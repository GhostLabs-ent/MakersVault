"""Tests for the scheduler wave planner (host-only tooling).

The script lives in makervault/scripts, outside the API test image, so the
module skips itself there instead of failing the container gate.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "wave_plan.py"
if not SCRIPT.exists():
    pytest.skip("host-only scheduler tooling (not present in the API image)", allow_module_level=True)


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


def write_plan(path: Path, lanes: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    return path


def test_help_exits_zero() -> None:
    result = run("--help")
    assert result.returncode == 0
    assert "usage" in result.stdout
    assert "--max-lanes" in result.stdout


def test_list_serialisers_exits_zero() -> None:
    result = run("--list-serialisers")
    assert result.returncode == 0
    assert "makervault/api/migrations.py" in result.stdout
    assert "Makefile" in result.stdout


def test_serialiser_data_is_unique_and_carries_a_reason() -> None:
    entries = wave_plan.SERIALISERS
    assert entries
    assert {kind for kind, _, _ in entries} <= {"path", "dir", "glob"}
    assert len(entries) == len({(kind, value) for kind, value, _ in entries})
    assert all(reason.strip() for _, _, reason in entries)
    assert ("path", "Makefile") in {(kind, value) for kind, value, _ in entries}


def test_accepts_two_disjoint_lanes() -> None:
    result = run(
        "--lane",
        "Mf-6d52:makervault/api/routers/library.py,makervault/api/permissions.py",
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
        "Mf-6d52:makervault/api/tests/test_permissions_matrix.py",
        "--lane",
        "Mf-nhhy:makervault/api/tests/test_permissions_matrix.py",
    )
    assert result.returncode == 1
    assert "both touch makervault/api/tests/test_permissions_matrix.py" in result.stderr
    assert result.stdout == ""


def test_refuses_serialiser_exact_path() -> None:
    result = run("--lane", "Mf-6d52:makervault/api/migrations.py")
    assert result.returncode == 1
    assert "a serialiser (makervault/api/migrations.py)" in result.stderr
    assert "the schema ledger" in result.stderr


def test_refuses_serialiser_directory_prefix() -> None:
    result = run("--lane", "Mf-6d52:makervault/web/src/ui/asset-grid/AssetCard.tsx")
    assert result.returncode == 1
    assert "a serialiser (makervault/web/src/ui/asset-grid)" in result.stderr


def test_refuses_serialiser_stem_sibling() -> None:
    result = run("--lane", "Mf-6d52:makervault/web/src/ui/Sidebar.test.tsx")
    assert result.returncode == 1
    assert "same-stem sibling of makervault/web/src/ui/Sidebar.tsx" in result.stderr


def test_refuses_over_max_lanes() -> None:
    result = run(
        "--lane",
        "Mf-a:README.md",
        "--lane",
        "Mf-b:docs/x.md",
        "--lane",
        "Mf-c:makervault/api/routers/a.py",
        "--lane",
        "Mf-d:makervault/slicer-bridge/cmd/slicer-bridge/main.go",
    )
    assert result.returncode == 1
    assert "over max lanes: 4 > 2" in result.stderr


def test_max_lanes_three_accepts_three_disjoint_lanes() -> None:
    lanes = (
        "Mf-a:makervault/api/routers/library.py",
        "Mf-b:makervault/web/src/ui/LicenceChip.tsx",
        "Mf-c:makervault/slicer-bridge/cmd/slicer-bridge/main.go",
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
                "touches": ["makervault/api/permissions.py"],
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
        "Mf-6d52:makervault/api/tests/test_audit_log.py",
        "--lane",
        "Mf-nhhy:makervault/api/tests/test_user_roles.py",
    )
    assert result.returncode == 0, result.stderr
    assert "warning:" in result.stdout
    assert "makervault/api/tests/" in result.stdout


def test_json_reports_accepted_wave(tmp_path: Path) -> None:
    plan = write_plan(
        tmp_path / "wave.json",
        [
            {"id": "Mf-6d52", "touches": ["makervault/api/permissions.py"]},
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
