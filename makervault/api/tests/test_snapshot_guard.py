"""The snapshot guard's pure surface and its policy table (Mf-julm).

Two entry points, two kinds of test. `describe()` is a preview and must stay
pure, so it is tested against a `provider_for` that fails the test if it is
called, an `audit.record` that does the same, and a `detect()` that counts its
own calls. `guard()` acts, so the tests below drive its exception mapping and its
audit rows with a scripted provider.

The rows are captured at `audit.record` rather than read back from the table:
this module is about what the guard *decides*, and the two tests that need a real
row (fail-loud ordering, the routes themselves) live in `test_snapshot_destructive.py`
and `test_audit_log.py`, where a database already exists.
"""

import pytest
import snapshot_fakes
from fastapi import HTTPException

import audit
import config
import db
import snapshot_guard
import snapshots
import storage_capabilities
from schemas import SnapshotNoticeOut

OPERATIONS = snapshot_guard.OPERATIONS

POLICY_ATTRIBUTES = {
    snapshots.SnapshotReason.PRE_DELETE: "SNAPSHOT_POLICY_PREDELETE",
    snapshots.SnapshotReason.PRE_PURGE: "SNAPSHOT_POLICY_PREPURGE",
    snapshots.SnapshotReason.PRE_BULK: "SNAPSHOT_POLICY_PREBULK",
}

# A request-scoped context, spelled out so a guard test never needs a client.
CTX = audit.AuditContext(
    actor=audit.Actor("admin", "admin", "password", "user-1"),
    request_id="guard-unit",
    method="POST",
    path="/trash/purge",
)


def reason_id(reason: snapshots.SnapshotReason) -> str:
    return reason.value


@pytest.fixture(autouse=True)
def storage_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """An empty temporary library root: the guard's providers resolve `db.STORAGE`."""
    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setattr(db, "STORAGE", root)
    return root


def capture_audit(monkeypatch: pytest.MonkeyPatch) -> list[audit.Event]:
    """Collect the events handed to `audit.record`; the guard writes through it."""

    events: list[audit.Event] = []

    def record(*written: audit.Event, ctx: audit.AuditContext) -> None:
        events.extend(written)

    monkeypatch.setattr(audit, "record", record)
    return events


# --- the name pattern is S2's real name format ------------------------------


@pytest.mark.parametrize("reason", OPERATIONS, ids=reason_id)
def test_name_pattern_is_the_real_snapshot_name_shape(reason: snapshots.SnapshotReason) -> None:
    """The pattern is the only promise a preview makes, so it must be S2's name."""
    pattern = snapshot_guard.name_pattern(reason)
    sample = pattern.replace("<YYYYmmddTHHMMSSZ>", "20250101T000000Z").replace("<6 hex>", "a1b2c3")

    assert snapshots.NAME_RE.fullmatch(sample), f"{pattern} does not describe a real snapshot name"
    parsed = snapshots.parse_name(sample)
    assert parsed is not None and parsed.reason is reason
    assert f"-{reason.value}-" in pattern


def test_the_operations_are_the_three_destructive_reasons() -> None:
    """A snapshot on a plain delete would be per click; only these three are gestures."""
    assert set(OPERATIONS) == {
        snapshots.SnapshotReason.PRE_DELETE,
        snapshots.SnapshotReason.PRE_PURGE,
        snapshots.SnapshotReason.PRE_BULK,
    }
    assert snapshots.SnapshotReason.MANUAL not in OPERATIONS
    assert snapshots.SnapshotReason.SCHEDULED not in OPERATIONS
    assert snapshot_guard.NAME_PATTERN == "<YYYYmmddTHHMMSSZ>-{reason}-<6 hex>"


# --- the policy is read from config, at call time ---------------------------


@pytest.mark.parametrize("reason", OPERATIONS, ids=reason_id)
def test_policy_for_reads_the_configured_policy(reason: snapshots.SnapshotReason, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both values of both policies, patched on `config` with no module reload."""
    attribute = POLICY_ATTRIBUTES[reason]
    for value in ("warn", "strict"):
        monkeypatch.setattr(config, attribute, value)
        assert snapshot_guard.policy_for(reason) == value


def test_policy_for_fails_closed_for_a_reason_that_names_no_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_STRICT", "strict")
    assert snapshot_guard.policy_for(snapshots.SnapshotReason.MANUAL) == config.SNAPSHOT_POLICY_STRICT


# --- describe() is pure -----------------------------------------------------


def test_describe_writes_nothing_and_constructs_nothing(storage_root, monkeypatch: pytest.MonkeyPatch) -> None:
    """A preview may not create a file, a snapshot, a provider or an audit row."""
    detect_calls: list[int] = []

    def detect():
        detect_calls.append(len(detect_calls))
        return [snapshot_fakes.capability()]

    monkeypatch.setattr(storage_capabilities, "detect", detect)

    def boom(*args, **kwargs):
        raise AssertionError("describe() must not construct a provider")

    def refuse(*args, **kwargs):
        raise AssertionError("describe() must not write an audit row")

    monkeypatch.setattr(snapshots, "provider_for", boom)
    monkeypatch.setattr(audit, "record", refuse)
    monkeypatch.setattr(audit, "stage", refuse)

    before = sorted(path.relative_to(storage_root).as_posix() for path in storage_root.rglob("*"))

    notice = snapshot_guard.describe(snapshots.SnapshotReason.PRE_PURGE)

    assert detect_calls == [0], "describe() must ask detect() exactly once"
    assert sorted(path.relative_to(storage_root).as_posix() for path in storage_root.rglob("*")) == before == []
    assert not (storage_root / snapshots.SNAPSHOT_DIRNAME).exists()
    assert notice == SnapshotNoticeOut(
        reason="prepurge",
        policy=config.SNAPSHOT_POLICY_PREPURGE,
        capability="available",
        action="snapshot",
        pattern=snapshot_guard.name_pattern(snapshots.SnapshotReason.PRE_PURGE),
        name=None,
        detail=None,
    )


@pytest.mark.parametrize("policy", ["warn", "strict"], ids=["warn", "strict"])
@pytest.mark.parametrize("available", [True, False], ids=["available", "unavailable"])
@pytest.mark.parametrize("require", [False, True], ids=["optional", "required"])
def test_describe_announces_the_policy_decision(
    available: bool, policy: str, require: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(available|unavailable) x (warn|strict) x SNAPSHOT_REQUIRE_CAPABILITY."""
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", policy)
    monkeypatch.setattr(config, "SNAPSHOT_REQUIRE_CAPABILITY", require)
    if available:
        snapshot_fakes.use_capability(monkeypatch)
    else:
        snapshot_fakes.use_unavailable(monkeypatch)

    notice = snapshot_guard.describe(snapshots.SnapshotReason.PRE_PURGE)

    assert notice.policy == policy
    assert notice.reason == "prepurge"
    assert notice.pattern == snapshot_guard.name_pattern(snapshots.SnapshotReason.PRE_PURGE)
    # A preview can never name a snapshot: the name carries the clock.
    assert notice.name is None
    if available:
        assert notice.capability == "available"
        assert notice.action == "snapshot"
        assert notice.detail is None
    else:
        assert notice.capability == "unavailable"
        assert notice.action == ("refuse" if policy == "strict" and require else "proceed_without")
        assert notice.detail == snapshot_fakes.UNUSABLE.reason


# --- guard(): the exception mapping, observable through the status ---------


@pytest.mark.parametrize("policy", ["warn", "strict"], ids=["warn", "strict"])
@pytest.mark.parametrize(
    "error, status",
    [
        (snapshots.SnapshotPathError("a path escaped the root"), 400),
        (snapshots.SnapshotNotFound("the snapshot is gone"), 404),
        (snapshots.SnapshotExists("the name is taken"), 409),
    ],
    ids=["path", "not-found", "exists"],
)
def test_a_defect_or_a_collision_refuses_whatever_the_policy_says(
    error: snapshots.SnapshotError, status: int, policy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path, not-found and collision are bugs, not capability misses: always refuse."""
    rows = capture_audit(monkeypatch)
    provider = snapshot_fakes.use_provider(monkeypatch, db.STORAGE, fail=error)
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREPURGE", policy)

    with pytest.raises(HTTPException) as excinfo:
        snapshot_guard.guard(snapshots.SnapshotReason.PRE_PURGE, "trash", ctx=CTX)

    assert excinfo.value.status_code == status
    assert excinfo.value.detail == str(error)
    assert provider.calls == [(snapshots.SnapshotReason.PRE_PURGE, None)]
    assert len(rows) == 1
    row = rows[0]
    assert row.action == audit.DESTRUCTIVE_SNAPSHOT_MISSED
    assert row.target == "trash"
    assert row.detail == {"reason": "prepurge", "policy": policy, "cause": "failed", "error": str(error)}


def test_guard_writes_one_taken_row_naming_the_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = capture_audit(monkeypatch)
    provider = snapshot_fakes.use_provider(monkeypatch, db.STORAGE)
    monkeypatch.setattr(config, "SNAPSHOT_POLICY_PREBULK", "strict")

    notice = snapshot_guard.guard(snapshots.SnapshotReason.PRE_BULK, "assets", ctx=CTX)

    assert notice.action == "snapshot"
    assert notice.capability == "available"
    assert notice.policy == "strict"
    assert notice.name is not None and snapshots.NAME_RE.fullmatch(notice.name)
    assert provider.calls == [(snapshots.SnapshotReason.PRE_BULK, None)], "the guard never passes a context"
    assert len(rows) == 1
    assert rows[0].action == audit.DESTRUCTIVE_SNAPSHOT_TAKEN
    assert rows[0].target == "assets"
    assert rows[0].detail == {"reason": "prebulk", "policy": "strict", "name": notice.name, "method": provider.method}


def test_guard_without_a_context_writes_no_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ctx=None` is the one no-op, mirroring `snapshots._emit`."""
    rows = capture_audit(monkeypatch)
    provider = snapshot_fakes.use_provider(monkeypatch, db.STORAGE)

    notice = snapshot_guard.guard(snapshots.SnapshotReason.PRE_PURGE, "trash", ctx=None)

    assert rows == []
    assert notice.action == "snapshot"
    assert notice.name is not None and snapshots.NAME_RE.fullmatch(notice.name)
    assert provider.calls == [(snapshots.SnapshotReason.PRE_PURGE, None)]


def test_guard_without_a_context_writes_no_row_on_a_miss_either(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = capture_audit(monkeypatch)
    snapshot_fakes.use_unavailable(monkeypatch)

    notice = snapshot_guard.guard(snapshots.SnapshotReason.PRE_PURGE, "trash", ctx=None)

    assert rows == []
    assert notice.action == "proceed_without"
    assert notice.capability == "unavailable"


# --- config.env_policy ------------------------------------------------------


def test_env_policy_rejects_an_unknown_value_and_names_the_key() -> None:
    with pytest.raises(ValueError) as excinfo:
        config.env_policy("SNAPSHOT_POLICY_PREPURGE", "lenient", "warn")

    message = str(excinfo.value)
    assert "SNAPSHOT_POLICY_PREPURGE" in message
    assert "lenient" in message


@pytest.mark.parametrize("raw", ["warn", "WARN", " Warn ", "strict", "STRICT", " Strict"])
def test_env_policy_accepts_both_policies_case_insensitively(raw: str) -> None:
    value = config.env_policy("SNAPSHOT_POLICY_PREPURGE", raw, "strict")
    assert value == raw.strip().lower()
    assert value in config.SNAPSHOT_POLICIES


@pytest.mark.parametrize("raw", ["lenient", "   "])
def test_env_policy_rejects_a_value_it_cannot_use(raw: str) -> None:
    """A typo, and a blank string, must fail the boot rather than fall back."""
    with pytest.raises(ValueError) as excinfo:
        config.env_policy("SNAPSHOT_POLICY_PREPURGE", raw, "warn")

    message = str(excinfo.value)
    assert "SNAPSHOT_POLICY_PREPURGE" in message


@pytest.mark.parametrize("raw", [None, ""])
def test_env_policy_falls_back_to_the_default(raw) -> None:
    """An unset variable is the default; `env_policy` is what makes that explicit."""
    assert config.env_policy("SNAPSHOT_POLICY_PREPURGE", raw, "strict") == "strict"
    assert config.env_policy("SNAPSHOT_POLICY_PREPURGE", raw, "warn") == "warn"


def test_the_configured_policies_are_in_their_valid_sets() -> None:
    """The three policies and the operator switch, as the module sees them at import."""
    assert config.SNAPSHOT_POLICIES == {"warn", "strict"}
    for attribute in POLICY_ATTRIBUTES.values():
        assert hasattr(config, attribute), attribute
        assert getattr(config, attribute) in config.SNAPSHOT_POLICIES, attribute
    assert isinstance(config.SNAPSHOT_REQUIRE_CAPABILITY, bool)
