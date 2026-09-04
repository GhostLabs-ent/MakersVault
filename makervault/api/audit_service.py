"""Durable, bounded, secret-free audit records for Gate 11D-2."""

from __future__ import annotations

import json
import re
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal, Mapping, Optional

from fastapi import Request
from sqlalchemy import and_, or_
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from authorization import AccessKind, Permission, Role, RouteRule, route_rule
from models import AuditEvent


AuditResult = Literal["success", "denied", "failure"]
AUDIT_PAGE_MAX = 200
AUDIT_DETAILS_MAX_BYTES = 2048
SOURCE_ADDRESS_MAX = 128
_SAFE_ACTION = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DETAIL_KEYS = frozenset({
    "changed_fields",
    "revoked_sessions",
    "revoked_challenges",
    "removed_credentials",
    "reset_mfa_policy",
})
_CHANGED_FIELDS = frozenset({"display_name", "role", "enabled", "password"})
_OBJECT_PARAMETERS = {
    "user_id": "user",
    "session_id": "session",
    "folder_id": "folder",
    "project_id": "project",
    "asset_id": "artifact",
    "revision_id": "revision",
    "file_id": "file",
    "relationship_id": "relationship",
    "machine_id": "machine",
}
_EXPLICIT_ACTIONS: Mapping[tuple[str, str], str] = {
    ("POST", "/login"): "identity.login",
    ("GET", "/users"): "identity.account.list",
    ("POST", "/users"): "identity.account.create",
    ("PATCH", "/users/{user_id}"): "identity.account.update",
    ("POST", "/users/{user_id}/password-reset"): "identity.password.reset",
    ("POST", "/account/password"): "identity.password.change",
    ("POST", "/session/reauthenticate"): "identity.reauthenticate",
    ("POST", "/account/passkeys/registration/options"): "passkey.registration.begin",
    ("POST", "/account/passkeys/registration/verify"): "passkey.registration.complete",
    ("POST", "/account/passkeys/reauthentication/options"): "passkey.reauthentication.begin",
    ("POST", "/account/passkeys/reauthentication/verify"): "passkey.reauthentication.complete",
    ("PATCH", "/account/passkeys/{passkey_id}"): "passkey.credential.rename",
    ("DELETE", "/account/passkeys/{passkey_id}"): "passkey.credential.remove",
    ("GET", "/sessions"): "session.list",
    ("POST", "/logout"): "session.logout",
    ("DELETE", "/sessions/{session_id}"): "session.revoke",
    ("POST", "/sessions/revoke-all"): "session.revoke_all",
    ("GET", "/audit"): "audit.read",
    ("POST", "/download/zip"): "content.export",
    ("GET", "/folder/{folder_id}/download"): "content.export",
    ("GET", "/asset/{asset_id}/revisions/export"): "content.export",
    ("GET", "/project/{project_id}/export"): "content.export",
    ("POST", "/asset/{asset_id}/handoff"): "handoff.create",
    ("GET", "/handoff/redeem"): "handoff.redeem",
}
_MUTATION_ACTIONS: Mapping[Permission, str] = {
    Permission.CONTENT_MANAGE: "content.mutate",
    Permission.TRASH_RESTORE: "trash.restore",
    Permission.CONTENT_DELETE_PERMANENTLY: "content.delete_permanently",
    Permission.TRASH_EMPTY: "trash.empty",
    Permission.SETTINGS_MANAGE: "settings.update",
    Permission.JOBS_MANAGE: "job.start",
    Permission.CONTENT_EXPORT: "content.export",
    Permission.HANDOFF_CREATE: "handoff.create",
    Permission.SESSION_MANAGE_SELF: "session.manage",
    Permission.IDENTITY_MANAGE_SELF: "identity.manage_self",
    Permission.IDENTITY_MANAGE: "identity.manage",
}


@dataclass(frozen=True)
class AuditActor:
    user_id: str
    username: str
    role: Role


@dataclass(frozen=True)
class AuditContext:
    correlation_id: str
    actor: Optional[AuditActor]
    action: str
    method: str
    route: str
    permission: Optional[str]
    source_address: Optional[str]
    object_type: Optional[str] = None
    object_id: Optional[str] = None

    def for_object(self, object_type: str, object_id: str) -> "AuditContext":
        return replace(
            self,
            object_type=_bounded(object_type, 64),
            object_id=_safe_identifier(object_id),
        )


@dataclass(frozen=True)
class AuditPage:
    items: list[AuditEvent]
    limit: int
    has_more: bool
    next_cursor: Optional[str]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _bounded(value: object, maximum: int) -> str:
    return str(value or "")[:maximum]


def _safe_identifier(value: object) -> Optional[str]:
    candidate = str(value or "")
    if not _SAFE_IDENTIFIER.fullmatch(candidate):
        return None
    try:
        normalized = str(uuid.UUID(candidate))
    except ValueError:
        return None
    return normalized if candidate.lower() == normalized else None


def _details_json(details: Optional[Mapping[str, object]]) -> str:
    if not details:
        return "{}"
    unknown = set(details) - _DETAIL_KEYS
    if unknown:
        raise ValueError(f"audit detail keys are not allowed: {sorted(unknown)}")
    normalized: dict[str, object] = {}
    if "changed_fields" in details:
        fields = details["changed_fields"]
        if not isinstance(fields, (list, tuple)):
            raise ValueError("changed_fields must be a list")
        cleaned = sorted({str(field) for field in fields})
        if any(field not in _CHANGED_FIELDS for field in cleaned):
            raise ValueError("changed_fields contains a value that is not allowed")
        normalized["changed_fields"] = cleaned
    for key in ("revoked_sessions", "revoked_challenges", "removed_credentials"):
        if key in details:
            count = details[key]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError(f"{key} must be a non-negative integer")
            normalized[key] = min(count, 1_000_000)
    if "reset_mfa_policy" in details:
        reset_policy = details["reset_mfa_policy"]
        if not isinstance(reset_policy, bool):
            raise ValueError("reset_mfa_policy must be a boolean")
        normalized["reset_mfa_policy"] = reset_policy
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > AUDIT_DETAILS_MAX_BYTES:
        raise ValueError("audit details exceed the storage limit")
    return encoded


def _encode_cursor(event: AuditEvent) -> str:
    payload = json.dumps(
        [event.occurred_at, event.id],
        separators=(",", ":"),
    ).encode("utf-8")
    return urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    if not cursor or len(cursor) > 512:
        raise ValueError("audit cursor is invalid")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("audit cursor is invalid") from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not isinstance(payload[0], str)
        or len(payload[0]) > 64
        or not isinstance(payload[1], str)
        or _safe_identifier(payload[1]) is None
    ):
        raise ValueError("audit cursor is invalid")
    return payload[0], payload[1]


def audit_action_for_route(method: str, path: str, rule: RouteRule) -> Optional[str]:
    key = (method.upper(), path)
    explicit = _EXPLICIT_ACTIONS.get(key)
    if explicit:
        return explicit
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if rule.kind is not AccessKind.SESSION or rule.permission is None:
        return None
    return _MUTATION_ACTIONS.get(rule.permission)


def result_for_status(status_code: int) -> AuditResult:
    if status_code < 400:
        return "success"
    if status_code < 500:
        return "denied"
    return "failure"


def _actor_from_request(request: Request) -> Optional[AuditActor]:
    override = getattr(request.state, "audit_actor", None)
    if isinstance(override, AuditActor):
        return override
    principal = getattr(request.state, "session_principal", None)
    if principal is None:
        return None
    return AuditActor(
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role,
    )


def _object_from_request(request: Request) -> tuple[Optional[str], Optional[str]]:
    override_type = getattr(request.state, "audit_object_type", None)
    override_id = getattr(request.state, "audit_object_id", None)
    if override_type and override_id:
        return _bounded(override_type, 64), _safe_identifier(override_id)
    for parameter, value in reversed(tuple(request.path_params.items())):
        object_type = _OBJECT_PARAMETERS.get(parameter)
        object_id = _safe_identifier(value)
        if object_type and object_id:
            return object_type, object_id
    return None, None


def audit_context_from_request(
    request: Request,
    *,
    action: Optional[str] = None,
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
) -> AuditContext:
    rule = route_rule(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if not isinstance(route_path, str):
        raise ValueError("classified route required for audit")
    resolved_action = action or audit_action_for_route(request.method, route_path, rule)
    if not resolved_action:
        raise ValueError("audited route requires a stable action")
    inferred_type, inferred_id = _object_from_request(request)
    return AuditContext(
        correlation_id=getattr(
            request.state,
            "audit_correlation_id",
            str(uuid.uuid4()),
        ),
        actor=_actor_from_request(request),
        action=resolved_action,
        method=request.method.upper(),
        route=route_path,
        permission=rule.permission.value if rule.permission else None,
        source_address=request.client.host if request.client else None,
        object_type=object_type or inferred_type,
        object_id=_safe_identifier(object_id) if object_id else inferred_id,
    )


def append_audit_event(
    session: Session,
    context: AuditContext,
    *,
    result: AuditResult,
    status_code: int,
    details: Optional[Mapping[str, object]] = None,
) -> AuditEvent:
    if not _SAFE_ACTION.fullmatch(context.action):
        raise ValueError("audit action is invalid")
    if result not in {"success", "denied", "failure"}:
        raise ValueError("audit result is invalid")
    actor = context.actor
    event = AuditEvent(
        id=str(uuid.uuid4()),
        occurred_at=_timestamp(),
        correlation_id=_bounded(context.correlation_id, 64),
        actor_user_id=_safe_identifier(actor.user_id) if actor else None,
        actor_username=_bounded(actor.username, 256) if actor else None,
        actor_role=actor.role.value if actor else None,
        action=context.action,
        result=result,
        object_type=_bounded(context.object_type, 64) if context.object_type else None,
        object_id=_safe_identifier(context.object_id) if context.object_id else None,
        method=_bounded(context.method.upper(), 16),
        route=_bounded(context.route, 512),
        permission=_bounded(context.permission, 128) if context.permission else None,
        status_code=int(status_code),
        source_address=(
            _bounded(context.source_address, SOURCE_ADDRESS_MAX)
            if context.source_address
            else None
        ),
        details_json=_details_json(details),
    )
    session.add(event)
    session.flush()
    return event


def record_audit_event(
    database_engine: Engine,
    context: AuditContext,
    *,
    result: AuditResult,
    status_code: int,
    details: Optional[Mapping[str, object]] = None,
) -> AuditEvent:
    with Session(database_engine) as session:
        event = append_audit_event(
            session,
            context,
            result=result,
            status_code=status_code,
            details=details,
        )
        session.commit()
        session.refresh(event)
        session.expunge(event)
        return event


def list_audit_events(
    database_engine: Engine,
    *,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> AuditPage:
    if not 1 <= limit <= AUDIT_PAGE_MAX:
        raise ValueError("audit page limit must be between 1 and 200")
    boundary = _decode_cursor(cursor) if cursor else None
    with Session(database_engine) as session:
        statement = select(AuditEvent)
        if boundary is not None:
            occurred_at, event_id = boundary
            statement = statement.where(
                or_(
                    AuditEvent.occurred_at < occurred_at,
                    and_(
                        AuditEvent.occurred_at == occurred_at,
                        AuditEvent.id < event_id,
                    ),
                )
            )
        rows = list(
            session.exec(
                statement
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
                .limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        for item in items:
            session.expunge(item)
    return AuditPage(
        items=items,
        limit=limit,
        has_more=has_more,
        next_cursor=_encode_cursor(items[-1]) if has_more and items else None,
    )


def validate_audit_inventory() -> None:
    from authorization import ROUTE_AUTHORIZATION

    for (method, path), rule in ROUTE_AUTHORIZATION.items():
        required = method in {"POST", "PUT", "PATCH", "DELETE"} or (
            method,
            path,
        ) in _EXPLICIT_ACTIONS
        if required and not audit_action_for_route(method, path, rule):
            raise RuntimeError(f"audited route lacks a stable action: {(method, path)}")
