"""Guard ADR 0003 (retiring Asset.collection) against documentation drift.

This is a docs-drift guard, not a behavior test: it binds the ADR to the runbook
queue item and truth-ledger row that record the decision, so a later edit cannot
quietly drop one half of it.

Pure pathlib with no imports from the API, consistent with the other doc guards.
The guarded docs live above the API directory, so the module skips itself in the
container, where `makervault/api` is the whole build context.
"""

from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
MAKERVAULT_ROOT = API_ROOT.parent
REPO_ROOT = MAKERVAULT_ROOT.parent

ADR_DIR = MAKERVAULT_ROOT / "docs" / "adr"
RUNBOOK_PATH = MAKERVAULT_ROOT / "docs" / "ARCHITECTURE_RUNBOOK.md"

# Every test below guards ADR 0003 and/or the runbook, so the whole module is
# host-only. Both paths are absent inside the API image (build context is
# makervault/api, which becomes /app), but requiring both to be missing keeps a
# half-deleted docs tree failing loudly on a real checkout instead of skipping.
if not ADR_DIR.is_dir() and not RUNBOOK_PATH.exists():
    pytest.skip(
        "ADR guard is host-only (the API image builds from makervault/api, so "
        "the repo README.md and makervault/docs/ are absent)",
        allow_module_level=True,
    )

ADR_QUEUE_ANCHOR = "initial required ADR queue"
TRUTH_LEDGER_HEADING = "### 5.3 Truth ledger"
REQUIRED_ADR_HEADINGS = (
    "## Context",
    "## Decision",
    "## Consequences",
    "## Alternatives considered",
    "## Rollback",
    "## Verification",
    "## Superseding conditions",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _read_text(path).splitlines()


def _adr_0003_path() -> Path:
    matches = sorted(ADR_DIR.glob("0003-*.md"))
    assert len(matches) == 1, (
        f"makervault/docs/adr must hold exactly one 0003-*.md file, found: "
        f"{[match.name for match in matches]}"
    )
    return matches[0]


def _section_after_anchor(lines: list[str], anchor: str) -> list[str]:
    """Lines from the anchor line up to (excluding) the next markdown heading."""
    start = next(
        (index for index, line in enumerate(lines) if anchor in line),
        None,
    )
    assert start is not None, f"ARCHITECTURE_RUNBOOK.md has no {anchor!r} section"
    section: list[str] = []
    for line in lines[start:]:
        if section and line.startswith("#"):
            break
        section.append(line)
    return section


def _truth_ledger_lines() -> list[str]:
    lines = _lines(RUNBOOK_PATH)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == TRUTH_LEDGER_HEADING),
        None,
    )
    assert start is not None, f"ARCHITECTURE_RUNBOOK.md has no {TRUTH_LEDGER_HEADING!r} section"
    section: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        section.append(line)
    return section


def test_exactly_one_adr_0003_file() -> None:
    assert _adr_0003_path().is_file()


def test_adr_0003_is_accepted_with_the_required_sections() -> None:
    adr_path = _adr_0003_path()
    text = _read_text(adr_path)
    assert "**Status:** Accepted" in text, f"{adr_path.name} is not marked Status: Accepted"
    for heading in REQUIRED_ADR_HEADINGS:
        assert heading in text, f"{adr_path.name} is missing the {heading!r} section"


def test_adr_0003_retires_collection() -> None:
    text = _read_text(_adr_0003_path()).lower()
    assert "retir" in text, (
        f"{_adr_0003_path().name} does not state that Asset.collection is being retired"
    )


def test_runbook_adr_queue_references_adr_0003() -> None:
    section = _section_after_anchor(_lines(RUNBOOK_PATH), ADR_QUEUE_ANCHOR)
    assert "0003" in "\n".join(section), (
        "the runbook's ADR queue does not reference 0003; the queue item must annotate "
        "ADR 0003 rather than drop it"
    )


def test_runbook_truth_ledger_records_collection() -> None:
    section = "\n".join(_truth_ledger_lines()).lower()
    assert "collection" in section, (
        "the runbook truth ledger no longer mentions collection; the T-021 row for the "
        "ADR 0003 decision must survive"
    )
