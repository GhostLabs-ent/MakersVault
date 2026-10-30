"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

import audit
from auth import AuthContext
from db import engine
from models import AuditEvent
from permissions import require_admin
from schemas import AuditEventOut, AuditListOut

router = APIRouter()


def audit_event_to_out(row: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=row.id,
        created_at=row.created_at,
        actor=row.actor,
        actor_user_id=row.actor_user_id,
        actor_role=row.actor_role,
        actor_kind=row.actor_kind,
        action=row.action,
        target=row.target,
        detail=json.loads(row.detail_json) if row.detail_json else None,
        request_id=row.request_id,
        method=row.method,
        path=row.path,
    )


@router.get("/audit", response_model=AuditListOut)
def list_audit_events(
    actor: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Optional[AuthContext] = Depends(require_admin),
):
    with Session(engine) as s:
        rows, total = audit.list_events(
            s, actor=actor, action=action, target=target, since=since, until=until, limit=limit, offset=offset
        )
        events = [audit_event_to_out(row) for row in rows]
    return AuditListOut(events=events, total=total, limit=limit, offset=offset)
