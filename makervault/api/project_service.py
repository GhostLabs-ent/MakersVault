import json
import threading
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlmodel import Session, select

from models import Asset, Project, ProjectMembership, ProjectRelationship


PROJECT_NAME_MAX_LENGTH = 200
PROJECT_TAG_MAX_LENGTH = 64
PROJECT_TAG_MAX_COUNT = 100
PROJECT_PERMANENT_DELETE_CONFIRMATION = "PERMANENTLY DELETE PROJECT"
project_mutation_lock = threading.RLock()


def project_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _clean_optional(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_project_name(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Project name cannot be blank")
    if len(cleaned) > PROJECT_NAME_MAX_LENGTH:
        raise HTTPException(status_code=422, detail="Project name is too long")
    return cleaned


def normalize_project_tags(values: Iterable[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        if len(cleaned) > PROJECT_TAG_MAX_LENGTH:
            raise HTTPException(status_code=422, detail="Project tag is too long")
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(cleaned)
    if len(tags) > PROJECT_TAG_MAX_COUNT:
        raise HTTPException(status_code=422, detail="Too many Project tags")
    return tags


def require_active_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project or project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_trashed_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project or not project.deleted_at:
        raise HTTPException(status_code=404, detail="Project not found in Trash")
    return project


def _commit_unique_project(session: Session, project: Project) -> Project:
    session.add(project)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active Project with that name already exists",
        ) from exc
    session.refresh(project)
    return project


def create_project(session: Session, body) -> Project:
    now = project_timestamp()
    project = Project(
        name=normalize_project_name(body.name),
        notes=_clean_optional(body.notes),
        creator=_clean_optional(body.creator),
        source_url=_clean_optional(body.source_url),
        license=_clean_optional(body.license),
        tags_json=json.dumps(normalize_project_tags(body.tags)),
        created_at=now,
        updated_at=now,
    )
    return _commit_unique_project(session, project)


def update_project(session: Session, project_id: str, body) -> Project:
    project = require_active_project(session, project_id)
    provided = body.model_fields_set
    if not provided:
        raise HTTPException(status_code=422, detail="No Project fields were provided")
    if "name" in provided:
        project.name = normalize_project_name(body.name)
    for field in ("notes", "creator", "source_url", "license"):
        if field in provided:
            setattr(project, field, _clean_optional(getattr(body, field)))
    if "tags" in provided:
        project.tags_json = json.dumps(normalize_project_tags(body.tags or []))
    project.updated_at = project_timestamp()
    return _commit_unique_project(session, project)


def soft_delete_project(session: Session, project_id: str) -> None:
    with project_mutation_lock:
        project = require_active_project(session, project_id)
        now = project_timestamp()
        project.deleted_at = now
        project.updated_at = now
        session.add(project)
        session.commit()


def list_trashed_projects(
    session: Session,
    *,
    limit: int,
    offset: int,
) -> list[dict]:
    projects = list(session.exec(
        select(Project)
        .where(Project.deleted_at != None)  # noqa: E711
        .order_by(Project.deleted_at.desc(), Project.name, Project.id)
        .offset(offset)
        .limit(limit)
    ))
    project_ids = [project.id for project in projects]
    if not project_ids:
        return []

    def counts(statement) -> dict[str, int]:
        return {str(project_id): int(count) for project_id, count in session.exec(statement)}

    member_counts = counts(
        select(ProjectMembership.project_id, func.count(ProjectMembership.asset_id))
        .where(ProjectMembership.project_id.in_(project_ids))
        .group_by(ProjectMembership.project_id)
    )
    active_counts = counts(
        select(ProjectMembership.project_id, func.count(ProjectMembership.asset_id))
        .join(Asset, Asset.id == ProjectMembership.asset_id)
        .where(
            ProjectMembership.project_id.in_(project_ids),
            Asset.deleted_at == None,  # noqa: E711
        )
        .group_by(ProjectMembership.project_id)
    )
    trashed_counts = counts(
        select(ProjectMembership.project_id, func.count(ProjectMembership.asset_id))
        .join(Asset, Asset.id == ProjectMembership.asset_id)
        .where(
            ProjectMembership.project_id.in_(project_ids),
            Asset.deleted_at != None,  # noqa: E711
        )
        .group_by(ProjectMembership.project_id)
    )
    relationship_counts = counts(
        select(ProjectRelationship.project_id, func.count(ProjectRelationship.id))
        .where(ProjectRelationship.project_id.in_(project_ids))
        .group_by(ProjectRelationship.project_id)
    )
    return [
        {
            "id": project.id,
            "name": project.name,
            "deleted_at": project.deleted_at,
            "member_count": member_counts.get(project.id, 0),
            "active_member_count": active_counts.get(project.id, 0),
            "trashed_member_count": trashed_counts.get(project.id, 0),
            "relationship_count": relationship_counts.get(project.id, 0),
        }
        for project in projects
    ]


def restore_project(session: Session, project_id: str) -> Project:
    with project_mutation_lock:
        project = require_trashed_project(session, project_id)
        project.deleted_at = None
        project.updated_at = project_timestamp()
        session.add(project)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "project_name_conflict",
                    "message": (
                        "An active Project now uses this name; rename or remove "
                        "that Project before restoring this one"
                    ),
                },
            ) from exc
        session.refresh(project)
        return project


def permanently_delete_project(
    session: Session,
    project_id: str,
    confirmation: str,
) -> dict:
    if confirmation != PROJECT_PERMANENT_DELETE_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Type {PROJECT_PERMANENT_DELETE_CONFIRMATION} to permanently "
                "delete this Project"
            ),
        )
    with project_mutation_lock:
        project = require_trashed_project(session, project_id)
        relationships = list(session.exec(
            select(ProjectRelationship).where(
                ProjectRelationship.project_id == project_id
            )
        ))
        memberships = list(session.exec(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project_id
            )
        ))
        result = {
            "project_id": project.id,
            "name": project.name,
            "memberships_deleted": len(memberships),
            "relationships_deleted": len(relationships),
        }
        for relationship in relationships:
            session.delete(relationship)
        for membership in memberships:
            session.delete(membership)
        session.delete(project)
        session.commit()
        return result


def add_project_membership(
    session: Session,
    project_id: str,
    asset_id: str,
) -> ProjectMembership:
    with project_mutation_lock:
        require_active_project(session, project_id)
        asset = session.get(Asset, asset_id)
        if not asset or asset.deleted_at:
            raise HTTPException(status_code=404, detail="Artifact not found")
        if session.get(ProjectMembership, (project_id, asset_id)):
            raise HTTPException(status_code=409, detail="Artifact is already in this Project")
        membership = ProjectMembership(
            project_id=project_id,
            asset_id=asset_id,
            created_at=project_timestamp(),
        )
        session.add(membership)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Artifact is already in this Project",
            ) from exc
        session.refresh(membership)
        return membership


def remove_project_membership(
    session: Session,
    project_id: str,
    asset_id: str,
    *,
    confirm_relationship_cleanup: bool = False,
) -> None:
    with project_mutation_lock:
        require_active_project(session, project_id)
        membership = session.get(ProjectMembership, (project_id, asset_id))
        if not membership:
            raise HTTPException(status_code=404, detail="Project item not found")
        incident = list(session.exec(
            select(ProjectRelationship).where(
                ProjectRelationship.project_id == project_id,
                (
                    (ProjectRelationship.source_asset_id == asset_id)
                    | (ProjectRelationship.target_asset_id == asset_id)
                ),
            )
        ))
        if incident and not confirm_relationship_cleanup:
            count = len(incident)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "relationship_cleanup_confirmation_required",
                    "relationship_count": count,
                    "message": (
                        "Removing this Project item will also remove "
                        f"{count} relationship{'s' if count != 1 else ''}"
                    ),
                },
            )
        for relationship in incident:
            session.delete(relationship)
        session.delete(membership)
        session.commit()


def active_project_members(
    session: Session,
    project_id: str,
    *,
    limit: int,
    offset: int,
) -> list[Asset]:
    require_active_project(session, project_id)
    statement = (
        select(Asset)
        .join(ProjectMembership, ProjectMembership.asset_id == Asset.id)
        .where(
            ProjectMembership.project_id == project_id,
            Asset.deleted_at == None,  # noqa: E711
        )
        .order_by(Asset.name, Asset.filename, Asset.id)
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(statement))


def active_member_counts(session: Session, project_ids: Iterable[str]) -> dict[str, int]:
    ids = list(project_ids)
    if not ids:
        return {}
    statement = (
        select(ProjectMembership.project_id, func.count(ProjectMembership.asset_id))
        .join(Asset, Asset.id == ProjectMembership.asset_id)
        .where(
            ProjectMembership.project_id.in_(ids),
            Asset.deleted_at == None,  # noqa: E711
        )
        .group_by(ProjectMembership.project_id)
    )
    return {str(project_id): int(count) for project_id, count in session.exec(statement)}
