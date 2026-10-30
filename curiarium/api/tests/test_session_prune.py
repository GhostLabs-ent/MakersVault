"""The session sweep: what it deletes, the one row it writes, and its thread.

Rows are inserted directly with crafted timestamps, so a tick is driven with an
injected `now` and no test sleeps. The audit table is append-only, so count-only
assertions are made against the rows this test added rather than by cleaning up.
"""

import threading
import time
from pathlib import Path

import pytest
from sqlmodel import Session, delete, select

import audit
import main
import session_prune
from db import engine
from migrations import run_migrations
from models import AuditEvent, UserSession


def truncate_sessions() -> None:
    with Session(engine) as db_session:
        db_session.execute(delete(UserSession))
        db_session.commit()


@pytest.fixture(autouse=True)
def clean_sessions():
    run_migrations(engine)
    truncate_sessions()
    yield
    truncate_sessions()


def make_session(
    *,
    now: int,
    refresh_expires_at: int,
    revoked_at: int | None = None,
    kind: str = "password",
) -> str:
    """Insert one row with exactly the timestamps the test cares about."""
    with Session(engine) as db_session:
        row = UserSession(
            user_id=None,
            username="prune-test",
            kind=kind,
            refresh_token_hash=f"hash-{now}-{refresh_expires_at}-{revoked_at}-{kind}",
            created_at=now - 1000,
            last_used_at=now - 100,
            access_expires_at=now + 100,
            refresh_expires_at=refresh_expires_at,
            revoked_at=revoked_at,
        )
        db_session.add(row)
        db_session.commit()
        return row.id


def remaining_sessions() -> set[str]:
    with Session(engine) as db_session:
        return {row.id for row in db_session.exec(select(UserSession))}


def prune_rows() -> list[AuditEvent]:
    with Session(engine) as db_session:
        return list(
            db_session.exec(
                select(AuditEvent)
                .where(AuditEvent.action == audit.SESSION_PRUNE)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            )
        )


def test_expired_and_long_revoked_rows_are_deleted_and_the_rest_survive() -> None:
    now = int(time.time())
    live = make_session(now=now, refresh_expires_at=now + 1000)
    make_session(now=now, refresh_expires_at=now - 1)
    make_session(
        now=now,
        refresh_expires_at=now + 1000,
        revoked_at=now - session_prune.REVOKED_RETENTION_SECONDS - 1,
    )
    recently_revoked = make_session(now=now, refresh_expires_at=now + 1000, revoked_at=now - 10)

    count = session_prune.run_once(now=now)

    assert count == 2
    assert remaining_sessions() == {live, recently_revoked}


def test_one_count_only_system_row_is_written_when_something_was_deleted() -> None:
    now = int(time.time())
    make_session(now=now, refresh_expires_at=now - 1, kind="password")
    before = len(prune_rows())

    assert session_prune.run_once(now=now) == 1

    rows = prune_rows()
    assert len(rows) == before + 1
    row = rows[0]
    assert row.action == audit.SESSION_PRUNE
    assert row.actor == "system"
    assert row.actor_kind == "system"
    assert row.actor_role == "system"
    assert row.target == session_prune.TARGET
    assert row.request_id == ""
    assert row.detail_json == '{"count": 1}'


def test_a_tick_that_deletes_nothing_writes_nothing() -> None:
    now = int(time.time())
    make_session(now=now, refresh_expires_at=now + 1000)
    before = len(prune_rows())

    assert session_prune.run_once(now=now) == 0

    assert len(prune_rows()) == before


def test_the_thread_returns_at_once_when_the_stop_event_is_already_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(session_prune, "run_once", lambda *args, **kwargs: calls.append(args))
    stop = threading.Event()
    stop.set()

    session_prune.run_forever(stop, interval_seconds=0, start_delay_seconds=0)

    # The start delay's `stop.wait` returns as soon as the flag is set; a
    # `time.sleep` implementation would hang here instead of failing.
    assert calls == []


def test_the_thread_ticks_then_stops_on_the_event(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()
    calls: list[int] = []

    def fake_run_once() -> int:
        calls.append(1)
        stop.set()
        return 0

    monkeypatch.setattr(session_prune, "run_once", fake_run_once)

    session_prune.run_forever(stop, interval_seconds=0, start_delay_seconds=0)

    assert calls == [1]


def test_the_sweep_never_sleeps_and_uses_the_stop_event_to_wait() -> None:
    source = Path(session_prune.__file__).read_text(encoding="utf-8")

    # `stop.wait` is the only wait primitive. `import time` is allowed here
    # because `run_once` needs the wall clock for its default `now`; the wait
    # path never reads it. The call form below is what a regression would add.
    assert "time.sleep(" not in source
    assert "stop.wait(" in source


def test_the_lifespan_starts_the_sweep_unconditionally_before_the_snapshot_scheduler() -> None:
    # A source pin is the honest test here: driving the real lifespan would run
    # migrations and both boot guards. There is deliberately no should_run()
    # gate, and the snapshot scheduler stays literally last.
    source = Path(main.__file__).read_text(encoding="utf-8")

    sweep = source.index("session_prune.run_forever")
    scheduler = source.index("snapshot_schedule.should_run()")
    assert sweep < scheduler
    assert "session_prune.should_run()" not in source
    assert "session_prune_stop.set()" in source
    assert source.index("    yield") < source.index("session_prune_stop.set()")
