"""Append-only audit log: one taxonomy, one emission point, one drift guard.

Failure semantics (the ticket's crux):
  * Row-mutating actions are FAIL-CLOSED. The audit row is inserted in the same
    session and transaction as the mutation and committed with it, so a failed
    audit write rolls the mutation back and the caller sees an error. The audit
    row and the row set it describes are one atomic fact.
  * Filesystem-only actions are FAIL-LOUD. `POST /trash/purge` and
    `POST /library/scan` destroy or launch things that carry no DB row, so there
    is nothing to roll back. Their row is written immediately after the action
    and a failure raises a 500, after logging. The bytes/scan are already gone or
    started; that residual window is documented, not hidden.

The emission point is the action site, not `permissions.authorize()`. Those are
two different things: `authorize()` is the *authorization* choke point (who may
call what) and sees no target, and it runs before the mutation, so it cannot
know whether anything changed or succeeded. An *event* is what happened, and
only the handler/service that performed it knows that. Every audited route
declares its actions in `ROUTE_ACTIONS`; `assert_audit_coverage()` (called from
`main.lifespan` right after `permissions.assert_routes_classified`) refuses to
boot when a mutating route is neither audited nor exempt. That guard, not a
comment, is what keeps a future route from silently escaping the log.

A request that changes nothing writes nothing: no-op rename, same-folder move,
same-role PATCH and tag-only folder edits stage zero events.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Request
from sqlalchemy import func
from sqlmodel import Session, select

import request_id
from auth import AuthContext
from db import engine
from models import AuditEvent

log = logging.getLogger(__name__)

ACTOR_DISABLED_USERNAME = "local"
ACTOR_DISABLED_ROLE = "auth-disabled"

ASSET_DELETE = "asset.delete"
ASSET_RENAME = "asset.rename"
ASSET_MOVE = "asset.move"
ASSET_FILE_DELETE = "asset.file.delete"
ASSET_FILE_RENAME = "asset.file.rename"
ASSET_FILE_REORDER = "asset.file.reorder"
ASSET_PREPARED_PRINT_DELETE = "asset.prepared_print.delete"
FOLDER_DELETE = "folder.delete"
FOLDER_RENAME = "folder.rename"
FOLDER_MOVE = "folder.move"
PROJECT_DELETE = "project.delete"
PROJECT_RENAME = "project.rename"
TRASH_PURGE = "trash.purge"
SETTINGS_STORAGE_UPDATE = "settings.storage.update"
SETTINGS_MOUNT_IMPORT_UPDATE = "settings.mount_import.update"
SETTINGS_SNAPSHOT_RETENTION_UPDATE = "settings.snapshot_retention.update"
USER_CREATE = "user.create"
USER_ROLE_CHANGE = "user.role_change"
USER_DISABLE = "user.disable"
USER_ENABLE = "user.enable"
LIBRARY_SCAN_START = "library.scan.start"
LOGIN_SUCCEEDED = "login.succeeded"
# An SSO login is its own action pair rather than a `kind` on login.succeeded:
# the exchange route is the only mutation, and the callback is the only place a
# rejection can be recorded, so both need a name an operator can filter on.
LOGIN_OIDC_SUCCEEDED = "login.oidc.succeeded"
LOGIN_OIDC_FAILED = "login.oidc.failed"
SNAPSHOT_CREATE = "snapshot.create"
SNAPSHOT_PRUNE = "snapshot.prune"
SNAPSHOT_DELETE = "snapshot.delete"
SNAPSHOT_RESTORE = "snapshot.restore"
# The scheduler's skip and failure rows are ACTIONS-only: they come from a
# background thread with no route to declare and no request context, so
# ROUTE_ACTIONS must not list them. A successful tick writes no new action; the
# provider's own snapshot.create/snapshot.prune rows cover it.
SNAPSHOT_SCHEDULE_SKIPPED = "snapshot.schedule.skipped"
SNAPSHOT_SCHEDULE_FAILED = "snapshot.schedule.failed"
DESTRUCTIVE_SNAPSHOT_TAKEN = "destructive.snapshot_taken"
DESTRUCTIVE_SNAPSHOT_MISSED = "destructive.snapshot_missed"

ACTIONS: frozenset[str] = frozenset({
    ASSET_DELETE,
    ASSET_RENAME,
    ASSET_MOVE,
    ASSET_FILE_DELETE,
    ASSET_FILE_RENAME,
    ASSET_FILE_REORDER,
    ASSET_PREPARED_PRINT_DELETE,
    FOLDER_DELETE,
    FOLDER_RENAME,
    FOLDER_MOVE,
    PROJECT_DELETE,
    PROJECT_RENAME,
    TRASH_PURGE,
    SETTINGS_STORAGE_UPDATE,
    SETTINGS_MOUNT_IMPORT_UPDATE,
    SETTINGS_SNAPSHOT_RETENTION_UPDATE,
    USER_CREATE,
    USER_ROLE_CHANGE,
    USER_DISABLE,
    USER_ENABLE,
    LIBRARY_SCAN_START,
    LOGIN_SUCCEEDED,
    LOGIN_OIDC_SUCCEEDED,
    LOGIN_OIDC_FAILED,
    SNAPSHOT_CREATE,
    SNAPSHOT_PRUNE,
    SNAPSHOT_DELETE,
    SNAPSHOT_RESTORE,
    SNAPSHOT_SCHEDULE_SKIPPED,
    SNAPSHOT_SCHEDULE_FAILED,
    DESTRUCTIVE_SNAPSHOT_TAKEN,
    DESTRUCTIVE_SNAPSHOT_MISSED,
})


@dataclass(frozen=True)
class Actor:
    """Who acted, copied at write time so the row survives a changed or deleted user."""

    username: str
    role: str
    kind: str
    user_id: Optional[str] = None


@dataclass(frozen=True)
class AuditContext:
    """Everything one request contributes to every row it writes."""

    actor: Actor
    request_id: str
    method: str
    path: str


@dataclass(frozen=True)
class Event:
    """One action on one target; `detail` is small JSON-safe context, never a secret."""

    action: str
    target: str
    detail: Optional[dict] = None


def context_for_actor(request: Request, actor: Actor) -> AuditContext:
    """Build the request-scoped context for an actor that is already known."""
    return AuditContext(
        actor=actor,
        request_id=request_id.get(request),
        method=request.method,
        path=request.url.path,
    )


def context_for(request: Request, context: Optional[AuthContext]) -> AuditContext:
    """The audit context for this request; never raises.

    `context is None` means authentication is disabled for this deployment, so
    the actor is the fixed `local` principal. That mode must keep working and a
    missing principal must never turn an audited action into a 500.
    """
    if context is None:
        return context_for_actor(request, Actor(ACTOR_DISABLED_USERNAME, ACTOR_DISABLED_ROLE, ACTOR_DISABLED_ROLE, None))
    return context_for_actor(request, Actor(context.username, context.role, context.kind, context.user_id))


def _now() -> str:
    """ISO-8601 UTC with a fixed precision, so lexical order is time order."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _add(session: Session, row: AuditEvent) -> None:
    """The single insert seam. Tests inject a failure here, nowhere else."""
    session.add(row)


def _row(ctx: AuditContext, event: Event) -> AuditEvent:
    return AuditEvent(
        created_at=_now(),
        actor=ctx.actor.username,
        actor_user_id=ctx.actor.user_id,
        actor_role=ctx.actor.role,
        actor_kind=ctx.actor.kind,
        action=event.action,
        target=event.target,
        detail_json=None if event.detail is None else json.dumps(event.detail, sort_keys=True),
        request_id=ctx.request_id,
        method=ctx.method,
        path=ctx.path,
    )


def stage(session: Session, ctx: Optional[AuditContext], *events: Event) -> None:
    """Add one row per event to the caller's session; NEVER commits.

    `ctx is None` is a no-op for callers that are not on a request path (library
    maintenance threads). Nothing else is swallowed: an insert failure is the
    caller's commit failure and rolls its mutation back with it.
    """
    if ctx is None:
        return
    for event in events:
        _add(session, _row(ctx, event))


def record(*events: Event, ctx: AuditContext) -> None:
    """Write events that have no transaction to join; log and raise on failure.

    Only for actions whose effect is outside the database (`trash.purge`,
    `library.scan.start`). There is nothing to roll back, so the residual window
    is the action itself; the failure must still be visible, never swallowed.
    """
    try:
        with Session(engine) as session:
            stage(session, ctx, *events)
            session.commit()
    except Exception:
        log.exception("Audit write failed for %s", ", ".join(event.action for event in events))
        raise


def _normalise_bound(value: str, *, upper: bool) -> str:
    """A bare YYYY-MM-DD means the whole day; anything else is compared as given."""
    candidate = value.strip()
    if len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
        return f"{candidate}T23:59:59.999999+00:00" if upper else f"{candidate}T00:00:00"
    return candidate


def _escape_like(value: str) -> str:
    """Escape LIKE metacharacters so a target filter is a literal substring."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_events(
    session: Session,
    *,
    actor: Optional[str] = None,
    action: Optional[str] = None,
    target: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[List[AuditEvent], int]:
    """Newest-first page of events and the total that matches the filters."""
    filters = []
    if actor:
        filters.append(func.lower(AuditEvent.actor) == actor.strip().lower())
    if action:
        filters.append(AuditEvent.action == action)
    if target:
        filters.append(AuditEvent.target.like(f"%{_escape_like(target)}%", escape="\\"))
    if since:
        filters.append(AuditEvent.created_at >= _normalise_bound(since, upper=False))
    if until:
        filters.append(AuditEvent.created_at <= _normalise_bound(until, upper=True))

    total = session.exec(select(func.count()).select_from(AuditEvent).where(*filters)).one()
    statement = (
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(statement)), int(total)


# The audited routes and the actions each one may write. Keys are the FastAPI
# path templates exactly as declared, so this table can be checked against the
# permission matrix without guessing.
ROUTE_ACTIONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("POST", "/login"): (LOGIN_SUCCEEDED,),
    # The one mutating OIDC route. `GET /auth/oidc/callback` also writes
    # `login.oidc.failed`, but it is a GET and records through `audit.record`
    # with its own transaction, so it has no entry here by design.
    ("POST", "/auth/oidc/exchange"): (LOGIN_OIDC_SUCCEEDED,),
    ("DELETE", "/asset/{asset_id}"): (ASSET_DELETE,),
    ("POST", "/assets/batch/delete"): (ASSET_DELETE, DESTRUCTIVE_SNAPSHOT_TAKEN, DESTRUCTIVE_SNAPSHOT_MISSED),
    ("POST", "/asset/{asset_id}/rename"): (ASSET_RENAME,),
    ("POST", "/asset/{asset_id}/meta"): (ASSET_RENAME,),
    ("POST", "/asset/{asset_id}/folder"): (ASSET_MOVE,),
    ("POST", "/assets/batch/folder"): (ASSET_MOVE,),
    ("DELETE", "/asset/{asset_id}/files/{file_id}"): (ASSET_FILE_DELETE,),
    ("PATCH", "/asset/{asset_id}/files/{file_id}"): (ASSET_FILE_RENAME,),
    ("PUT", "/asset/{asset_id}/files/order"): (ASSET_FILE_REORDER,),
    ("DELETE", "/asset/{asset_id}/prepared-print"): (ASSET_PREPARED_PRINT_DELETE,),
    ("PATCH", "/folder/{folder_id}"): (FOLDER_RENAME, FOLDER_MOVE),
    ("DELETE", "/folder/{folder_id}"): (FOLDER_DELETE, DESTRUCTIVE_SNAPSHOT_TAKEN, DESTRUCTIVE_SNAPSHOT_MISSED),
    ("PATCH", "/project/{project_id}"): (PROJECT_RENAME,),
    ("DELETE", "/project/{project_id}"): (PROJECT_DELETE,),
    ("POST", "/trash/purge"): (TRASH_PURGE, DESTRUCTIVE_SNAPSHOT_TAKEN, DESTRUCTIVE_SNAPSHOT_MISSED),
    ("POST", "/settings/storage"): (SETTINGS_STORAGE_UPDATE,),
    ("POST", "/settings/mount-import"): (SETTINGS_MOUNT_IMPORT_UPDATE,),
    # With the HTTP surface in place these four make the provider's own snapshot
    # actions route actions: POST /snapshots hands the provider a context.
    ("POST", "/snapshots"): (SNAPSHOT_CREATE, SNAPSHOT_PRUNE),
    ("DELETE", "/snapshots/{name}"): (SNAPSHOT_DELETE,),
    ("POST", "/snapshots/{name}/restore"): (SNAPSHOT_RESTORE,),
    ("POST", "/snapshots/retention"): (SETTINGS_SNAPSHOT_RETENTION_UPDATE,),
    ("POST", "/users"): (USER_CREATE,),
    ("PATCH", "/users/{user_id}"): (USER_ROLE_CHANGE, USER_DISABLE, USER_ENABLE),
    ("POST", "/library/scan"): (LIBRARY_SCAN_START,),
}

# Mutating routes that are deliberately NOT audited, each with the reason. The
# drift guard prints these, so "not audited" is a decision with a sentence, not
# an omission.
EXEMPT_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/upload"): "creates an asset; not destructive or administrative",
    ("POST", "/import"): "creates an asset from a URL",
    ("POST", "/import/project"): "creates a project and imports files from a URL",
    ("POST", "/import/inspect"): "outbound fetch, no mutation",
    ("POST", "/import/zip/entries"): "outbound fetch, no mutation",
    ("POST", "/import/zip"): "creates assets from a zip",
    ("POST", "/asset/{asset_id}/files"): "uploads a supporting file",
    ("POST", "/asset/{asset_id}/thumbnail-generated"): "derived cache artifact",
    ("POST", "/asset/{asset_id}/tags"): "metadata edit; rename and move are the audited edits",
    ("POST", "/assets/batch/tags"): "metadata edit; rename and move are the audited edits",
    ("POST", "/assets/batch/meta"): "creator/notes metadata edit; rename and move are the audited edits",
    ("POST", "/folders"): "creates a folder",
    ("POST", "/projects"): "creates a project",
    ("POST", "/project/{project_id}/assets"): "membership edit; deletes no files or asset rows",
    ("DELETE", "/project/{project_id}/assets"): "membership edit; deletes no files or asset rows",
    ("POST", "/refresh"): "session-token bookkeeping; the abusable surface is POST /login",
    ("POST", "/logout"): "session-token bookkeeping",
    ("POST", "/download/zip"): "streams a temp zip; stores nothing",
    ("POST", "/file-grants"): "mints a short-lived read-only file grant; mutates nothing",
}


def assert_audit_coverage() -> dict[tuple[str, str], tuple[str, ...]]:
    """Prove the audited routes and the permission matrix agree; return ROUTE_ACTIONS.

    Runs at startup (`main.lifespan`, immediately after
    `permissions.assert_routes_classified`) so a new mutating route that forgets
    to emit fails to boot. Every problem is collected before raising, mirroring
    the permission guard, so one startup log line shows the whole drift.
    """
    # Imported lazily: `permissions` imports `auth`, and `main` imports both.
    import permissions

    problems: list[str] = []

    for method, path in sorted(permissions.ROUTE_PERMISSIONS):
        if method == "GET":
            continue
        key = (method, path)
        if key not in ROUTE_ACTIONS and key not in EXEMPT_ROUTES:
            problems.append(
                f"{method} {path} mutates but is neither in ROUTE_ACTIONS nor EXEMPT_ROUTES; "
                "record its actions or state why it is not audited"
            )

    for method, path in sorted(ROUTE_ACTIONS):
        if (method, path) not in permissions.ROUTE_PERMISSIONS:
            problems.append(f"{method} {path} is in ROUTE_ACTIONS but no such route exists")
        if (method, path) in EXEMPT_ROUTES:
            problems.append(f"{method} {path} is in both ROUTE_ACTIONS and EXEMPT_ROUTES")

    for method, path in sorted(EXEMPT_ROUTES):
        if (method, path) not in permissions.ROUTE_PERMISSIONS:
            problems.append(f"{method} {path} is in EXEMPT_ROUTES but no such route exists")
        if not EXEMPT_ROUTES[(method, path)].strip():
            problems.append(f"{method} {path} is exempt without a reason")

    for method, path in sorted(ROUTE_ACTIONS):
        for action in ROUTE_ACTIONS[(method, path)]:
            if action not in ACTIONS:
                problems.append(f"{method} {path} declares unknown action {action!r}")

    if problems:
        raise RuntimeError("audit coverage does not match the routes:\n  - " + "\n  - ".join(problems))
    return ROUTE_ACTIONS
