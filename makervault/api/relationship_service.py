from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from models import Asset, ProjectMembership, ProjectRelationship
from project_service import project_mutation_lock, project_timestamp, require_active_project


RELATIONSHIP_LABELS = {
    "derived_from": ("Derived from", "Source of"),
    "documentation_for": ("Documents", "Documented by"),
    "component_of": ("Component of", "Contains"),
}
CYCLE_KINDS = {"derived_from", "component_of"}


def relationship_labels(kind: str) -> tuple[str, str]:
    labels = RELATIONSHIP_LABELS.get(kind)
    if not labels:
        raise HTTPException(status_code=422, detail="Unsupported relationship kind")
    return labels


def _require_active_endpoint(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if not asset or asset.deleted_at:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return asset


def _require_memberships(
    session: Session,
    project_id: str,
    asset_ids: Iterable[str],
) -> None:
    for asset_id in asset_ids:
        if not session.get(ProjectMembership, (project_id, asset_id)):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "endpoint_not_project_member",
                    "asset_id": asset_id,
                    "message": "Both endpoints must be active members of this Project",
                },
            )


def _would_create_cycle(
    session: Session,
    project_id: str,
    source_asset_id: str,
    target_asset_id: str,
    kind: str,
) -> bool:
    statement = text(
        """
        WITH RECURSIVE reachable(asset_id) AS (
            SELECT target_asset_id
            FROM projectrelationship
            WHERE project_id = :project_id
              AND kind = :kind
              AND source_asset_id = :target_asset_id
            UNION
            SELECT relationship.target_asset_id
            FROM projectrelationship AS relationship
            JOIN reachable
              ON relationship.source_asset_id = reachable.asset_id
            WHERE relationship.project_id = :project_id
              AND relationship.kind = :kind
        )
        SELECT 1 FROM reachable WHERE asset_id = :source_asset_id LIMIT 1
        """
    )
    return session.connection().execute(
        statement,
        {
            "project_id": project_id,
            "source_asset_id": source_asset_id,
            "target_asset_id": target_asset_id,
            "kind": kind,
        },
    ).first() is not None


def create_relationship(session: Session, project_id: str, body) -> ProjectRelationship:
    with project_mutation_lock:
        return _create_relationship(session, project_id, body)


def _create_relationship(session: Session, project_id: str, body) -> ProjectRelationship:
    require_active_project(session, project_id)
    relationship_labels(body.kind)
    if body.source_asset_id == body.target_asset_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "relationship_self_link",
                "message": "A Project item cannot relate to itself",
            },
        )
    _require_active_endpoint(session, body.source_asset_id)
    _require_active_endpoint(session, body.target_asset_id)
    _require_memberships(
        session,
        project_id,
        (body.source_asset_id, body.target_asset_id),
    )
    duplicate = session.exec(
        select(ProjectRelationship).where(
            ProjectRelationship.project_id == project_id,
            ProjectRelationship.source_asset_id == body.source_asset_id,
            ProjectRelationship.target_asset_id == body.target_asset_id,
            ProjectRelationship.kind == body.kind,
        )
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "relationship_duplicate",
                "message": "This relationship already exists",
            },
        )
    if body.kind in CYCLE_KINDS and _would_create_cycle(
        session,
        project_id,
        body.source_asset_id,
        body.target_asset_id,
        body.kind,
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "relationship_cycle",
                "message": "This relationship would create a directed cycle",
            },
        )
    relationship = ProjectRelationship(
        project_id=project_id,
        source_asset_id=body.source_asset_id,
        target_asset_id=body.target_asset_id,
        kind=body.kind,
        created_at=project_timestamp(),
    )
    session.add(relationship)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "relationship_duplicate",
                "message": "This relationship already exists",
            },
        ) from exc
    session.refresh(relationship)
    return relationship


def list_active_relationships(
    session: Session,
    project_id: str,
    *,
    limit: int,
    offset: int,
):
    require_active_project(session, project_id)
    source_asset = aliased(Asset)
    target_asset = aliased(Asset)
    statement = (
        select(ProjectRelationship, source_asset, target_asset)
        .join(source_asset, source_asset.id == ProjectRelationship.source_asset_id)
        .join(target_asset, target_asset.id == ProjectRelationship.target_asset_id)
        .where(
            ProjectRelationship.project_id == project_id,
            source_asset.deleted_at == None,  # noqa: E711
            target_asset.deleted_at == None,  # noqa: E711
        )
        .order_by(
            source_asset.name,
            target_asset.name,
            ProjectRelationship.kind,
            ProjectRelationship.id,
        )
        .offset(offset)
        .limit(limit + 1)
    )
    return list(session.exec(statement))


def delete_relationship(
    session: Session,
    project_id: str,
    relationship_id: str,
) -> None:
    with project_mutation_lock:
        require_active_project(session, project_id)
        relationship = session.get(ProjectRelationship, relationship_id)
        if not relationship or relationship.project_id != project_id:
            raise HTTPException(status_code=404, detail="Relationship not found")
        session.delete(relationship)
        session.commit()
