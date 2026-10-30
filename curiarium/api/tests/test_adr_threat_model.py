"""Guard ADR 0004 (token and cookie threat model) and ADR 0005 (file grants).

This is a docs-drift guard, not a behavior test: it binds the ADRs to the runbook
queue item, the truth-ledger rows and the Gate 0 dispositions that record the
same decisions, so a later edit cannot quietly drop one half of them. The
cross-file ticket check is the point of the module - the ADR, the runbook and
the Gate 0 table must name the same follow-up implementation ticket.

ADR 0004 is now history: `M3-7bb7` landed the signed grants, so 0004 is
`Superseded` and the tests below guard (a) its record of what was decided in
2026-10-29, including the access-log surface it admitted, and (b) its
supersession link to ADR 0005, which is the ADR for the shipped design. The
import-cookie decision (MV-SEC-017) and the `localStorage` acceptance
(MV-SEC-008) are still 0004's and are still pinned here. Deleting 0004 would
remove the only written record of the interim risk that was accepted, so the
supersession is asserted rather than assumed.

Pure pathlib with no imports from the API, consistent with the other doc guards.
The guarded docs live above the API directory, so the module skips itself in the
container, where `curiarium/api` is the whole build context.
"""

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
CURIARIUM_ROOT = API_ROOT.parent

ADR_DIR = CURIARIUM_ROOT / "docs" / "adr"
RUNBOOK_PATH = CURIARIUM_ROOT / "docs" / "ARCHITECTURE_RUNBOOK.md"
GATE_0_PATH = CURIARIUM_ROOT / "docs" / "security" / "GATE_0_REVALIDATION.md"

# Every test below guards the ADR and/or one of the two host-only docs, so the
# whole module is host-only. All three paths are absent inside the API image
# (build context is curiarium/api, which becomes /app), but requiring all three
# to be missing keeps a half-deleted docs tree failing loudly on a real checkout
# instead of skipping.
if not ADR_DIR.is_dir() and not RUNBOOK_PATH.exists() and not GATE_0_PATH.exists():
    pytest.skip(
        "ADR 0004 guard is host-only (the API image builds from curiarium/api, so "
        "curiarium/docs/ is absent)",
        allow_module_level=True,
    )

ADR_QUEUE_ANCHOR = "initial required ADR queue"
QUEUE_ITEM_ANCHOR = "browser-to-bridge handoff grants"
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
MIGRATION_TARGET_PHRASE = "file-scoped signed grants"
MIGRATION_TARGET_ADJECTIVE = "short-lived"
MITIGATION_IDENTIFIERS = (
    "AUTH_ACCESS_TOKEN_TTL",
    "stableFileUrl",
    "redactURL",
    "sessionStorage",
)
STALE_TOKEN_ROW_STRINGS = ("12-hour", "no identifier or revocation store")
STALE_THROTTLE_PHRASE = "Login has no throttle"
TICKET_ROW_IDS = ("MV-SEC-007", "MV-SEC-017")
TICKET_ID_RE = re.compile(r"Mf-[A-Za-z0-9]+|M3-[A-Za-z0-9]+")
# ADR 0005 is the shipped grant design; these are the strings that make it
# describe the code rather than a wish: the mint route, its verifier, the log
# fixes and the implementation ticket.
ADR_0005_REQUIRED_STRINGS = (
    "POST /file-grants",
    "require_auth_or_file_grant",
    "log_format",
    "--no-access-log",
    "M3-7bb7",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lines(path: Path) -> list[str]:
    return _read_text(path).splitlines()


def _adr_0004_path() -> Path:
    matches = sorted(ADR_DIR.glob("0004-*.md"))
    assert len(matches) == 1, (
        f"curiarium/docs/adr must hold exactly one 0004-*.md file, found: "
        f"{[match.name for match in matches]}"
    )
    return matches[0]


def _adr_text() -> str:
    return _read_text(_adr_0004_path())


def _adr_0005_path() -> Path:
    matches = sorted(ADR_DIR.glob("0005-*.md"))
    assert len(matches) == 1, (
        f"curiarium/docs/adr must hold exactly one 0005-*.md file, found: "
        f"{[match.name for match in matches]}"
    )
    return matches[0]


def _adr_0005_text() -> str:
    return _read_text(_adr_0005_path())


def _section(text: str, heading: str) -> str:
    """The body of `heading`, up to (excluding) the next markdown heading."""
    match = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    assert match is not None, f"ADR 0004 has no {heading!r} section"
    following = re.search(r"^#{1,2} ", text[match.end() :], re.MULTILINE)
    body = text[match.end() :]
    return body if following is None else body[: following.start()]


def _decision_section() -> str:
    return _section(_adr_text(), "## Decision")


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


def _queue_item_line() -> str:
    """The runbook ADR-queue line for the browser-to-bridge handoff grants."""
    section = _section_after_anchor(_lines(RUNBOOK_PATH), ADR_QUEUE_ANCHOR)
    line = next((item for item in section if QUEUE_ITEM_ANCHOR in item), None)
    assert line is not None, (
        f"the runbook ADR queue has no item mentioning {QUEUE_ITEM_ANCHOR!r}; the queue "
        "item must annotate ADR 0004 rather than drop it"
    )
    return line


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


def _ledger_row(row_id: str) -> str:
    row = next((line for line in _truth_ledger_lines() if line.startswith(f"| {row_id} ")), None)
    assert row is not None, f"the runbook truth ledger has no {row_id} row"
    return row


def _gate_rows() -> dict[str, str]:
    """Every MV-SEC-* disposition row, keyed by finding id."""
    rows: dict[str, str] = {}
    for line in _lines(GATE_0_PATH):
        if not line.startswith("| "):
            continue
        row_id = line.split("|")[1].strip()
        if re.fullmatch(r"MV-SEC-\d+", row_id):
            rows[row_id] = line
    return rows


def _gate_row(row_id: str) -> str:
    rows = _gate_rows()
    assert row_id in rows, f"GATE_0_REVALIDATION.md has no {row_id} row"
    return rows[row_id]


def test_exactly_one_adr_0004_file() -> None:
    assert _adr_0004_path().is_file()


def test_adr_0004_opens_with_its_title() -> None:
    path = _adr_0004_path()
    first_line = _lines(path)[0]
    assert re.match(r"^# ADR 0004: ", first_line), (
        f"{path.name} must open with '# ADR 0004: ', found {first_line!r}"
    )


def test_adr_0004_is_superseded_with_the_required_sections() -> None:
    path = _adr_0004_path()
    text = _adr_text()
    assert "**Status:** Superseded" in text, (
        f"{path.name} is not marked Status: Superseded; the file-URL half of it was "
        "implemented in M3-7bb7 and is now ADR 0005"
    )
    assert "0005" in text, (
        f"{path.name} does not name its successor; a superseded ADR that does not link "
        "the replacement hides which design is live"
    )
    for heading in REQUIRED_ADR_HEADINGS:
        assert heading in text, f"{path.name} is missing the {heading!r} section"


def test_decision_names_the_migration_target() -> None:
    decision = _decision_section()
    assert MIGRATION_TARGET_PHRASE in decision, (
        "the Decision section does not name file-scoped signed grants as the migration "
        "target; a mention in Context does not satisfy the decision"
    )
    assert MIGRATION_TARGET_ADJECTIVE in decision, (
        f"the Decision section does not call the grants {MIGRATION_TARGET_ADJECTIVE}"
    )


def test_follow_up_ticket_is_named_in_adr_runbook_and_gate_0() -> None:
    decision_ids = set(TICKET_ID_RE.findall(_decision_section()))
    assert decision_ids, "the Decision section names no follow-up ticket id"

    queue_ids = set(TICKET_ID_RE.findall(_queue_item_line()))
    gate_ids: set[str] = set()
    rows = _gate_rows()
    for row_id in TICKET_ROW_IDS:
        gate_ids.update(TICKET_ID_RE.findall(rows.get(row_id, "")))

    shared = decision_ids & queue_ids & gate_ids
    assert shared, (
        "the follow-up implementation ticket must be named in all three documents: "
        f"ADR 0004 Decision has {sorted(decision_ids)}, the runbook ADR queue has "
        f"{sorted(queue_ids)}, the Gate 0 rows {list(TICKET_ROW_IDS)} have {sorted(gate_ids)}"
    )


def test_runbook_adr_queue_annotates_adr_0004() -> None:
    line = _queue_item_line()
    assert line.startswith("4. "), f"the handoff grants must stay queue item 4, found {line!r}"
    assert "0004" in line, (
        "the runbook's file-scoped handoff queue item does not reference 0004; the queue "
        "item must annotate ADR 0004 rather than drop it"
    )


def test_runbook_truth_ledger_records_both_decisions() -> None:
    for row_id in ("T-023", "T-024"):
        row = _ledger_row(row_id)
        assert "0004" in row, f"the runbook {row_id} row does not point at ADR 0004"


def test_runbook_t006_row_matches_the_current_token_model() -> None:
    row = _ledger_row("T-006")
    for stale in STALE_TOKEN_ROW_STRINGS:
        assert stale not in row, (
            f"the runbook T-006 row still carries the stale token model ({stale!r}): the "
            "API now issues short-lived access tokens with rotating refresh sessions"
        )


def test_gate_0_rows_record_the_decision() -> None:
    for row_id in ("MV-SEC-007", "MV-SEC-008"):
        assert "0004" in _gate_row(row_id), (
            f"the {row_id} disposition does not point at ADR 0004"
        )

    cookie_row = _gate_row("MV-SEC-017").lower()
    assert "cookie" in cookie_row, "the MV-SEC-017 row does not describe the import cookies"
    assert "0004" in cookie_row, "the MV-SEC-017 row does not point at ADR 0004"

    for row_id, row in _gate_rows().items():
        assert STALE_THROTTLE_PHRASE not in row, (
            f"the {row_id} row still claims there is no login throttle"
        )


def test_adr_anchors_its_mitigations_to_real_code() -> None:
    text = _adr_text()
    for identifier in MITIGATION_IDENTIFIERS:
        assert identifier in text, (
            f"ADR 0004 does not name {identifier!r}; the mitigations must stay anchored to "
            "real code rather than prose"
        )


def test_adr_admits_the_access_log_surface() -> None:
    text = _adr_text().lower()
    assert "access log" in text, (
        "ADR 0004 must keep the record that server access logs once recorded token-bearing "
        "request lines; the superseded ADR is the history, and the history is not edited"
    )


def test_adr_0005_is_the_single_accepted_decision_for_grants() -> None:
    path = _adr_0005_path()
    first_line = _lines(path)[0]
    assert re.match(r"^# ADR 0005: ", first_line), (
        f"{path.name} must open with '# ADR 0005: ', found {first_line!r}"
    )
    text = _adr_0005_text()
    assert "**Status:** Accepted" in text, f"{path.name} is not marked Status: Accepted"
    for heading in REQUIRED_ADR_HEADINGS:
        assert heading in text, f"{path.name} is missing the {heading!r} section"


def test_adr_0005_names_the_grants_the_log_fix_and_the_ticket() -> None:
    text = _adr_0005_text()
    for needle in ADR_0005_REQUIRED_STRINGS:
        assert needle in text, (
            f"ADR 0005 does not name {needle!r}; the decision must stay anchored to the "
            "shipped mint, verifier, log fixes and implementation ticket"
        )
