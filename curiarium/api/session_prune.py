"""The session sweep: the background thread that deletes dead session rows.

`main.lifespan` starts exactly one daemon thread from here, and it starts it
**unconditionally** rather than behind an env gate. That is deliberate: expired
and long-revoked session rows are dead weight that must not accumulate, and
there is no deployment that wants them kept, so an opt-in switch would only
create a way to get it wrong. It also keeps the deploy manifests still - an env
var would have to appear in `docker-compose.deploy.yml`, `.env.example` and
`CONFIGURATION.md` for no operator benefit.

What a tick does and does not write:

* It deletes only rows that can no longer authorize anything: a refresh token
  past its absolute expiry (the access token is necessarily dead too, because it
  is shorter-lived) or a session revoked longer ago than the retention window.
  Live rows and freshly-revoked rows survive.
* Only when it deleted something does it write one count-only
  `session.prune` row, in the same session and transaction as the delete. The
  audit row and the delete are one atomic fact: an audit failure rolls the
  delete back. A tick that removed nothing writes nothing.
* The actor is the fixed `system` principal and `request_id` is empty, exactly
  like the scheduled-snapshot rows: nobody logs in as `system`, so a reader can
  tell a background action from a user's without joining anything.

`stop.wait(...)` is the only wait primitive, so a shutdown returns immediately
rather than up to one interval late, and a test drives this module without
sleeping. `import time` is allowed here, unlike in `snapshot_schedule`, because
`run_once` needs the wall clock for its default `now`; the wait path never
reads it. An exception from a tick is caught and logged so the thread survives.
"""

import logging
import threading
import time
from typing import Optional

from sqlmodel import Session

import audit
import sessions
from db import engine

log = logging.getLogger(__name__)

# Module constants rather than env vars, for the same reason as the grace window
# in `sessions`: the sweep's cadence is a correctness detail, not a deployment
# choice that needs a manifest entry.
INTERVAL_SECONDS = 3600
START_DELAY_SECONDS = 300
REVOKED_RETENTION_SECONDS = 24 * 60 * 60

# The audit target for this module's one row: it describes the sweep, not any
# particular session (the row carries only a count, never an id or a hash).
TARGET = "session_prune"

# The system principal a sweep row is attributed to. This mirrors the shape of
# `snapshot_schedule`'s fixed triple but is declared here rather than imported:
# each background module owns the actor it writes as, and importing one thread's
# constants into another would couple two unrelated lifetimes.
ACTOR_SYSTEM_USERNAME = "system"
ACTOR_SYSTEM_ROLE = "system"
ACTOR_SYSTEM_KIND = "system"
ACTOR_SYSTEM_PATH = "/sessions/prune"


def system_context() -> audit.AuditContext:
    """The audit context for a row written by the sweep's own thread.

    There is no request, so `request_id` and `method` are empty and `path` names
    the endpoint the sweep stands for. The actor is the fixed `system` principal.
    """
    return audit.AuditContext(
        actor=audit.Actor(ACTOR_SYSTEM_USERNAME, ACTOR_SYSTEM_ROLE, ACTOR_SYSTEM_KIND, None),
        request_id="",
        method="",
        path=ACTOR_SYSTEM_PATH,
    )


def prune(session: Session, *, now: Optional[int] = None) -> int:
    """Delete every dead session row in this transaction; return the count."""
    moment = int(time.time()) if now is None else now
    return sessions.delete_stale(session, now=moment, revoked_retention=REVOKED_RETENTION_SECONDS)


def run_once(now: Optional[int] = None) -> int:
    """One tick's whole unit of work: delete, then at most one audit row.

    The delete and the count-only row share one session and one commit, so an
    audit failure rolls the delete back instead of leaving dead rows deleted
    with no record of who did it. `now` is injectable so a test can age rows
    deterministically and never sleep.
    """
    with Session(engine) as session:
        count = prune(session, now=now)
        if count > 0:
            audit.stage(session, system_context(), audit.Event(audit.SESSION_PRUNE, TARGET, {"count": count}))
        session.commit()
    if count > 0:
        log.info("pruned %d dead session row(s)", count)
    return count


def run_forever(
    stop: threading.Event,
    *,
    interval_seconds: int = INTERVAL_SECONDS,
    start_delay_seconds: int = START_DELAY_SECONDS,
) -> None:
    """Tick until `stop` is set; the whole body of the lifespan thread.

    `stop.wait` is the wait primitive: it returns True as soon as the flag is
    set, so a shutdown is immediate rather than up to one interval late, and a
    `stop` that is already set returns at once, before the first tick. The start
    delay keeps the first sweep clear of boot work - migrations, the boot
    guards and the backfills.
    """
    if stop.wait(start_delay_seconds):
        return
    while not stop.wait(interval_seconds):
        try:
            run_once()
        except Exception:
            # A sweep that dies on one bad tick leaves dead rows for the rest of
            # the process's life and says nothing about it, which is the one
            # failure mode a background job cannot afford.
            log.exception("the session prune tick failed")
