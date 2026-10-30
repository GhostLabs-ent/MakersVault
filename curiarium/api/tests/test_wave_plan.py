"""Tests for the scheduler wave planner (host-only tooling).

The script lives in curiarium/scripts, outside the API test image, so the
module skips itself there instead of failing the container gate.
"""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wave_plan.py"
if not SCRIPT.exists():
    pytest.skip("host-only scheduler tooling (not present in the API image)", allow_module_level=True)

REPO_ROOT = SCRIPT.parents[2]

# The migration entries name paths that do not exist yet: migrations live in
# migrations.py, which this ticket keeps exactly as is, so existence cannot be
# asserted for them. They must instead match their canonical future path, and
# this exemption must stay exactly these two entries so a third zombie cannot hide.
FORWARD_LOOKING = frozenset({("glob", "**/migration_*.py"), ("dir", "curiarium/api/migrations")})

# Directory spellings the ledger no longer serialises: no markdown table row may
# carry one backticked as a token (row-scoped and trailing-slash so the accepted-
# hole prose and the usage example cannot false-positive).
OLD_DIRECTORY_SPELLINGS = frozenset(
    {
        "curiarium/scripts/",
        "src/ui/asset-grid/",
        "src/ui/settings/",
        "curiarium/web/src/ui/asset-grid/",
        "curiarium/web/src/ui/settings/",
    }
)


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("wave_plan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wave_plan = load_script()


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return [path for path in result.stdout.split("\0") if path.strip()]


def document_section(path: Path, heading: str) -> str:
    """The section from `heading` up to the next markdown heading (any level)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(heading))
    following = lines[start + 1 :]
    end = next((index for index, line in enumerate(following) if line.startswith("#")), len(following))
    return "\n".join([lines[start], *following[:end]])


def write_plan(path: Path, lanes: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    return path


def test_help_exits_zero() -> None:
    result = run("--help")
    assert result.returncode == 0
    assert "usage" in result.stdout
    assert "--max-lanes" in result.stdout
    assert "--check-shape" in result.stdout


def test_list_serialisers_exits_zero() -> None:
    result = run("--list-serialisers")
    assert result.returncode == 0
    assert "curiarium/api/migrations.py" in result.stdout
    assert "Makefile" in result.stdout


def test_serialiser_data_is_unique_and_carries_a_reason() -> None:
    entries = wave_plan.SERIALISERS
    assert entries
    assert {kind for kind, _, _ in entries} <= {"path", "dir", "glob"}
    assert len(entries) == len({(kind, value) for kind, value, _ in entries})
    assert all(reason.strip() for _, _, reason in entries)
    assert ("path", "Makefile") in {(kind, value) for kind, value, _ in entries}


DOCUMENTED_SERIALISERS: list[tuple[str, str]] = [
    ("path", "curiarium/api/migrations.py"),
    ("glob", "**/migration_*.py"),
    ("dir", "curiarium/api/migrations"),
    ("glob", "curiarium/api/requirements*.txt"),
    ("glob", "curiarium/api/requirements*.lock"),
    ("glob", "**/package.json"),
    ("glob", "**/package-lock.json"),
    ("path", "Makefile"),
    ("glob", ".github/workflows/*"),
    ("glob", "**/nginx.conf"),
    ("path", "curiarium/web/security-headers.conf"),
    ("glob", "**/conftest.py"),
    ("path", "curiarium/scripts/container-smoke.sh"),
    ("path", "curiarium/scripts/wave_plan.py"),
    ("path", "curiarium/scripts/check_version.py"),
    ("path", "curiarium/api/Dockerfile"),
    ("path", "curiarium/web/Dockerfile"),
    ("path", "curiarium/docker-compose.yml"),
    ("path", "curiarium/docker-compose.deploy.yml"),
    ("path", "curiarium/docker-compose.smoke.yml"),
    ("path", "curiarium/docker-deploy.yml"),
    ("path", "curiarium/api/main.py"),
    ("path", "curiarium/api/models.py"),
    ("path", "curiarium/api/schemas/__init__.py"),
    ("path", "curiarium/web/src/lib/api/index.ts"),
    ("path", "curiarium/web/src/lib/api/baseUrl.ts"),
    ("path", "curiarium/web/src/lib/api/http.ts"),
    ("path", "curiarium/web/src/lib/api/grantPriming.ts"),
    ("path", "curiarium/web/src/ui/App.tsx"),
    ("path", "curiarium/web/src/ui/Sidebar.tsx"),
    ("path", "curiarium/web/src/ui/asset-grid/AssetGrid.tsx"),
    ("path", "curiarium/web/src/ui/settings/Settings.tsx"),
]


def test_serialiser_set_matches_the_documented_list() -> None:
    assert [(kind, value) for kind, value, _ in wave_plan.SERIALISERS] == DOCUMENTED_SERIALISERS


def test_no_directory_is_serialised_except_the_documented_one() -> None:
    assert [value for kind, value, _ in wave_plan.SERIALISERS if kind == "dir"] == ["curiarium/api/migrations"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required to resolve serialiser paths")
def test_every_serialiser_entry_resolves_to_an_existing_path() -> None:
    tracked = tracked_paths()
    unresolved = {
        (kind, value)
        for kind, value, _ in wave_plan.SERIALISERS
        if not any(wave_plan.match_serialiser(kind, value, path) for path in tracked)
    }
    assert unresolved == FORWARD_LOOKING
    assert wave_plan.match_serialiser("glob", "**/migration_*.py", "curiarium/api/migrations/migration_010_x.py")
    assert wave_plan.match_serialiser("dir", "curiarium/api/migrations", "curiarium/api/migrations/010_x.py")


def test_docs_quote_every_serialiser() -> None:
    documents = {
        "docs/TICKET_WORKFLOW.md": document_section(REPO_ROOT / "docs/TICKET_WORKFLOW.md", "### Serialisers"),
        ".pi/agents/scheduler.md": document_section(REPO_ROOT / ".pi/agents/scheduler.md", "## Hard serialisers"),
    }
    for name, section in documents.items():
        for _, value, _ in wave_plan.SERIALISERS:
            assert f"`{value}`" in section, f"{name} is missing serialiser `{value}`"
        for row in (line for line in section.splitlines() if line.startswith("|")):
            for token in re.findall(r"`([^`]+)`", row):
                assert token not in OLD_DIRECTORY_SPELLINGS, f"{name} still quotes the old directory {token}"


def test_a_new_file_beside_an_entry_point_does_not_serialise() -> None:
    for path in (
        "curiarium/scripts/new_helper.py",
        "curiarium/web/src/ui/asset-grid/useSomething.ts",
        "curiarium/web/src/ui/settings/useSomething.ts",
        "curiarium/api/schemas/assets.py",
        "curiarium/api/schemas/projects.py",
    ):
        result = run("--lane", f"Mf-6d52:{path}")
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""


def test_entry_files_still_serialise() -> None:
    for path in (
        "curiarium/scripts/container-smoke.sh",
        "curiarium/scripts/wave_plan.py",
        "curiarium/scripts/check_version.py",
        "curiarium/api/schemas/__init__.py",
        "curiarium/web/src/ui/asset-grid/AssetGrid.tsx",
        "curiarium/web/src/ui/settings/Settings.tsx",
    ):
        result = run("--lane", f"Mf-6d52:{path}")
        assert result.returncode == 1
        assert path in result.stderr
    sibling = run("--lane", "Mf-6d52:curiarium/web/src/ui/asset-grid/AssetGrid.test.tsx")
    assert sibling.returncode == 1
    assert "same-stem sibling of curiarium/web/src/ui/asset-grid/AssetGrid.tsx" in sibling.stderr


def test_accepts_two_disjoint_lanes() -> None:
    result = run(
        "--lane",
        "Mf-6d52:curiarium/api/routers/library.py,curiarium/api/permissions.py",
        "--lane",
        "Mf-nhhy:README.md,docs/architecture/CONFIGURATION.md",
    )
    assert result.returncode == 0, result.stderr
    assert "Mf-6d52" in result.stdout
    assert "Mf-nhhy" in result.stdout
    assert "disjoint" in result.stdout
    assert result.stderr == ""


def test_refuses_shared_file() -> None:
    result = run(
        "--lane",
        "Mf-6d52:curiarium/api/tests/test_permissions_matrix.py",
        "--lane",
        "Mf-nhhy:curiarium/api/tests/test_permissions_matrix.py",
    )
    assert result.returncode == 1
    assert "both touch curiarium/api/tests/test_permissions_matrix.py" in result.stderr
    assert result.stdout == ""


def test_two_lanes_overlap_on_a_now_lane_able_path() -> None:
    result = run(
        "--lane",
        "Mf-6d52:curiarium/web/src/ui/asset-grid/useSomething.ts,curiarium/api/permissions.py",
        "--lane",
        "Mf-nhhy:curiarium/web/src/ui/asset-grid/useSomething.ts,README.md",
    )
    assert result.returncode == 1
    assert "both touch curiarium/web/src/ui/asset-grid/useSomething.ts" in result.stderr


def test_refuses_serialiser_exact_path() -> None:
    result = run("--lane", "Mf-6d52:curiarium/api/migrations.py")
    assert result.returncode == 1
    assert "a serialiser (curiarium/api/migrations.py)" in result.stderr
    assert "the schema ledger" in result.stderr


def test_accepts_a_file_beside_an_entry_point() -> None:
    result = run("--lane", "Mf-6d52:curiarium/web/src/ui/asset-grid/AssetCard.tsx")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_refuses_serialiser_stem_sibling() -> None:
    result = run("--lane", "Mf-6d52:curiarium/web/src/ui/Sidebar.test.tsx")
    assert result.returncode == 1
    assert "same-stem sibling of curiarium/web/src/ui/Sidebar.tsx" in result.stderr


def test_refuses_over_max_lanes() -> None:
    result = run(
        "--lane",
        "Mf-a:README.md",
        "--lane",
        "Mf-b:docs/x.md",
        "--lane",
        "Mf-c:curiarium/api/routers/a.py",
        "--lane",
        "Mf-d:curiarium/slicer-bridge/cmd/slicer-bridge/main.go",
    )
    assert result.returncode == 1
    assert "over max lanes: 4 > 2" in result.stderr


def test_max_lanes_three_accepts_three_disjoint_lanes() -> None:
    lanes = (
        "Mf-a:curiarium/api/routers/library.py",
        "Mf-b:curiarium/web/src/ui/LicenceChip.tsx",
        "Mf-c:curiarium/slicer-bridge/cmd/slicer-bridge/main.go",
    )
    result = run("--lane", lanes[0], "--lane", lanes[1], "--lane", lanes[2], "--max-lanes", "3")
    assert result.returncode == 0, result.stderr
    assert "wave accepted: 3 lane(s), max 3" in result.stdout


def test_refuses_declared_serialises_from_plan(tmp_path: Path) -> None:
    plan = write_plan(
        tmp_path / "wave.json",
        [
            {
                "id": "Mf-6d52",
                "touches": ["curiarium/api/permissions.py"],
                "serialises": True,
                "reason": "needs migration 009",
            }
        ],
    )
    result = run("--plan", str(plan))
    assert result.returncode == 1
    assert "lane Mf-6d52 declared serialises: true (needs migration 009)" in result.stderr


def test_refuses_empty_touch_set() -> None:
    result = run("--lane", "Mf-nhhy:", "--lane", "Mf-6d52:README.md")
    assert result.returncode == 1
    assert "lane Mf-nhhy has an empty touch-set" in result.stderr


def test_refuses_absolute_path() -> None:
    result = run("--lane", "Mf-nhhy:/etc/passwd")
    assert result.returncode == 1
    assert "lane Mf-nhhy path /etc/passwd is outside the repo" in result.stderr


def test_refuses_parent_escape() -> None:
    result = run("--lane", "Mf-nhhy:../outside.py")
    assert result.returncode == 1
    assert "is outside the repo" in result.stderr


def test_refuses_duplicate_lane_id() -> None:
    result = run("--lane", "Mf-6d52:README.md", "--lane", "Mf-6d52:docs/x.md")
    assert result.returncode == 1
    assert "lane id Mf-6d52 appears twice" in result.stderr


def test_normalises_paths_before_comparing() -> None:
    result = run("--lane", "Mf-6d52:./docs//PERMISSIONS.md", "--lane", "Mf-nhhy:docs/PERMISSIONS.md")
    assert result.returncode == 1
    assert "both touch docs/PERMISSIONS.md" in result.stderr


def test_shared_directory_is_a_warning_not_a_refusal() -> None:
    result = run(
        "--lane",
        "Mf-6d52:curiarium/api/tests/test_audit_log.py",
        "--lane",
        "Mf-nhhy:curiarium/api/tests/test_user_roles.py",
    )
    assert result.returncode == 0, result.stderr
    assert "warning:" in result.stdout
    assert "curiarium/api/tests/" in result.stdout


def test_json_reports_accepted_wave(tmp_path: Path) -> None:
    plan = write_plan(
        tmp_path / "wave.json",
        [
            {"id": "Mf-6d52", "touches": ["curiarium/api/permissions.py"]},
            {"id": "Mf-nhhy", "touches": ["README.md"], "reason": "docs only"},
        ],
    )
    result = run("--plan", str(plan), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["accepted"] is True
    assert payload["reason"] is None
    assert [lane["id"] for lane in payload["lanes"]] == ["Mf-6d52", "Mf-nhhy"]
    assert [lane["files"] for lane in payload["lanes"]] == [1, 1]
    assert [lane["serialises"] for lane in payload["lanes"]] == [False, False]


def test_json_reports_refusal() -> None:
    result = run("--lane", "Mf-6d52:README.md", "--lane", "Mf-nhhy:README.md", "--json")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["accepted"] is False
    assert "both touch README.md" in payload["reason"]
    assert "both touch README.md" in result.stderr


def test_max_lanes_out_of_range_is_a_usage_error() -> None:
    for limit in ("0", "4"):
        result = run("--lane", "Mf-6d52:README.md", "--max-lanes", limit)
        assert result.returncode == 2
        assert "must be 1, 2 or 3" in result.stderr


def test_lane_and_plan_are_mutually_exclusive(tmp_path: Path) -> None:
    plan = write_plan(tmp_path / "wave.json", [{"id": "Mf-6d52", "touches": ["README.md"]}])
    result = run("--lane", "Mf-nhhy:docs/x.md", "--plan", str(plan))
    assert result.returncode == 2
