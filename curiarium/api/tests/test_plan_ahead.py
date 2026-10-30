"""Tests for the plan-ahead delta check, the batch shape check and the timing report.

The script lives in curiarium/scripts, outside the API test image, so the
module skips itself there instead of failing the container gate. The delta
check answers questions about the caller's working directory, so every test
builds a throwaway repository in tmp_path: cheap, no network, and no repo
files borrowed from this checkout. Plans are written outside that repository
so its own tree stays clean.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wave_plan.py"
if not SCRIPT.exists():
    pytest.skip("host-only scheduler tooling (not present in the API image)", allow_module_level=True)
if shutil.which("git") is None:
    pytest.skip("the delta check shells out to git", allow_module_level=True)

# Passed per call so no test depends on a global identity, and nothing here
# names a branch: only captured shas and HEAD.
IDENTITY = ("-c", "user.name=Plan Ahead", "-c", "user.email=plan-ahead@example.invalid", "-c", "commit.gpgsign=false")
TOUCH = "curiarium/api/routers/library.py"
LANE_TOUCHES = (
    "curiarium/api/routers/library.py",
    "curiarium/web/src/ui/LicenceChip.tsx",
    "curiarium/slicer-bridge/cmd/slicer-bridge/main.go",
    "curiarium/api/routers/assets.py",
)


def git(cwd: Path, *arguments: str) -> str:
    """One git command in the fixture repository, with an inline identity."""
    result = subprocess.run(
        ["git", *IDENTITY, *arguments],
        capture_output=True,
        check=False,
        cwd=cwd,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit(cwd: Path, message: str, *paths: str) -> str:
    """Write one file per path, commit everything, and return the new HEAD sha."""
    for name in paths:
        target = cwd / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{message}\n{name}\n", encoding="utf-8")
    git(cwd, "add", "--all")
    git(cwd, "commit", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


def run(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the script with `cwd` as the caller's directory, which the delta check reads."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        check=False,
        cwd=cwd,
        text=True,
        timeout=60,
    )


def plan_payload(**overrides: object) -> dict[str, object]:
    """A complete per-ticket plan, so a test overrides only what it is about."""
    payload: dict[str, object] = {
        "id": "Mf-z5qa",
        "touches": [TOUCH],
        "serialises": False,
        "reason": "the scheduler wave planner",
        "base": "0" * 40,
        "approach": "extend the planner with a delta check",
        "risks": ["the base commit moves under the plan"],
        "acceptance": {"AC-1": "a stale plan exits 1 and names the path"},
        "gates": [{"gate": "plan", "seconds": 877, "oracle_calls": 2, "overlapped_with": "Mf-0bl6", "verdict": "approved"}],
    }
    payload.update(overrides)
    return payload


def write_payload(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_plan(path: Path, **overrides: object) -> Path:
    return write_payload(path, plan_payload(**overrides))


def write_wave_from_plans(path: Path, *plans: Path) -> Path:
    """Build the wave the way the scheduler does: one lane per dispatched plan file."""
    lanes = []
    for plan_path in plans:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        lanes.append(
            {
                "id": payload["id"],
                "touches": payload["touches"],
                "serialises": payload["serialises"],
                "reason": payload["reason"],
            }
        )
    path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    return path


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """An empty git repository with one seed commit that touches nothing declared."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    commit(root, "seed the repository", "seed.txt")
    return root


@pytest.fixture()
def four_plans(tmp_path: Path) -> list[Path]:
    """Four disjoint one-path plans, the raw material for the lane-width checks."""
    plans = tmp_path / "plans"
    return [
        write_plan(plans / f"Mf-lane{index}.json", id=f"Mf-lane{index}", touches=[touch], reason="a disjoint lane")
        for index, touch in enumerate(LANE_TOUCHES, start=1)
    ]


def test_fresh_plan_against_head_exits_zero(tmp_path: Path, repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base=head)
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 0, result.stderr
    assert "FRESH" in result.stdout
    assert "Mf-z5qa" in result.stdout
    assert "0 commit(s) since base" in result.stdout
    assert "changed outside the touch-set: none" in result.stdout
    assert "warning:" not in result.stdout


def test_stale_plan_on_a_touch_set_hit_exits_one(tmp_path: Path, repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, "Mf-other: edit the router the plan declares", TOUCH)
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base=base)
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 1
    assert result.stdout == ""
    assert "STALE" in result.stderr
    assert "re-plan" in result.stderr
    assert TOUCH in result.stderr


def test_a_plan_survives_an_unrelated_merge(tmp_path: Path, repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, "Mf-other: widen the gate", "Makefile", "docs/notes.md")
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base=base)
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 0, result.stderr
    assert "FRESH" in result.stdout
    assert "1 commit(s) since base" in result.stdout
    assert "Makefile" in result.stdout
    assert "docs/notes.md" in result.stdout
    # The exit-0 contract is only meaningful if this annotation really prints.
    assert "serialiser: Makefile" in result.stdout
    assert "it is the gate" in result.stdout


def test_a_non_ascii_path_still_matches_the_touch_set(tmp_path: Path, repo: Path) -> None:
    # git C-quotes a non-ASCII path unless asked not to, and a quoted path never
    # matches the touch-set: the plan would read as fresh while it is stale.
    base = git(repo, "rev-parse", "HEAD")
    unusual = "docs/r\u00e9sum\u00e9.md"
    commit(repo, "Mf-other: add an accented note", unusual)
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base=base, touches=[unusual])
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 1
    assert unusual in result.stderr


def test_unknown_base_fails_closed(tmp_path: Path, repo: Path) -> None:
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base="f" * 40)
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 1
    assert "does not resolve" in result.stderr
    assert result.stdout == ""


def test_non_ancestor_base_fails_closed(tmp_path: Path, repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    side = commit(repo, "Mf-other: work that never merges", "side.txt")
    git(repo, "reset", "--hard", base)
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base=side)
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 1
    assert "is not an ancestor" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param("{not json", "", id="invalid_json"),
        pytest.param(json.dumps(plan_payload(touches=[])), "touches must be a non-empty list of strings", id="empty_touches"),
        pytest.param(
            json.dumps(plan_payload(touches=[TOUCH, 7])),
            "touches must be a non-empty list of strings",
            id="touches_not_strings",
        ),
        pytest.param(json.dumps({key: value for key, value in plan_payload().items() if key != "base"}), "base must be", id="missing_base"),
    ],
)
def test_malformed_plan_exits_two(tmp_path: Path, repo: Path, payload: str, expected: str) -> None:
    plan = tmp_path / "plans" / "plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(payload, encoding="utf-8")
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 2, result.stdout
    assert "error:" in result.stderr
    if expected:
        assert expected in result.stderr


def test_outside_a_git_work_tree_fails_closed(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base="0" * 40)
    result = run(plain, "--check-delta", str(plan))
    assert result.returncode == 1
    assert "not inside a git work tree" in result.stderr


def test_an_incomplete_plan_still_warns_on_a_fresh_delta(tmp_path: Path, repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base=head, approach="", acceptance={})
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 0, result.stderr
    assert "FRESH" in result.stdout
    assert "warning: Mf-z5qa: the plan has no approach" in result.stdout
    assert "warning: Mf-z5qa: the plan has no acceptance records" in result.stdout


def test_a_serialiser_touch_warns_and_still_exits_zero(tmp_path: Path, repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json", base=head, touches=["Makefile"])
    result = run(repo, "--check-delta", str(plan))
    assert result.returncode == 0, result.stderr
    assert "warning: Mf-z5qa" in result.stdout
    assert "serialiser (Makefile)" in result.stdout
    assert "it is the gate" in result.stdout
    assert "cannot ride a lane" in result.stdout


def test_report_tolerates_a_gates_less_plan(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_plan(plans / "Mf-gated.json", id="Mf-gated")
    in_flight = plan_payload(id="Mf-inflight")
    del in_flight["gates"]
    write_payload(plans / "Mf-inflight.json", in_flight)
    result = run(tmp_path, "--report-timings", str(plans))
    assert result.returncode == 0, result.stderr
    assert "Mf-gated" in result.stdout
    assert "Mf-inflight" in result.stdout
    assert "not recorded" in result.stdout
    assert "warning: Mf-inflight: timings are unknown" in result.stdout


def test_report_aggregates_plan_gate_costs(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_plan(
        plans / "Mf-two.json",
        id="Mf-two",
        gates=[
            {"gate": "plan", "seconds": 300, "oracle_calls": 2, "overlapped_with": "Mf-0bl6"},
            {"gate": "plan", "seconds": 300, "oracle_calls": 3, "overlapped_with": "Mf-0bl6"},
            {"gate": "commit", "seconds": 120, "oracle_calls": 4},
        ],
    )
    write_plan(plans / "Mf-zero.json", id="Mf-zero", gates=[{"gate": "plan", "seconds": 0, "oracle_calls": 1}])
    result = run(tmp_path, "--report-timings", str(plans))
    assert result.returncode == 0, result.stderr
    assert "Mf-0bl6" in result.stdout
    assert "plan_gate_s 600.0s" in result.stdout
    assert "replans 1" in result.stdout
    assert "oracle_calls 10" in result.stdout
    assert "warning: Mf-zero: a plan gate reports 0s" in result.stdout
    assert "no OpenTelemetry instrumentation" in result.stdout
    # A self-reported zero is warned about and never summed or printed as a measurement.
    zero_row = next(line for line in result.stdout.splitlines() if line.startswith("Mf-zero"))
    assert "not recorded" in zero_row


def test_report_does_not_accept_a_non_finite_timing(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_plan(plans / "Mf-nan.json", id="Mf-nan", gates=[{"gate": "plan", "seconds": float("nan"), "oracle_calls": 1}])
    result = run(tmp_path, "--report-timings", str(plans))
    assert result.returncode == 0, result.stderr
    assert "warning: Mf-nan: a plan gate record has no numeric seconds" in result.stdout
    assert "nan" not in result.stdout.replace("Mf-nan", "")


def test_report_warns_when_the_file_name_disagrees_with_the_id(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_plan(plans / "Mf-copied.json", id="Mf-original")
    result = run(tmp_path, "--report-timings", str(plans))
    assert result.returncode == 0, result.stderr
    assert "warning: Mf-copied.json holds plan Mf-original" in result.stdout


def test_report_skips_an_unreadable_plan(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_plan(plans / "Mf-good.json", id="Mf-good")
    (plans / "broken.json").write_text("{not json", encoding="utf-8")
    result = run(tmp_path, "--report-timings", str(plans))
    assert result.returncode == 0, result.stderr
    assert "Mf-good" in result.stdout
    assert "skipped as unreadable or malformed" in result.stdout
    assert "warning: skipping" in result.stderr


def test_report_on_a_directory_without_plans_is_a_usage_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = run(tmp_path, "--report-timings", str(empty))
    assert missing.returncode == 2
    assert "holds no *.json plan files" in missing.stderr
    absent = run(tmp_path, "--report-timings", str(tmp_path / "nowhere"))
    assert absent.returncode == 2
    assert "is not a directory" in absent.stderr


def test_max_lanes_four_is_a_usage_error(repo: Path) -> None:
    result = run(repo, "--lane", "Mf-a:README.md", "--max-lanes", "4")
    assert result.returncode == 2
    assert "must be 1, 2 or 3" in result.stderr


def test_four_lane_wave_exceeds_the_hard_cap(tmp_path: Path, four_plans: list[Path]) -> None:
    wave = write_wave_from_plans(tmp_path / "wave.json", *four_plans)
    result = run(tmp_path, "--plan", str(wave), "--max-lanes", "3")
    assert result.returncode == 1
    assert "over max lanes: 4 > 3" in result.stderr


def test_the_default_cap_is_two_lanes(tmp_path: Path, four_plans: list[Path]) -> None:
    wave = write_wave_from_plans(tmp_path / "wave.json", *four_plans[:3])
    refused = run(tmp_path, "--plan", str(wave))
    assert refused.returncode == 1
    assert "over max lanes: 3 > 2" in refused.stderr
    accepted = run(tmp_path, "--plan", str(wave), "--max-lanes", "3")
    assert accepted.returncode == 0, accepted.stderr
    assert "wave accepted: 3 lane(s), max 3" in accepted.stdout


def test_the_new_modes_are_mutually_exclusive(tmp_path: Path) -> None:
    plan = write_plan(tmp_path / "plans" / "Mf-z5qa.json")
    combined = run(tmp_path, "--check-delta", str(plan), "--plan", str(plan))
    assert combined.returncode == 2
    assert "not allowed with argument" in combined.stderr
    reported = run(tmp_path, "--report-timings", str(plan.parent), "--lane", "Mf-a:README.md")
    assert reported.returncode == 2
    shaped = run(tmp_path, "--check-shape", str(plan.parent), "--lane", "Mf-a:README.md")
    assert shaped.returncode == 2
    both_reports = run(tmp_path, "--check-shape", str(plan.parent), "--report-timings", str(plan.parent))
    assert both_reports.returncode == 2


SHARED = "curiarium/api/models.py"
WITHHELD_GUIDANCE = (
    "gate each remaining candidate just before its own dispatch: its base is the HEAD of that moment, so the delta "
    "check is empty by construction and the ticket cannot re-plan. At most one already-queued plan can go stale, so "
    "the batch re-plans at most once."
)


def write_batch(directory: Path, *plans: tuple[str, tuple[str, ...]]) -> list[Path]:
    """One plan file per (id, touches) pair, so a shape test declares only its touch-sets."""
    return [write_plan(directory / f"{plan_id}.json", id=plan_id, touches=list(touches)) for plan_id, touches in plans]


def test_shape_withholds_when_more_than_half_the_declared_plans_share_a_surface(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_batch(
        plans,
        ("Mf-a", (SHARED, "curiarium/api/routers/assets.py")),
        ("Mf-b", (SHARED, "curiarium/api/routers/library.py")),
        ("Mf-c", (SHARED,)),
    )
    result = run(tmp_path, "--check-shape", str(plans))
    assert result.returncode == 1
    assert "batch shape: 3 declared candidate(s), shared surface 1 path(s)" in result.stdout
    assert f"{SHARED}" in result.stdout
    surface_row = next(line for line in result.stdout.splitlines() if line.startswith(SHARED))
    assert "Mf-a, Mf-b, Mf-c" in surface_row
    assert "verdict: 3 of 3 declared candidates share a surface (> half) - plan-ahead WITHHELD" in result.stdout
    assert "plan-ahead withheld: 3 of 3 declared candidates share a surface" in result.stderr
    assert WITHHELD_GUIDANCE in result.stdout


def test_shape_proceeds_when_the_declared_touch_sets_are_disjoint(tmp_path: Path) -> None:
    # The batch-14 shape: disjoint touch-sets, one plan recording the overlap with the other's implementation.
    plans = tmp_path / "plans"
    write_plan(
        plans / "M3-7bb7.json",
        id="M3-7bb7",
        touches=["curiarium/api/snapshots.py"],
        gates=[{"gate": "plan", "seconds": 471, "oracle_calls": 1, "overlapped_with": None}],
    )
    write_plan(
        plans / "Mf-sc7l.json",
        id="Mf-sc7l",
        touches=["curiarium/api/routers/assets.py"],
        gates=[{"gate": "plan", "seconds": 297, "oracle_calls": 1, "overlapped_with": "M3-7bb7"}],
    )
    result = run(tmp_path, "--check-shape", str(plans))
    assert result.returncode == 0, result.stderr
    assert "shared surface 0 path(s)" in result.stdout
    assert "verdict: 0 of 2 declared candidates share a surface - plan-ahead proceeds" in result.stdout
    assert result.stderr == ""
    assert WITHHELD_GUIDANCE not in result.stdout


def test_shape_is_undetermined_below_two_plans(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_batch(plans, ("Mf-alone", (SHARED,)))
    result = run(tmp_path, "--check-shape", str(plans))
    assert result.returncode == 0, result.stderr
    assert "batch shape: 1 declared candidate(s), shared surface 0 path(s)" in result.stdout
    assert "verdict: shape undetermined with fewer than 2 declared candidates - plan-ahead proceeds" in result.stdout


def test_shape_exactly_half_does_not_withhold(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_batch(
        plans,
        ("Mf-a", (SHARED, "curiarium/api/audit.py")),
        ("Mf-b", (SHARED, "curiarium/api/config.py")),
        ("Mf-c", ("curiarium/api/routers/assets.py",)),
        ("Mf-d", ("curiarium/api/routers/library.py",)),
    )
    result = run(tmp_path, "--check-shape", str(plans))
    assert result.returncode == 0, result.stderr
    assert "verdict: 2 of 4 declared candidates share a surface - plan-ahead proceeds" in result.stdout


def test_shape_counts_a_shared_serialiser_as_a_shared_surface(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_batch(plans, ("Mf-a", ("Makefile",)), ("Mf-b", ("Makefile",)))
    result = run(tmp_path, "--check-shape", str(plans))
    assert result.returncode == 1
    assert "Makefile" in result.stdout
    assert "verdict: 2 of 2 declared candidates share a surface (> half) - plan-ahead WITHHELD" in result.stdout


def test_shape_replay_compares_the_recorded_and_policy_costs(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_plan(
        plans / "Mf-a.json",
        id="Mf-a",
        touches=[SHARED],
        gates=[
            {"gate": "plan", "seconds": 100, "oracle_calls": 1},
            {"gate": "plan", "seconds": 40, "oracle_calls": 1},
        ],
    )
    write_plan(
        plans / "Mf-b.json",
        id="Mf-b",
        touches=[SHARED],
        gates=[
            {"gate": "plan", "seconds": 200, "oracle_calls": 1},
            {"gate": "plan", "seconds": 90, "oracle_calls": 1},
        ],
    )
    write_plan(
        plans / "Mf-c.json",
        id="Mf-c",
        touches=[SHARED],
        gates=[
            {"gate": "plan", "seconds": 300, "oracle_calls": 1},
            {"gate": "plan", "seconds": 70, "oracle_calls": 1},
        ],
    )
    result = run(tmp_path, "--check-shape", str(plans))
    assert result.returncode == 1
    assert "recorded: 6 plan gates, 800.0s, 3 re-plan(s), 6 oracle calls" in result.stdout
    # 100 + 200 + 300 first-gate seconds, plus the largest recorded re-plan (90).
    assert "policy:   4 plan gates (3 first + at most one re-plan), <= 690.0s, <=1 re-plan" in result.stdout
    assert "replay over the recorded plans, not a re-run" in result.stdout


def test_shape_replay_is_silent_without_measured_gates(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    gates_less = plan_payload(id="Mf-inflight", touches=[SHARED])
    del gates_less["gates"]
    write_payload(plans / "Mf-inflight.json", gates_less)
    write_plan(
        plans / "Mf-nonnumeric.json",
        id="Mf-nonnumeric",
        touches=[SHARED],
        gates=[{"gate": "plan", "seconds": "slow", "oracle_calls": 1}],
    )
    result = run(tmp_path, "--check-shape", str(plans))
    assert result.returncode == 1
    assert "verdict: 2 of 2 declared candidates share a surface (> half) - plan-ahead WITHHELD" in result.stdout
    assert "recorded:" not in result.stdout
    assert "policy:" not in result.stdout


def test_shape_skips_a_malformed_plan_with_a_warning(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    write_batch(plans, ("Mf-a", (SHARED,)), ("Mf-b", (SHARED,)))
    (plans / "broken.json").write_text("{not json", encoding="utf-8")
    result = run(tmp_path, "--check-shape", str(plans), "--json")
    assert result.returncode == 1
    assert "warning: skipping" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["declared"] == 2
    assert payload["skipped"] == 1
    assert payload["withheld"] is True


def test_shape_on_a_directory_without_plans_is_a_usage_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    missing = run(tmp_path, "--check-shape", str(empty))
    assert missing.returncode == 2
    assert "holds no *.json plan files" in missing.stderr
    absent = run(tmp_path, "--check-shape", str(tmp_path / "nowhere"))
    assert absent.returncode == 2
    assert "is not a directory" in absent.stderr
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "broken.json").write_text("{not json", encoding="utf-8")
    unreadable = run(tmp_path, "--check-shape", str(broken))
    assert unreadable.returncode == 2
    assert "holds no readable plan files (1 skipped)" in unreadable.stderr


def test_shape_json_reports_the_verdict(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    write_batch(shared, ("Mf-a", (SHARED,)), ("Mf-b", (SHARED,)), ("Mf-c", ("Makefile",)))
    withheld = run(tmp_path, "--check-shape", str(shared), "--json")
    assert withheld.returncode == 1
    payload = json.loads(withheld.stdout)
    assert payload["declared"] == 3
    assert payload["shared"] == 2
    assert payload["withheld"] is True
    assert payload["surface"] == {SHARED: ["Mf-a", "Mf-b"]}
    assert "plan-ahead withheld: 2 of 3 declared candidates share a surface" in withheld.stderr
    assert "replay" not in withheld.stdout
    disjoint = tmp_path / "disjoint"
    write_batch(disjoint, ("Mf-a", (SHARED,)), ("Mf-b", ("Makefile",)))
    fresh = run(tmp_path, "--check-shape", str(disjoint), "--json")
    assert fresh.returncode == 0, fresh.stderr
    fresh_payload = json.loads(fresh.stdout)
    assert fresh_payload["withheld"] is False
    assert fresh_payload["surface"] == {}


def test_report_timings_prints_the_shape_verdict(tmp_path: Path) -> None:
    disjoint = tmp_path / "disjoint"
    write_batch(disjoint, ("Mf-a", ("curiarium/api/routers/assets.py",)), ("Mf-b", ("Makefile",)))
    proceeded = run(tmp_path, "--report-timings", str(disjoint))
    assert proceeded.returncode == 0, proceeded.stderr
    assert "shape: 0 of 2 declared candidates share a surface - plan-ahead proceeds" in proceeded.stdout
    shared = tmp_path / "shared"
    write_batch(shared, ("Mf-a", (SHARED,)), ("Mf-b", (SHARED,)))
    withheld = run(tmp_path, "--report-timings", str(shared))
    assert withheld.returncode == 0, withheld.stderr
    assert "shape: 2 of 2 declared candidates share a surface - plan-ahead withheld" in withheld.stdout
    assert "totals: 2 plan(s) reported" in withheld.stdout
