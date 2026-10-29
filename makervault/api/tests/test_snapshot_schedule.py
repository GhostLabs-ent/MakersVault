"""S8's scheduler: the clock-driven decision, its own audit rows, the never-dying thread.

The provider layer is S2's and is tested in `test_snapshots.py`; the HTTP surface
is S4's and is driven in `test_snapshot_browse_restore.py`. What is left, and what
is tested here, is what only the scheduler does: decide from a snapshot's own
`created_at` whether a tick is due, write the two audit rows the provider never
gets to write (a refusal and a failure), keep the thread alive across a bad tick,
and report all of that through a status surface that must never raise.

Every test works in a temporary storage root (`db.STORAGE` and the other storage
bindings are patched by `isolated_storage`), the clock is injected into
`run_once` and monkeypatched through `snapshots._now`, and the in-process state
is reset around every test by `clean_scheduler_state`: a tick history from one
test must never make another test's tick look idle. No test sleeps, and no test
waits on a real thread; `run_forever` is driven with a `threading.Event` that is
already set, so "it returns at once" is an assertion rather than a hope.

The four retention settings are operator configuration, so `restored_retention`
puts them back after each test, exactly as `test_snapshot_browse_restore.py` does.
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest
import snapshot_fakes
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_file_service
import asset_service
import audit
import config
import db
import library_scan
import main
import snapshot_schedule
import snapshot_service
import snapshots
import storage_capabilities
from db import engine
from main import app
from migrations import run_migrations
from models import AppConfig, Asset, AssetFile, AuditEvent, Folder

# A fixed aware-UTC instant: the injected "now" every tick decision is measured
# against, and the instant the wall clock is patched to when a test has to prove
# the injected value is the one that decides.
FROZEN = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)

RETENTION_KEYS = (
    snapshots.RETENTION_KEEP_LAST_N_KEY,
    snapshots.RETENTION_KEEP_DAILY_KEY,
    snapshots.RETENTION_MAX_AGE_DAYS_KEY,
    snapshots.RETENTION_HARD_CAP_KEY,
)


# --- infrastructure ---------------------------------------------------------


class RecordingProvider(snapshot_fakes.ScriptedProvider):
    """`ScriptedProvider` plus a log of `delete()` calls, so "zero deletes" is observable.

    S2's own `create()` still prunes: retention removes old snapshots through
    `_remove`, which never calls `delete()`. That is why the assertion below is
    about `delete()` and not about the store shrinking -- the store *should*
    shrink when retention says so, and the scheduler must still issue no delete
    of its own.
    """

    def __init__(self, root: Path, **kwargs) -> None:
        super().__init__(root, **kwargs)
        self.deletes: list[str] = []

    def delete(self, name: str, *, ctx: Optional[audit.AuditContext] = None) -> None:
        self.deletes.append(name)
        super().delete(name, ctx=ctx)


@pytest.fixture(autouse=True)
def clean_scheduler_state():
    """The in-process tick history is per-test state; reset it on both sides."""
    snapshot_schedule.reset_state()
    yield
    snapshot_schedule.reset_state()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage and thumbnails at temp roots, then undo the rows a test made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")

    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        files_before = {row.id for row in session.exec(select(AssetFile))}
    yield storage
    with Session(engine) as session:
        for row in list(session.exec(select(AssetFile))):
            if row.id not in files_before:
                session.delete(row)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


@pytest.fixture(autouse=True)
def restored_retention(isolated_storage: Path) -> None:
    """Put the four retention settings back after each test, exactly as they were.

    They are operator configuration and a corrupt row is one of the cases below;
    a row written here must not change any later test's pruning.
    """
    with Session(engine) as session:
        previous = {
            key: (row.value if (row := session.get(AppConfig, key)) is not None else None)
            for key in RETENTION_KEYS
        }
    yield
    with Session(engine) as session:
        for key, value in previous.items():
            row = session.get(AppConfig, key)
            if value is None:
                if row is not None:
                    session.delete(row)
            elif row is None:
                session.add(AppConfig(key=key, value=value))
            else:
                row.value = value
        session.commit()


@pytest.fixture()
def library(isolated_storage: Path) -> Path:
    """The temporary library root, which is also `db.STORAGE` for these tests."""
    return isolated_storage


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def admin_headers(client: TestClient) -> dict[str, str]:
    """Bearer token, or nothing when this deployment runs with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# --- helpers ----------------------------------------------------------------


def recording_provider(root: Path, **kwargs) -> RecordingProvider:
    """A `RecordingProvider` on `root`, with the snapshot store materialised."""
    (root / snapshots.SNAPSHOT_DIRNAME).mkdir(parents=True, exist_ok=True)
    return RecordingProvider(root, **kwargs)


def install_provider(monkeypatch: pytest.MonkeyPatch, provider: snapshots.SnapshotProvider) -> snapshots.SnapshotProvider:
    """Answer `provider_for()` with one fixed provider and a usable capability."""
    return install_provider_factory(monkeypatch, lambda *args, **kwargs: provider)


def install_provider_factory(monkeypatch: pytest.MonkeyPatch, factory) -> None:
    """Answer `provider_for()` from `factory`; the tick builds one provider per call.

    `snapshot_service.provider()` resolves `snapshots.provider_for` at call time,
    so this is the one patch point, exactly as `snapshot_fakes` documents.
    """
    snapshot_fakes.use_capability(monkeypatch)
    monkeypatch.setattr(snapshots, "provider_for", factory)


def seed_snapshot(
    provider: snapshots.SnapshotProvider,
    when: datetime,
    *,
    reason: snapshots.SnapshotReason = snapshots.SnapshotReason.SCHEDULED,
    suffix: str = "000001",
) -> str:
    """Put a snapshot directory in the store exactly as a provider would have named it."""
    name = snapshots.snapshot_name(reason, when, suffix=suffix)
    (provider.snapshot_dir / name).mkdir()
    return name


def schedule_rows() -> list[AuditEvent]:
    """Every row this module writes itself: they all share one target."""
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.target == snapshot_schedule.TARGET)))


def rows_for(action: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.action == action)))


def row_ids(action: str) -> set[str]:
    return {row.id for row in rows_for(action)}


def schedule_row_ids() -> set[str]:
    return {row.id for row in schedule_rows()}


def new_schedule_rows(before: set[str]) -> list[AuditEvent]:
    return [row for row in schedule_rows() if row.id not in before]


def store_setting(key: str, value: str) -> None:
    with Session(engine) as session:
        row = session.get(AppConfig, key)
        if row is None:
            session.add(AppConfig(key=key, value=value))
        else:
            row.value = value
        session.commit()


# --- AC-1: the due rule, decided from the injected clock --------------------


def test_ac1_a_volume_with_no_scheduled_snapshot_is_due_immediately(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_CREATED
    assert outcome.now == FROZEN
    assert len(provider.calls) == 1
    assert provider.calls[0][0] is snapshots.SnapshotReason.SCHEDULED


def test_ac1_a_scheduled_snapshot_inside_the_window_makes_the_tick_idle(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    seed_snapshot(provider, FROZEN - timedelta(hours=23))
    before = schedule_row_ids()

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_IDLE
    assert provider.calls == []
    # An idle tick writes nothing at all: a row per idle check would fill the log
    # with the absence of an action.
    assert new_schedule_rows(before) == []


def test_ac1_a_scheduled_snapshot_past_the_window_is_due(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    seed_snapshot(provider, FROZEN - timedelta(hours=25))

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_CREATED
    assert [reason for reason, _ in provider.calls] == [snapshots.SnapshotReason.SCHEDULED]


def test_ac1_a_manual_snapshot_does_not_satisfy_the_schedule(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    seed_snapshot(provider, FROZEN - timedelta(hours=30), reason=snapshots.SnapshotReason.MANUAL)

    outcome = snapshot_schedule.run_once(FROZEN)

    # Only a `scheduled` snapshot is a schedule marker: a manual one says a user
    # took a snapshot, not that the clock did.
    assert outcome.outcome == snapshot_schedule.OUTCOME_CREATED


def test_ac1_the_decision_follows_the_injected_now_not_the_wall_clock(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    seed_snapshot(provider, FROZEN - timedelta(hours=23), suffix="000001")
    # The wall clock says a year has passed, which would make the tick due if the
    # scheduler read it. It must not: the injected `now` is the whole decision.
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN + timedelta(days=365))
    assert snapshot_schedule.run_once(FROZEN).outcome == snapshot_schedule.OUTCOME_IDLE

    second_root = library / "second"
    second_root.mkdir()
    other = recording_provider(second_root)
    install_provider(monkeypatch, other)
    seed_snapshot(other, FROZEN - timedelta(hours=25), suffix="000002")
    # And the other direction: a wall clock in the past must not make it idle.
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN - timedelta(days=365))
    assert snapshot_schedule.run_once(FROZEN).outcome == snapshot_schedule.OUTCOME_CREATED


# --- AC-2: one create, zero deletes, retention inside create ----------------


def test_ac2_a_due_tick_takes_one_snapshot_and_issues_no_delete(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_CREATED
    assert [reason for reason, _ in provider.calls] == [snapshots.SnapshotReason.SCHEDULED]
    # S2's create prunes through `_remove`, so a shrinking store is not a delete.
    assert provider.deletes == []


def test_ac2_retention_runs_inside_create_not_as_a_scheduler_delete(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = snapshots.RetentionPolicy(keep_last_n=2, keep_daily=0, max_age_days=1, hard_cap=5)
    (library / snapshots.SNAPSHOT_DIRNAME).mkdir(parents=True, exist_ok=True)
    provider = snapshots.LocalCopyProvider(library, policy=policy)
    snapshot_fakes.use_capability(monkeypatch, method=snapshots.LOCAL_COPY_METHOD)
    monkeypatch.setattr(snapshots, "provider_for", lambda *args, **kwargs: provider)
    # A one-hour window makes two-hour-old seeds due; the one-day age rule then
    # leaves them alone, so `keep_last_n` is the rule that has to prune.
    monkeypatch.setattr(config, "SNAPSHOT_SCHEDULE_HOURS", 1)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)
    oldest = seed_snapshot(provider, FROZEN - timedelta(hours=3), suffix="000001")
    newer = seed_snapshot(provider, FROZEN - timedelta(hours=2), suffix="000002")
    prune_before = row_ids(audit.SNAPSHOT_PRUNE)

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_CREATED
    names = [snapshot.name for snapshot in provider.list()]
    assert len(names) == 2
    assert oldest not in names
    assert newer in names
    # S2 wrote the prune row, not S8: the scheduler only handed over a context.
    new_prunes = [row for row in rows_for(audit.SNAPSHOT_PRUNE) if row.id not in prune_before]
    assert [row.target for row in new_prunes] == [oldest]


def test_ac2_the_provider_is_rebuilt_on_every_tick_and_never_cached(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[RecordingProvider] = []

    def factory(*args, **kwargs) -> RecordingProvider:
        provider = recording_provider(library)
        built.append(provider)
        return provider

    install_provider_factory(monkeypatch, factory)

    snapshot_schedule.run_once(FROZEN)
    snapshot_schedule.run_once(FROZEN)

    # One construction per tick: a provider reads the retention policy when it is
    # built, so a cached one would ignore an admin's edit until the next restart.
    assert len(built) == 2
    assert built[0] is not built[1]


def test_ac2_the_tick_hands_the_provider_a_system_context(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)

    snapshot_schedule.run_once(FROZEN)

    ctx = provider.calls[0][1]
    # ``ctx=None`` is a silent no-op in S2: a tick that forgot the context would
    # look green here and in production, and write no audit row at all.
    assert ctx is not None
    assert ctx.actor.username == "system"
    assert ctx.actor.role == "system"
    assert ctx.actor.kind == "system"
    assert ctx.request_id == ""
    assert ctx.method == ""
    assert ctx.path == "/snapshots/schedule"


def test_ac2_a_successful_tick_writes_the_provider_rows_and_no_schedule_row(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    creates_before = row_ids(audit.SNAPSHOT_CREATE)
    schedule_before = schedule_row_ids()

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_CREATED
    new_creates = [row for row in rows_for(audit.SNAPSHOT_CREATE) if row.id not in creates_before]
    assert [row.target for row in new_creates] == [outcome.snapshot]
    # The provider's create row already records the tick; a second "the
    # scheduler ran" row would double every scheduled snapshot in the log.
    assert new_schedule_rows(schedule_before) == []


# --- AC-3: the status surface reports and never raises ----------------------


def test_ac3_the_status_surface_reports_the_volume_the_policy_and_the_config(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)
    seed_snapshot(provider, FROZEN - timedelta(hours=25), reason=snapshots.SnapshotReason.MANUAL, suffix="000001")
    seed_snapshot(provider, FROZEN - timedelta(hours=1), suffix="000002")

    response = client.get("/snapshots/schedule", headers=admin_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] == config.SNAPSHOT_SCHEDULE_ENABLED
    assert body["hours"] == config.SNAPSHOT_SCHEDULE_HOURS
    assert body["check_seconds"] == config.SNAPSHOT_SCHEDULE_CHECK_SECONDS
    assert body["count"] == 2
    assert body["last_24h"] == 1
    assert body["oldest"] == (FROZEN - timedelta(hours=25)).isoformat()
    assert body["newest"] == (FROZEN - timedelta(hours=1)).isoformat()
    assert body["retention"] == {"keep_last_n": 20, "keep_daily": 7, "max_age_days": 30, "hard_cap": 100}
    assert body["database_caveat"]
    assert "SQLite" in body["database_caveat"]


def test_ac3_a_tick_is_reflected_in_the_status_report(client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    outcome = snapshot_schedule.run_once(FROZEN)
    body = client.get("/snapshots/schedule", headers=admin_headers(client)).json()

    assert body["last_attempt"] == FROZEN.isoformat()
    assert body["last_outcome"] == "created"
    assert body["last_snapshot"] == outcome.snapshot
    assert body["last_error"] is None


def test_ac3_a_volume_with_no_snapshot_method_is_reported_and_never_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The house idiom for "this volume cannot snapshot": a NullProvider, which is
    # what the permission matrix's sweep installs too. The route reports, it does
    # not operate, so this must be a 200 with a warning, never a 409.
    snapshot_fakes.use_unavailable(monkeypatch)

    response = client.get("/snapshots/schedule", headers=admin_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert snapshot_schedule.WARNING_NO_METHOD in body["warnings"]
    assert body["count"] == 0
    assert body["oldest"] is None
    assert body["newest"] is None


def test_ac3_a_corrupt_retention_row_is_a_warning_and_not_an_error(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_provider(monkeypatch, recording_provider(library))
    store_setting(snapshots.RETENTION_KEEP_LAST_N_KEY, "abc")

    response = client.get("/snapshots/schedule", headers=admin_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert body["retention"] is None
    unreadable_prefix = snapshot_schedule.WARNING_RETENTION_UNREADABLE.format(error="")
    assert any(warning.startswith(unreadable_prefix) for warning in body["warnings"])
    assert any("snapshot_keep_last_n" in warning for warning in body["warnings"])


def test_ac3_a_failed_provider_still_reports_the_method_the_volume_has(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A volume that HAS a snapshot method and a provider that could not be built
    # (here a corrupt retention row, which construction reads) must not also
    # claim the volume has no method: that would be a second, false warning.
    snapshot_fakes.use_capability(monkeypatch, method=storage_capabilities.ZFS_DATASET)

    def unbuildable(*args, **kwargs):
        raise ValueError("the setting snapshot_keep_last_n is not an integer")

    monkeypatch.setattr(snapshots, "provider_for", unbuildable)

    body = client.get("/snapshots/schedule", headers=admin_headers(client)).json()

    assert snapshot_schedule.WARNING_NO_METHOD not in body["warnings"]
    unreadable_prefix = snapshot_schedule.WARNING_PROVIDER_UNREADABLE.format(error="")
    assert any(warning.startswith(unreadable_prefix) for warning in body["warnings"])


def test_ac3_retention_pressure_is_reported_before_the_next_create(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = recording_provider(library)
    install_provider(monkeypatch, provider)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)
    # 25 snapshots taken in the last half hour, all on one UTC date: the default
    # `keep_last_n=20` will drop 5 on the next create, and the daily rule adds
    # nothing because the newest survivor's date is already kept.
    for index in range(25):
        seed_snapshot(provider, FROZEN - timedelta(minutes=index), suffix=f"{index:06d}")

    body = client.get("/snapshots/schedule", headers=admin_headers(client)).json()

    assert body["count"] == 25
    assert snapshot_schedule.WARNING_RETENTION_PRESSURE.format(count=5) in body["warnings"]


def test_ac3_the_warnings_are_emitted_in_a_deterministic_order(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "SNAPSHOT_SCHEDULE_ENABLED", False)
    snapshot_fakes.use_unavailable(monkeypatch)
    store_setting(snapshots.RETENTION_KEEP_LAST_N_KEY, "abc")

    body = client.get("/snapshots/schedule", headers=admin_headers(client)).json()

    unreadable = "the setting snapshot_keep_last_n is not an integer"
    assert body["warnings"] == [
        snapshot_schedule.WARNING_DISABLED,
        snapshot_schedule.WARNING_NO_METHOD,
        # A NullProvider reads the policy when it is constructed, so the corrupt
        # row is reported by the provider step as well as the retention step.
        snapshot_schedule.WARNING_PROVIDER_UNREADABLE.format(error=unreadable),
        snapshot_schedule.WARNING_RETENTION_UNREADABLE.format(error=unreadable),
    ]


# --- AC-4: refusal and failure are audited, deduped and surfaced ------------


def test_ac4_a_refusal_is_audited_and_surfaced(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_fakes.use_unavailable(monkeypatch)
    before = schedule_row_ids()

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_SKIPPED
    rows = new_schedule_rows(before)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == audit.SNAPSHOT_SCHEDULE_SKIPPED
    assert row.actor == "system"
    assert row.actor_kind == "system"
    assert row.actor_role == "system"
    assert row.request_id == ""
    assert row.target == "snapshot_schedule"
    assert json.loads(row.detail_json) == {
        "cause": outcome.cause,
        "method": storage_capabilities.NO_METHOD,
        "hours": config.SNAPSHOT_SCHEDULE_HOURS,
    }
    assert snapshot_schedule.WARNING_LAST_SKIPPED.format(cause=outcome.cause) in snapshot_schedule.status_out().warnings


def test_ac4_repeated_refusals_are_deduped_by_cause(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first_cause = "no .snap here"
    changed_cause = "a different volume problem"
    queue = [
        recording_provider(library, fail=snapshots.SnapshotUnavailable(first_cause)),
        recording_provider(library, fail=snapshots.SnapshotUnavailable(first_cause)),
        recording_provider(library, fail=snapshots.SnapshotUnavailable(changed_cause)),
    ]
    install_provider_factory(monkeypatch, lambda *args, **kwargs: queue.pop(0))
    before = schedule_row_ids()

    outcomes = [snapshot_schedule.run_once(FROZEN) for _ in range(3)]

    assert [outcome.outcome for outcome in outcomes] == [snapshot_schedule.OUTCOME_SKIPPED] * 3
    rows = new_schedule_rows(before)
    # A refused volume fails the same way on every check: one row, then a new row
    # only when the cause actually changed.
    assert [json.loads(row.detail_json)["cause"] for row in rows] == [first_cause, changed_cause]


def test_ac4_a_successful_tick_clears_the_dedupe(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cause = "no .snap here"

    def refusing() -> RecordingProvider:
        return recording_provider(library, fail=snapshots.SnapshotUnavailable(cause))

    queue = [refusing(), refusing(), recording_provider(library), refusing()]
    install_provider_factory(monkeypatch, lambda *args, **kwargs: queue.pop(0))
    # The successful tick names its snapshot at the patched clock, so the fourth
    # tick's "25 hours later" is measured against a known snapshot.
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)
    before = schedule_row_ids()

    first = snapshot_schedule.run_once(FROZEN)
    second = snapshot_schedule.run_once(FROZEN)
    after_two = new_schedule_rows(before)
    third = snapshot_schedule.run_once(FROZEN)
    after_success = new_schedule_rows(before)
    fourth = snapshot_schedule.run_once(FROZEN + timedelta(hours=25))
    after_four = new_schedule_rows(before)

    assert [first.outcome, second.outcome] == [snapshot_schedule.OUTCOME_SKIPPED] * 2
    assert len(after_two) == 1
    assert third.outcome == snapshot_schedule.OUTCOME_CREATED
    # A good tick is a new fact: it clears the key, so the recurring refusal is
    # recorded again instead of being deduped against a row from before it.
    assert len(after_success) == 1
    assert fourth.outcome == snapshot_schedule.OUTCOME_SKIPPED
    assert len(after_four) == 2
    assert [json.loads(row.detail_json)["cause"] for row in after_four] == [cause, cause]


def test_ac4_a_failure_is_audited_and_surfaced(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_fakes.use_provider(monkeypatch, library, fail=snapshots.SnapshotError("boom"))
    before = schedule_row_ids()

    outcome = snapshot_schedule.run_once(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_FAILED
    rows = new_schedule_rows(before)
    assert len(rows) == 1
    assert rows[0].action == audit.SNAPSHOT_SCHEDULE_FAILED
    assert snapshot_schedule.WARNING_LAST_FAILED.format(cause="boom") in snapshot_schedule.status_out().warnings


def test_ac4_a_corrupt_retention_row_fails_the_tick_without_raising(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot_fakes.use_unavailable(monkeypatch)
    store_setting(snapshots.RETENTION_KEEP_LAST_N_KEY, "abc")
    before = schedule_row_ids()

    outcome = snapshot_schedule.run_once(FROZEN)

    # The provider reads the policy when it is constructed, so the corrupt row
    # surfaces as a failed tick -- reported, never raised out of the thread.
    assert outcome.outcome == snapshot_schedule.OUTCOME_FAILED
    assert outcome.cause is not None
    assert snapshots.RETENTION_KEEP_LAST_N_KEY in outcome.cause
    rows = new_schedule_rows(before)
    assert [row.action for row in rows] == [audit.SNAPSHOT_SCHEDULE_FAILED]


def test_ac4_an_unexpected_error_fails_the_tick_without_killing_it(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> snapshots.SnapshotProvider:
        raise RuntimeError("boom")

    monkeypatch.setattr(snapshot_service, "provider", explode)

    outcome = snapshot_schedule.tick(FROZEN)

    assert outcome.outcome == snapshot_schedule.OUTCOME_FAILED
    assert outcome.cause == "boom"
    # Restore a working provider before asking the status surface, which builds
    # one of its own: the blanket catch is what keeps the thread alive, and the
    # report is what keeps the failure visible.
    monkeypatch.setattr(snapshot_service, "provider", lambda: recording_provider(library))
    assert snapshot_schedule.status_out().last_outcome == snapshot_schedule.OUTCOME_FAILED


# --- the thread and the clock (no sleeping, no real waiting) ----------------


def test_the_thread_returns_at_once_when_the_stop_event_is_already_set(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[datetime] = []
    monkeypatch.setattr(snapshot_schedule, "tick", calls.append)
    stop = threading.Event()
    stop.set()

    snapshot_schedule.run_forever(stop, check_seconds=0)

    # The start delay's `stop.wait` returns as soon as the flag is set, so this
    # would hang on a `time.sleep` implementation instead of failing here.
    assert calls == []


def test_the_thread_ticks_once_with_the_clock_seam_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[datetime] = []
    stop = threading.Event()

    def fake_tick(now: datetime) -> None:
        seen.append(now)
        stop.set()

    monkeypatch.setattr(snapshot_schedule, "tick", fake_tick)
    monkeypatch.setattr(config, "SNAPSHOT_SCHEDULE_START_DELAY_SECONDS", 0)
    monkeypatch.setattr(config, "SNAPSHOT_SCHEDULE_CHECK_SECONDS", 0)
    monkeypatch.setattr(snapshots, "_now", lambda: FROZEN)

    snapshot_schedule.run_forever(stop)

    assert seen == [FROZEN]


def test_the_scheduler_never_sleeps_and_never_reads_the_wall_clock() -> None:
    source = Path(snapshot_schedule.__file__).read_text(encoding="utf-8")

    # A wall-clock read or a sleep here would make the scheduler untestable
    # without waiting, and would make a shutdown up to one interval late. The
    # docstring names `time.sleep` in prose to explain the ban; the call form
    # below is what a regression would add.
    assert "time.sleep(" not in source
    assert "import time" not in source
    assert "datetime.now(" not in source
    assert "stop.wait(" in source


def test_should_run_reads_the_config_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SNAPSHOT_SCHEDULE_ENABLED", True)
    assert snapshot_schedule.should_run() is True

    monkeypatch.setattr(config, "SNAPSHOT_SCHEDULE_ENABLED", False)
    assert snapshot_schedule.should_run() is False


def test_the_lifespan_starts_the_scheduler_last_and_as_a_daemon() -> None:
    # A source pin is the honest test here: driving the real lifespan would run
    # migrations and both boot guards. The order is the contract -- the thread
    # must start after the guards and after migrations, never before them.
    source = Path(main.__file__).read_text(encoding="utf-8")

    routes_guard = source.index("permissions.assert_routes_classified")
    audit_guard = source.index("audit.assert_audit_coverage")
    migrations = source.index("run_migrations(engine)")
    mount_import = source.index("if mount_import_should_run():")
    scheduler = source.index("snapshot_schedule.should_run()")
    assert routes_guard < audit_guard < migrations < mount_import < scheduler

    line = next(line for line in source.splitlines() if "target=snapshot_schedule.run_forever" in line)
    assert "daemon=True" in line


# --- AC-5: the docs (host-only: absent inside the API image) ----------------


def _repo_path(*parts: str) -> Path:
    """Locate a repo-root file from either the host or the API image layout."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent.joinpath(*parts)
        if candidate.exists():
            return candidate
    pytest.skip(f"{'/'.join(parts)} is outside the API image build context", allow_module_level=False)


def test_ac5_the_runbook_documents_the_scheduler() -> None:
    path = _repo_path("makervault", "docs", "ARCHITECTURE_RUNBOOK.md")

    text = path.read_text(encoding="utf-8")
    normalised = " ".join(text.split())
    assert "#### 9.3.1 Scheduled library snapshots" in text
    assert "GET /snapshots/schedule" in text
    assert "snapshot.schedule.skipped" in text
    assert "snapshot.schedule.failed" in text
    assert "Mf-ljld" in text
    # The caveat is pinned whitespace-normalised: the prose is hard-wrapped.
    assert "does not cover the SQLite database" in normalised
    # The section must sit in the background-work chapter, not above it.
    assert text.index("### 9.3 Background or expensive work") < text.index("#### 9.3.1 Scheduled library snapshots")
    assert text.index("#### 9.3.1 Scheduled library snapshots") < text.index("### 9.4 API and client contract change")
    # Anchors that must survive the edit, so the section is an addition and not a
    # rewrite of the surrounding chapters.
    assert "initial required ADR queue" in normalised
    assert "### 5.3 Truth ledger" in text
    assert "browser-to-bridge handoff grants" in normalised


def test_ac5_the_configuration_reference_documents_the_scheduler_keys() -> None:
    path = _repo_path("makervault", "docs", "architecture", "CONFIGURATION.md")

    text = path.read_text(encoding="utf-8")
    for needle in (
        "## Scheduled snapshots",
        "SNAPSHOT_SCHEDULE_ENABLED",
        "SNAPSHOT_SCHEDULE_HOURS",
        "SNAPSHOT_SCHEDULE_CHECK_SECONDS",
        "SNAPSHOT_SCHEDULE_START_DELAY_SECONDS",
        # The snapshot chapter is an addition: the S1 documentation still stands.
        "No snapshot is taken in this slice.",
        "## Storage snapshot capabilities",
        "GET /storage/capabilities",
        "0x00C36400",
        ".snap",
        "zfs",
        "btrfs",
        "`snapshot_keep_daily` is non-negative",
        "the other three keys are positive",
    ):
        assert needle in text


def test_ac5_the_audit_and_permissions_docs_list_the_new_actions() -> None:
    audit_path = _repo_path("docs", "AUDIT.md")
    permissions_path = _repo_path("docs", "PERMISSIONS.md")

    audit_text = audit_path.read_text(encoding="utf-8")
    assert "snapshot.schedule.skipped" in audit_text
    assert "snapshot.schedule.failed" in audit_text

    permissions_text = permissions_path.read_text(encoding="utf-8")
    assert "/snapshots/schedule" in permissions_text
