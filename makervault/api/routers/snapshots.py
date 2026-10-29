"""Snapshot routes, split out of main.py in Mf-x9dx; the logic lives in ``snapshot_service``.

The declaration order below is load-bearing: both ``/snapshots/retention`` routes
are declared before any ``/snapshots/{name}`` template, so a one-segment detail
route can never shadow the literal. FastAPI matches in declaration order, so
moving a ``{name}`` route up here would swallow ``retention`` as a snapshot name.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

import audit
import snapshot_guard
import snapshot_service
import snapshots
from auth import AuthContext
from db import engine
from permissions import require_admin, require_read, require_write
from schemas import (
    SnapshotBrowseOut,
    SnapshotCreatedOut,
    SnapshotDeleteOut,
    SnapshotListOut,
    SnapshotRestoreOut,
    SnapshotRestoreRequest,
    SnapshotRetentionIn,
    SnapshotRetentionOut,
)

router = APIRouter()


@router.get("/snapshots", response_model=SnapshotListOut)
def list_snapshots(_: Optional[AuthContext] = Depends(require_read)):
    return _guard(snapshot_service.list_out)


@router.post("/snapshots", response_model=SnapshotCreatedOut, status_code=201)
def create_snapshot(request: Request, context: Optional[AuthContext] = Depends(require_write)):
    # The provider writes the snapshot.create/snapshot.prune rows, so it is the
    # one place that gets a context here.
    return _guard(lambda: snapshot_service.create_out(audit.context_for(request, context)))


@router.get("/snapshots/retention", response_model=SnapshotRetentionOut)
def get_snapshot_retention(_: Optional[AuthContext] = Depends(require_admin)):
    return _retention()


@router.post("/snapshots/retention", response_model=SnapshotRetentionOut)
def update_snapshot_retention(
    body: SnapshotRetentionIn,
    request: Request,
    context: Optional[AuthContext] = Depends(require_admin),
):
    # Mirrors POST /settings/storage exactly: one Session(engine), the settings
    # writes join it, the audit row is staged into it, one commit.
    previous = _retention()
    policy = _policy(body)
    with Session(engine) as s:
        snapshots.set_retention_policy(policy, session=s)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(
                audit.SETTINGS_SNAPSHOT_RETENTION_UPDATE,
                "snapshot_retention",
                {"from": previous.model_dump(), "to": _policy_out(policy).model_dump()},
            ),
        )
        s.commit()
    return _retention()


@router.get("/snapshots/{name}/browse", response_model=SnapshotBrowseOut)
def browse_snapshot(
    name: str,
    _: Optional[AuthContext] = Depends(require_read),
    path: str = "",
):
    # ``path`` is a query parameter: a scalar with a default and no path template
    # placeholder is a query, which keeps the browse URL one segment per route.
    return _guard(lambda: snapshot_service.browse_out(name, path))


@router.post("/snapshots/{name}/restore", response_model=SnapshotRestoreOut, status_code=201)
def restore_snapshot(
    name: str,
    request: Request,
    body: Optional[SnapshotRestoreRequest] = None,
    context: Optional[AuthContext] = Depends(require_write),
):
    # The body is optional so a body-less POST still restores the whole snapshot:
    # the CLI and S5 call this with `{}` or with no body at all.
    payload = body or SnapshotRestoreRequest()
    return _guard(lambda: snapshot_service.restore_out(name, payload.path, audit.context_for(request, context)))


@router.delete("/snapshots/{name}", response_model=SnapshotDeleteOut)
def delete_snapshot(name: str, request: Request, context: Optional[AuthContext] = Depends(require_admin)):
    return _guard(lambda: snapshot_service.delete_out(name, audit.context_for(request, context)))


def _guard(action):
    """Run one service call, mapping `SnapshotPathError`/`NotFound`/`Unavailable`/`Exists`
    with `snapshot_guard.status_for` (400/404/409/409/500) and nothing else."""
    try:
        return action()
    except snapshots.SnapshotError as error:
        raise HTTPException(status_code=snapshot_guard.status_for(error), detail=str(error)) from error


def _retention() -> SnapshotRetentionOut:
    """The policy in force; a stored row that does not parse is a 400, not a 500."""
    try:
        return snapshot_service.retention_out()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _policy(body: SnapshotRetentionIn) -> snapshots.RetentionPolicy:
    """The validated policy for a request body; ``ValueError`` is the caller's 400."""
    try:
        return snapshot_service.retention_from(body)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _policy_out(policy: snapshots.RetentionPolicy) -> SnapshotRetentionOut:
    """The policy being written, rendered the same way the GET route renders it."""
    return SnapshotRetentionOut(
        keep_last_n=policy.keep_last_n,
        keep_daily=policy.keep_daily,
        max_age_days=policy.max_age_days,
        hard_cap=policy.hard_cap,
    )
