import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlmodel import Session, select

from models import Asset, Project, ProjectMembership


PROJECT_NAME_MAX_LENGTH = 200
PROJECT_TAG_MAX_LENGTH = 64
PROJECT_TAG_MAX_COUNT = 100


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
    project = require_active_project(session, project_id)
    now = project_timestamp()
    project.deleted_at = now
    project.updated_at = now
    session.add(project)
    session.commit()


def add_project_membership(
    session: Session,
    project_id: str,
    asset_id: str,
) -> ProjectMembership:
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


def remove_project_membership(session: Session, project_id: str, asset_id: str) -> None:
    require_active_project(session, project_id)
    membership = session.get(ProjectMembership, (project_id, asset_id))
    if not membership:
        raise HTTPException(status_code=404, detail="Project item not found")
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
