"""Durable history for mounted import runs.

One row per mount import attempt lives in ``import_run``, bounded to the newest
``KEEP`` rows. Lifecycle writes are short ad-hoc ``Session(engine)``
transactions issued by ``mount_import.scan_mount_imports()``; they never happen
inside ``library_scan.register_tree``, ``_flush_batch`` or a plan's ``prepare``.
Those run while ``library_scan._write_lock`` and a batch transaction are held, so
opening another write session there can deadlock SQLite and then be retried with
the batch, duplicating or losing the lifecycle row.

The live overlay is memory only. ``set_active``/``clear_active``/``active_state``
are guarded by their own lock and are never called while ``_write_lock`` or
``_state_lock`` is held.
"""

import json
import threading
import time
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import func, update
from sqlmodel import Session, delete, select

from db import engine
from library_scan import ScanState
from models import ImportRun

KEEP = 50

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
INTERRUPTED = "interrupted"
SKIPPED = "skipped"

_active_lock = threading.Lock()
_active: Optional[Tuple[str, ScanState]] = None


def _prune_to_keep(session: Session) -> None:
    """Delete every row outside the newest ``KEEP``, inside the caller's transaction.

    The caller must flush first so the row it just added is counted among the
    kept rows; otherwise the prune sees the pre-insert snapshot and deletes one
    row too many.
    """
    session.exec(
        delete(ImportRun).where(
            ImportRun.id.not_in(
                select(ImportRun.id)
                .order_by(ImportRun.started_at.desc(), ImportRun.id.desc())
                .limit(KEEP)
            )
        )
    )


def begin_run(root: str, mode: str, started_at: float) -> str:
    """Insert a running row and prune history to the newest ``KEEP`` rows.

    The insert and the prune share one transaction via ``_prune_to_keep``, so a
    crash cannot leave the table above the bound. The new row is newest and
    therefore kept.
    """
    run_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            ImportRun(
                id=run_id,
                kind="mount",
                status=RUNNING,
                mode=mode,
                root=root,
                started_at=started_at,
            )
        )
        session.flush()
        _prune_to_keep(session)
        session.commit()
    return run_id


def _finish(run_id: str, status: str, state: ScanState, rejected: int, reason: Optional[str] = None) -> None:
    with Session(engine) as session:
        row = session.get(ImportRun, run_id)
        if row is None:
            # A running row can only be pruned by a later begin, which cannot
            # happen while this run holds the walk; treat a missing row as done.
            return
        row.status = status
        row.finished_at = time.time()
        row.registered = state.registered
        row.known = state.known
        row.ignored = state.ignored
        row.failed = state.failed
        row.rejected = rejected
        row.reason = reason
        row.errors_json = json.dumps(state.errors)
        session.add(row)
        session.commit()


def finish_run(run_id: str, state: ScanState, rejected: int) -> None:
    """Persist a completed run's counters and per-file errors."""
    _finish(run_id, SUCCEEDED, state, rejected)


def fail_run(run_id: str, state: ScanState, rejected: int, reason: str) -> None:
    """Persist an aborted run with the same counters plus its abort reason."""
    _finish(run_id, FAILED, state, rejected, reason)


def skip_run(root: str, mode: Optional[str], reason: str) -> str:
    """Record a run that never started, with a mandatory reason.

    A misconfigured mount skips on every boot, so this write path is bounded
    like ``begin_run``: the insert and the prune to the newest ``KEEP`` rows are
    one transaction. The new row carries ``started_at = now``, which makes it the
    newest and therefore kept.
    """
    run_id = str(uuid.uuid4())
    now = time.time()
    with Session(engine) as session:
        session.add(
            ImportRun(
                id=run_id,
                kind="mount",
                status=SKIPPED,
                mode=mode,
                root=root,
                started_at=now,
                finished_at=now,
                reason=reason,
            )
        )
        session.flush()
        _prune_to_keep(session)
        session.commit()
    return run_id


def mark_interrupted() -> None:
    """Turn every stale ``running`` row into ``interrupted`` at startup.

    A row can still be ``running`` only because a previous process died before
    it could finish; the startup call runs before a new mount thread starts, so
    it cannot catch the current process's own run.
    """
    with Session(engine) as session:
        session.exec(
            update(ImportRun)
            .where(ImportRun.status == RUNNING)
            .values(status=INTERRUPTED, finished_at=time.time())
        )
        session.commit()


def list_runs(limit: int, offset: int) -> Tuple[List[ImportRun], int]:
    """Newest-first page of runs and the total row count."""
    with Session(engine) as session:
        total = session.exec(select(func.count()).select_from(ImportRun)).one()
        rows = list(
            session.exec(
                select(ImportRun)
                .order_by(ImportRun.started_at.desc(), ImportRun.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
    return rows, int(total)


def get_run(run_id: str) -> Optional[ImportRun]:
    with Session(engine) as session:
        return session.get(ImportRun, run_id)


def set_active(run_id: str, state: ScanState) -> None:
    """Expose the live counters of the run this process is walking."""
    global _active
    with _active_lock:
        _active = (run_id, state)


def clear_active(run_id: str) -> None:
    """Drop the overlay, but only if it still belongs to ``run_id``."""
    global _active
    with _active_lock:
        if _active is not None and _active[0] == run_id:
            _active = None


def active_state(run_id: str) -> Optional[ScanState]:
    """The live state for ``run_id`` while it is walking, else None."""
    with _active_lock:
        if _active is not None and _active[0] == run_id:
            return _active[1]
    return None
