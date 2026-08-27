from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from machine_service import (
    machine_mutation_lock,
    machine_timestamp,
    require_active_machine,
)
from models import ArtifactMachine, ArtifactRevision, Asset, MachineProfile
from trash_service import require_active_asset


DESCRIPTIVE_CONTEXT_NOTICE = "Descriptive context only. No job was sent."
PREPARED_MACHINE_CATEGORIES = {"fdm_printer", "resin_printer"}


def list_machine_context(
    session: Session,
    asset_id: str,
) -> tuple[Asset, list[tuple[ArtifactMachine, MachineProfile]], MachineProfile | None]:
    asset = require_active_asset(session, asset_id)
    associations: list[tuple[ArtifactMachine, MachineProfile]] = []
    for association in session.exec(
        select(ArtifactMachine).where(ArtifactMachine.asset_id == asset_id)
    ):
        machine = session.get(MachineProfile, association.machine_id)
        if machine:
            associations.append((association, machine))
    associations.sort(key=lambda row: (row[1].name.casefold(), row[1].id))
    prepared_machine = (
        session.get(MachineProfile, asset.prepared_machine_id)
        if asset.prepared_machine_id
        else None
    )
    return asset, associations, prepared_machine


def add_machine_association(
    session: Session,
    asset_id: str,
    machine_id: str,
) -> None:
    with machine_mutation_lock:
        require_active_asset(session, asset_id)
        require_active_machine(session, machine_id)
        if session.get(ArtifactMachine, (asset_id, machine_id)):
            raise HTTPException(status_code=409, detail="Machine association already exists")
        session.add(ArtifactMachine(
            asset_id=asset_id,
            machine_id=machine_id,
            created_at=machine_timestamp(),
        ))
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="Machine association already exists"
            ) from exc


def remove_machine_association(
    session: Session,
    asset_id: str,
    machine_id: str,
) -> None:
    with machine_mutation_lock:
        require_active_asset(session, asset_id)
        association = session.get(ArtifactMachine, (asset_id, machine_id))
        if not association:
            raise HTTPException(status_code=404, detail="Machine association not found")
        session.delete(association)
        session.commit()


def set_prepared_machine(
    session: Session,
    asset_id: str,
    machine_id: str | None,
) -> None:
    with machine_mutation_lock:
        asset = require_active_asset(session, asset_id)
        revision = (
            session.get(ArtifactRevision, asset.current_revision_id)
            if asset.current_revision_id
            else None
        )
        if not revision or revision.asset_id != asset.id:
            raise HTTPException(status_code=409, detail="Current revision is unavailable")
        if machine_id is None:
            asset.prepared_machine_id = None
            revision.prepared_machine_id = None
        else:
            if not asset.prepared_metadata_json:
                raise HTTPException(
                    status_code=409,
                    detail="A prepared print is required before selecting a Machine",
                )
            machine = require_active_machine(session, machine_id)
            if machine.category not in PREPARED_MACHINE_CATEGORIES:
                raise HTTPException(
                    status_code=422,
                    detail="Prepared targets require an FDM or resin printer profile",
                )
            asset.prepared_machine_id = machine.id
            revision.prepared_machine_id = machine.id
        session.add(asset)
        session.add(revision)
        session.commit()
