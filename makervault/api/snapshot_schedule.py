"""S8's scheduler: the background thread that takes library snapshots on a clock.

`main.lifespan` starts one daemon thread from here, and only when
`SNAPSHOT_SCHEDULE_ENABLED` is true, so a deployment that never opted in is never
snapshotted behind the operator's back. The thread wakes every
`SNAPSHOT_SCHEDULE_CHECK_SECONDS`, asks whether a snapshot is due, and takes one
at most every `SNAPSHOT_SCHEDULE_HOURS`.

What a tick does and does not write:

* A successful tick writes **no new audit action**. It hands the provider a
  system `AuditContext`, and S2's `SnapshotProvider.create` then emits
  `snapshot.create` (plus `snapshot.prune` for whatever retention removed). A
  second "the scheduler ran" row would say nothing the create row does not
  already say, and would double every scheduled snapshot in the log.
* This slice issues **zero `delete()` calls of its own**. Retention is only ever
  READ -- `retention_policy()` for the echo, `plan_prune()` for the warning that
  a create will prune -- and never re-declared: S2 owns the cascade, and a second
  copy of it here could only drift from the one that actually runs.
* The two rows this module does write (`snapshot.schedule.failed`,
  `snapshot.schedule.skipped`) are the ones the provider never gets to write,
  because in both cases it was never called.

The provider is rebuilt on every tick rather than cached: a provider reads the
retention policy when it is constructed, so an admin's edit takes effect on the
next due tick without a restart. The cost is one `storage_capabilities.detect()`
per check interval, which is what the boot guard already does.

`last_attempt` / `last_outcome` / `last_snapshot` / `last_error` are in-process
state: they reset on restart, because they describe this process's thread and a
restart is exactly the moment they stop being true. The snapshots themselves are
on disk and are read back from the provider, so the status surface survives a
restart in everything that matters except that history.

A library snapshot covers the filesystem and **not** the SQLite database. It
cannot restore a row, a setting or a user; it is not a backup. `DATABASE_CAVEAT`
carries that to the API consumer, and Mf-ljld owns the database backup/restore
that closes it.

The clock is `snapshots._now()` -- the documented seam -- and `stop.wait(...)` is
the only wait primitive, so a test drives this module without sleeping and a
shutdown returns immediately.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import audit
import config
import snapshot_service
import snapshots
import storage_capabilities
from schemas import SnapshotRetentionOut, SnapshotScheduleOut

log = logging.getLogger(__name__)

# The audit target for the two rows this module writes itself. Both describe the
# scheduler, not a snapshot: the snapshot actions are the provider's targets.
TARGET = "snapshot_schedule"

# The system principal a scheduled row is attributed to. These mirror the shape
# of ``audit.ACTOR_DISABLED_*`` (a fixed username/role/kind triple) but live here
# because they are this module's only actor: nobody logs in as ``system``, so the
# name can never collide with a real user, and a reader can tell a scheduled
# action from a user's without joining anything.
ACTOR_SYSTEM_USERNAME = "system"
ACTOR_SYSTEM_ROLE = "system"
ACTOR_SYSTEM_KIND = "system"
ACTOR_SYSTEM_PATH = "/snapshots/schedule"

OUTCOME_IDLE = "idle"
OUTCOME_CREATED = "created"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"

# The status surface's warnings, in the deterministic order `status_out` emits
# them. The four templated ones keep their ``{placeholder}`` names: the strings
# are part of what the web console matches on.
WARNING_DISABLED = "scheduled snapshots are disabled; set SNAPSHOT_SCHEDULE_ENABLED=true to run them"
WARNING_NO_METHOD = "this volume has no snapshot method; scheduled snapshots cannot run"
WARNING_PROVIDER_UNREADABLE = "the snapshot provider could not be read: {error}"
WARNING_RETENTION_UNREADABLE = "the stored retention policy could not be read: {error}"
WARNING_RETENTION_PRESSURE = "retention will prune {count} snapshot(s) on the next create"
WARNING_LAST_FAILED = "the last scheduled snapshot failed: {cause}"
WARNING_LAST_SKIPPED = "the last scheduled snapshot was skipped: {cause}"
DATABASE_CAVEAT = (
    "a library snapshot covers the filesystem only, not the SQLite database; "
    "pair it with a database backup (see Mf-ljld)"
)


@dataclass(frozen=True)
class TickOutcome:
    """What one tick did, and why; ``cause`` is the failure or refusal message."""

    outcome: str
    now: datetime
    snapshot: Optional[str] = None
    cause: Optional[str] = None


@dataclass(frozen=True)
class ScheduleState:
    """This process's view of its own thread; ``None`` before the first tick."""

    last_attempt: Optional[datetime] = None
    last_outcome: Optional[str] = None
    last_snapshot: Optional[str] = None
    last_error: Optional[str] = None


_state = ScheduleState()

# The dedupe key of the last row written: ``(action, cause)``. A refused volume
# fails the same way on every check, and a row per check would be a log flood
# that hides the one row that mattered.
_last_audited: Optional[tuple[str, str]] = None


def system_context() -> audit.AuditContext:
    """The audit context for a row written by the scheduler's thread.

    The row comes from a background thread with no request, so the context is
    built by hand: the actor is the fixed ``system`` principal, which is how a
    reader tells a scheduled action from a user's, and ``request_id``/``method``
    are empty because there is no request to copy them from. ``path`` carries the
    endpoint the scheduler stands for, so the row still says where it belongs.
    """
    return audit.AuditContext(
        actor=audit.Actor(ACTOR_SYSTEM_USERNAME, ACTOR_SYSTEM_ROLE, ACTOR_SYSTEM_KIND, None),
        request_id="",
        method="",
        path=ACTOR_SYSTEM_PATH,
    )


def should_run() -> bool:
    """Whether the lifespan should start the thread (reads config at call time)."""
    return bool(config.SNAPSHOT_SCHEDULE_ENABLED)


def run_once(now: datetime) -> TickOutcome:
    """One tick's whole unit of work, with the clock injected.

    The tick reads no clock of its own, so a test decides what "due" means. The
    sequence is: list, decide, create, record.

    "Due" is measured from the newest ``scheduled`` snapshot's own ``created_at``
    rather than from this process's memory, so a restart, a second replica or a
    manual snapshot all leave the schedule correct: a volume with no prior
    scheduled snapshot is due immediately. ``SNAPSHOT_SCHEDULE_HOURS <= 0`` makes
    every tick due; the retention policy still bounds the count, which is why
    that is a supported setting and not a foot-gun.

    An idle tick writes no audit row: at one tick per check interval, a row per
    idle check would fill the log with the absence of an action.
    """
    # Rebuilt every call, never cached across ticks: the provider reads the
    # retention policy when it is constructed, so a fresh one per tick is what
    # makes an admin's retention edit take effect without a restart.
    try:
        provider = snapshot_service.provider()
    except (snapshots.SnapshotError, ValueError) as error:
        # ``ValueError`` is a corrupt ``snapshot_*`` settings row: the provider
        # reads the policy when it is constructed, so that row surfaces here,
        # before ``create`` is ever reached.
        return _record(TickOutcome(OUTCOME_FAILED, now, cause=str(error)), audit.SNAPSHOT_SCHEDULE_FAILED)

    try:
        existing = provider.list()
    except snapshots.SnapshotError as error:
        # Without the listing the tick cannot know whether it is due, so this is
        # a failure and not a silent idle: the schedule is now unknown.
        return _record(
            TickOutcome(OUTCOME_FAILED, now, cause=str(error)),
            audit.SNAPSHOT_SCHEDULE_FAILED,
            method=provider.method,
        )

    newest = next(
        (snapshot for snapshot in reversed(existing) if snapshot.reason is snapshots.SnapshotReason.SCHEDULED),
        None,
    )
    if newest is not None and now - newest.created_at < timedelta(hours=config.SNAPSHOT_SCHEDULE_HOURS):
        return _record(TickOutcome(OUTCOME_IDLE, now))

    try:
        created = provider.create(snapshots.SnapshotReason.SCHEDULED, ctx=system_context())
    except snapshots.SnapshotUnavailable as error:
        # A volume with no snapshot method is a refusal to report, not a
        # failure: nothing broke, this volume simply cannot snapshot.
        return _record(
            TickOutcome(OUTCOME_SKIPPED, now, cause=str(error)),
            audit.SNAPSHOT_SCHEDULE_SKIPPED,
            method=provider.method,
        )
    except (snapshots.SnapshotError, ValueError) as error:
        # ``ValueError`` is here because a corrupt ``snapshot_*`` settings row
        # makes ``retention_policy()`` raise, and the provider reads the policy
        # when it is constructed.
        return _record(
            TickOutcome(OUTCOME_FAILED, now, cause=str(error)),
            audit.SNAPSHOT_SCHEDULE_FAILED,
            method=provider.method,
        )

    return _record(TickOutcome(OUTCOME_CREATED, now, snapshot=created.snapshot.name))


def tick(now: datetime) -> TickOutcome:
    """``run_once`` behind a blanket catch: the thread must never die.

    Whatever ``run_once`` raises, the outcome is reported and the thread lives to
    tick again. A scheduler that dies on one bad tick stops taking snapshots for
    the rest of the process's life and says nothing about it, which is the one
    failure mode a scheduled job cannot afford.
    """
    try:
        return run_once(now)
    except Exception as error:
        log.exception("the scheduled snapshot tick failed")
        outcome = TickOutcome(OUTCOME_FAILED, now, cause=str(error) or type(error).__name__)
        return _record(outcome, audit.SNAPSHOT_SCHEDULE_FAILED)


def run_forever(stop: threading.Event, *, check_seconds: Optional[int] = None) -> None:
    """Tick until ``stop`` is set; the whole body of the lifespan thread.

    ``stop.wait`` is the wait primitive (never ``time.sleep``): it returns True as
    soon as the flag is set, so a shutdown is immediate rather than up to one
    interval late, and a ``stop`` that is already set returns at once, before the
    first tick. The start delay keeps the first tick clear of boot work --
    migrations, the boot guards, the backfills -- which is also why the lifespan
    starts this thread last.
    """
    interval = config.SNAPSHOT_SCHEDULE_CHECK_SECONDS if check_seconds is None else check_seconds
    if stop.wait(config.SNAPSHOT_SCHEDULE_START_DELAY_SECONDS):
        return
    while not stop.is_set():
        tick(snapshots._now())
        if stop.wait(interval):
            return


def status_out() -> SnapshotScheduleOut:
    """The scheduler as the API reports it, and it NEVER raises.

    Every step degrades to a warning instead of an error: the status surface is a
    diagnostic, and a volume whose retention row is corrupt is exactly the volume
    an operator opens it to look at. The alternative -- a 500 here -- would hide
    the problem behind the report that exists to show it.
    """
    now = snapshots._now()
    provider_error: Optional[str] = None
    retention_error: Optional[str] = None

    method = storage_capabilities.NO_METHOD
    listed: list[snapshots.Snapshot] = []
    # Derived before the provider is built, not from it: a corrupt retention row
    # makes construction raise, and reporting "no snapshot method" for a volume
    # that has one would be a second, false warning next to the true one.
    method = snapshot_service.library_method()
    try:
        provider = snapshot_service.provider()
    except (snapshots.SnapshotError, ValueError) as error:
        provider_error = str(error)
    else:
        try:
            listed = provider.list()
        except snapshots.SnapshotError as error:
            provider_error = str(error)

    retention: Optional[SnapshotRetentionOut] = None
    policy: Optional[snapshots.RetentionPolicy] = None
    try:
        # S4's echo is what the API reports; the typed policy is what
        # ``plan_prune`` needs. Both come from the same stored row, so they are
        # read together and fail together.
        retention = snapshot_service.retention_out()
        policy = snapshots.retention_policy()
    except ValueError as error:
        retention_error = str(error)

    names = [snapshot.name for snapshot in listed]
    # Only with both halves available: a policy without the current names would
    # report a prune count for a volume state that no longer exists. ``plan_prune``
    # does no I/O and takes ``now``, so the warning is deterministic.
    pruned = 0
    if policy is not None and names:
        pruned = snapshots.plan_prune(names, policy, now=now).pruned

    cutoff = now - timedelta(hours=24)
    warnings: list[str] = []
    if not config.SNAPSHOT_SCHEDULE_ENABLED:
        warnings.append(WARNING_DISABLED)
    if method == storage_capabilities.NO_METHOD:
        warnings.append(WARNING_NO_METHOD)
    if provider_error is not None:
        warnings.append(WARNING_PROVIDER_UNREADABLE.format(error=provider_error))
    if retention_error is not None:
        warnings.append(WARNING_RETENTION_UNREADABLE.format(error=retention_error))
    if pruned > 0:
        warnings.append(WARNING_RETENTION_PRESSURE.format(count=pruned))
    if _state.last_outcome == OUTCOME_FAILED:
        warnings.append(WARNING_LAST_FAILED.format(cause=_state.last_error))
    elif _state.last_outcome == OUTCOME_SKIPPED:
        warnings.append(WARNING_LAST_SKIPPED.format(cause=_state.last_error))

    return SnapshotScheduleOut(
        enabled=config.SNAPSHOT_SCHEDULE_ENABLED,
        hours=config.SNAPSHOT_SCHEDULE_HOURS,
        check_seconds=config.SNAPSHOT_SCHEDULE_CHECK_SECONDS,
        last_attempt=_iso(_state.last_attempt),
        last_outcome=_state.last_outcome,
        last_snapshot=_state.last_snapshot,
        last_error=_state.last_error,
        # ``list`` returns oldest first, so the ends are the ends.
        count=len(listed),
        last_24h=sum(1 for snapshot in listed if snapshot.created_at >= cutoff),
        oldest=_iso(listed[0].created_at) if listed else None,
        newest=_iso(listed[-1].created_at) if listed else None,
        retention=retention,
        warnings=warnings,
        database_caveat=DATABASE_CAVEAT,
    )


def reset_state() -> None:
    """Forget this process's tick history; the test seam, and what a restart does."""
    global _state, _last_audited
    _state = ScheduleState()
    _last_audited = None


def _iso(value: Optional[datetime]) -> Optional[str]:
    """Aware UTC ISO-8601 for the status surface, or None when there is nothing to report."""
    return None if value is None else value.astimezone(timezone.utc).isoformat()


def _record(outcome: TickOutcome, action: Optional[str] = None, *, method: str = "") -> TickOutcome:
    """Store the outcome first, then write at most one deduplicated audit row.

    The state is written before the row on purpose: the status surface must stay
    honest even when the row's write fails, because it is the only place the
    failure would otherwise show up.

    ``action=None`` means the outcome needs no row (an idle tick, a successful
    create -- the provider wrote ``snapshot.create`` itself).

    The dedupe key is ``(action, cause)``: a refused volume fails the same way on
    every check, and one row per check would flood the log with a fact that has
    not changed. A successful create clears the key, so a refusal that recurs
    after a good tick is a new fact and is recorded again. A row whose write
    failed leaves the key unset, so the next identical tick retries it.
    """
    global _state, _last_audited
    _state = ScheduleState(
        last_attempt=outcome.now,
        last_outcome=outcome.outcome,
        last_snapshot=outcome.snapshot,
        last_error=outcome.cause,
    )
    if outcome.outcome == OUTCOME_CREATED:
        _last_audited = None
        return outcome
    if action is None:
        return outcome

    key = (action, outcome.cause or "")
    if key == _last_audited:
        return outcome

    event = audit.Event(
        action,
        TARGET,
        {"cause": outcome.cause, "method": method, "hours": config.SNAPSHOT_SCHEDULE_HOURS},
    )
    try:
        audit.record(event, ctx=system_context())
    except Exception:
        # ``audit.record`` is fail-loud because a request caller can act on it.
        # A background thread has no caller to fail, so here the row's failure is
        # logged and the tick's outcome is unchanged: the requirement this thread
        # is held to is that it never dies, not that it never loses a row.
        log.exception("the scheduled snapshot audit row could not be written")
        return outcome
    _last_audited = key
    return outcome
