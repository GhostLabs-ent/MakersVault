import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from models import MachineProfile


MACHINE_NAME_MAX_LENGTH = 200
MACHINE_PERMANENT_DELETE_CONFIRMATION = "PERMANENTLY DELETE MACHINE"
machine_mutation_lock = threading.RLock()


def machine_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _clean_optional(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_machine_name(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Machine name cannot be blank")
    if len(cleaned) > MACHINE_NAME_MAX_LENGTH:
        raise HTTPException(status_code=422, detail="Machine name is too long")
    return cleaned


def require_machine(session: Session, machine_id: str) -> MachineProfile:
    machine = session.get(MachineProfile, machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


def require_active_machine(session: Session, machine_id: str) -> MachineProfile:
    machine = require_machine(session, machine_id)
    if machine.archived_at:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


def require_archived_machine(session: Session, machine_id: str) -> MachineProfile:
    machine = require_machine(session, machine_id)
    if not machine.archived_at:
        raise HTTPException(status_code=404, detail="Machine is not archived")
    return machine


def _commit_unique_machine(
    session: Session,
    machine: MachineProfile,
) -> MachineProfile:
    session.add(machine)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active Machine with that name already exists",
        ) from exc
    session.refresh(machine)
    return machine


def create_machine(session: Session, body) -> MachineProfile:
    now = machine_timestamp()
    machine = MachineProfile(
        name=normalize_machine_name(body.name),
        category=body.category,
        manufacturer=_clean_optional(body.manufacturer),
        model=_clean_optional(body.model),
        location=_clean_optional(body.location),
        notes=_clean_optional(body.notes),
        created_at=now,
        updated_at=now,
    )
    return _commit_unique_machine(session, machine)


def update_machine(
    session: Session,
    machine_id: str,
    body,
) -> MachineProfile:
    machine = require_active_machine(session, machine_id)
    provided = body.model_fields_set
    if not provided:
        raise HTTPException(status_code=422, detail="No Machine fields were provided")
    if "name" in provided:
        machine.name = normalize_machine_name(body.name)
    if "category" in provided:
        if body.category is None:
            raise HTTPException(status_code=422, detail="Machine category cannot be null")
        machine.category = body.category
    for field in ("manufacturer", "model", "location", "notes"):
        if field in provided:
            setattr(machine, field, _clean_optional(getattr(body, field)))
    machine.updated_at = machine_timestamp()
    return _commit_unique_machine(session, machine)


def archive_machine(session: Session, machine_id: str) -> MachineProfile:
    with machine_mutation_lock:
        machine = require_active_machine(session, machine_id)
        now = machine_timestamp()
        machine.archived_at = now
        machine.updated_at = now
        session.add(machine)
        session.commit()
        session.refresh(machine)
        return machine


def restore_machine(session: Session, machine_id: str) -> MachineProfile:
    with machine_mutation_lock:
        machine = require_archived_machine(session, machine_id)
        machine.archived_at = None
        machine.updated_at = machine_timestamp()
        session.add(machine)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "machine_name_conflict",
                    "message": (
                        "An active Machine now uses this name; rename or archive "
                        "that Machine before restoring this one"
                    ),
                },
            ) from exc
        session.refresh(machine)
        return machine


def permanently_delete_machine(
    session: Session,
    machine_id: str,
    confirmation: str,
) -> dict:
    if confirmation != MACHINE_PERMANENT_DELETE_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Type {MACHINE_PERMANENT_DELETE_CONFIRMATION} to permanently "
                "delete this Machine"
            ),
        )
    with machine_mutation_lock:
        machine = require_archived_machine(session, machine_id)
        result = {
            "machine_id": machine.id,
            "name": machine.name,
            "associations_deleted": 0,
            "prepared_references_cleared": 0,
        }
        session.delete(machine)
        session.commit()
        return result
