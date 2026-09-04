"""Convert stopped-instance recovery markers into durable startup audit events."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from audit_service import AuditContext, append_audit_event
from models import RecoveryMarker


_ACTIONS = {
    "raw_restore": "recovery.raw_restore",
    "administrator_recovery": "recovery.administrator",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def process_recovery_markers(database_engine: Engine) -> int:
    """Atomically audit and mark every pending, structurally valid marker."""
    processed = 0
    with Session(database_engine) as session:
        markers = list(
            session.exec(
                select(RecoveryMarker)
                .where(RecoveryMarker.processed_at.is_(None))
                .order_by(RecoveryMarker.created_at, RecoveryMarker.id)
            ).all()
        )
        for marker in markers:
            action = _ACTIONS.get(marker.kind)
            if action is None:
                raise RuntimeError("unknown pending recovery marker")
            try:
                details = json.loads(marker.details_json)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("invalid pending recovery marker details") from exc
            if not isinstance(details, dict):
                raise RuntimeError("invalid pending recovery marker details")
            revoked = details.get("revoked_sessions")
            if not isinstance(revoked, int) or isinstance(revoked, bool) or revoked < 0:
                raise RuntimeError("invalid pending recovery marker session count")
            audit_details: dict[str, object] = {"revoked_sessions": revoked}
            for field in ("revoked_challenges", "removed_credentials"):
                if field not in details:
                    continue
                count = details[field]
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise RuntimeError("invalid pending recovery marker authenticator count")
                audit_details[field] = count
            if "reset_mfa_policy" in details:
                reset_policy = details["reset_mfa_policy"]
                if not isinstance(reset_policy, bool):
                    raise RuntimeError("invalid pending recovery marker policy state")
                audit_details["reset_mfa_policy"] = reset_policy
            object_type = "recovery_marker"
            object_id = marker.id
            if marker.kind == "administrator_recovery":
                user_id = details.get("user_id")
                try:
                    object_id = str(uuid.UUID(str(user_id)))
                except ValueError as exc:
                    raise RuntimeError("invalid Administrator recovery account") from exc
                object_type = "user"
            append_audit_event(
                session,
                AuditContext(
                    correlation_id=str(uuid.uuid4()),
                    actor=None,
                    action=action,
                    method="SYSTEM",
                    route="startup",
                    permission=None,
                    source_address=None,
                    object_type=object_type,
                    object_id=object_id,
                ),
                result="success",
                status_code=200,
                details=audit_details,
            )
            marker.processed_at = _timestamp()
            session.add(marker)
            processed += 1
        session.commit()
    return processed
