"""Projects and their asset memberships: rows only, never storage paths.

A project is a row plus a join table (`project`, `project_asset`, migration 007).
It owns no directory, no filename and no bytes, so nothing in this module touches
the filesystem - deleting a project cannot delete an asset or a file.

`cover_asset_id` is a free reference to any existing asset: it needs no
membership, removing the membership leaves it alone, and the asset's own
`DELETE /asset/{id}` sets it to NULL through the schema's `ON DELETE SET NULL`.

Membership edits are one transaction per request: an unknown asset id becomes a
per-id `BatchFailure` while the valid ids still apply (partial success is the
contract, see `bulk_service`), and an unknown project is a whole-request 404.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

import audit
import bulk_service
from db import engine
from models import Asset, Project, ProjectAsset


def _now() -> str:
    """ISO-8601 UTC with a fixed precision, matching migration 007's columns."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _clean_name(name: Optional[str]) -> str:
    """A project's name is trimmed; whitespace alone is not a name."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="name is required")
    return cleaned


def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def count_members(session: Session, project_id: str) -> int:
    """Memberships of one project in a single aggregate statement."""
    statement = select(func.count()).select_from(ProjectAsset).where(ProjectAsset.project_id == project_id)
    return int(session.exec(statement).one())


def create_project(
    session: Session,
    name: str,
    description: Optional[str],
    cover_asset_id: Optional[str],
) -> Project:
    """Insert one project; the caller's session commits.

    Creation is an exempt audit class (like an upload or a new folder), so this
    stages no event: `project.delete` and `project.rename` are the audited edits.
    """
    name = _clean_name(name)
    if cover_asset_id:
        get_asset(session, cover_asset_id)
    stamp = _now()
    project = Project(
        name=name,
        description=description,
        cover_asset_id=cover_asset_id or None,
        created_at=stamp,
        updated_at=stamp,
    )
    try:
        session.add(project)
        session.commit()
        session.refresh(project)
    except IntegrityError:
        # `idx_project_name_unique` is the only unique key on the table, and it
        # is NOCASE: the name collides with a project differing only by case.
        session.rollback()
        raise HTTPException(status_code=409, detail="Project name already exists") from None
    return project


def update_project(
    session: Session,
    project: Project,
    fields: set[str],
    name: Optional[str],
    description: Optional[str],
    cover_asset_id: Optional[str],
    *,
    audit_ctx: Optional[audit.AuditContext],
) -> Project:
    """Apply the fields the patch actually carried, then commit.

    `fields` is the request body's `model_fields_set`: a field that is present and
    None clears its column, a field that is absent is left alone. Only a real
    rename is audited, so a description-only PATCH stages nothing.
    """
    previous_name = project.name
    next_name = _clean_name(name) if "name" in fields else previous_name
    # Validate the reference before mutating the row, so a 404 leaves it untouched.
    if "cover_asset_id" in fields and cover_asset_id:
        get_asset(session, cover_asset_id)

    if "name" in fields:
        project.name = next_name
    if "description" in fields:
        project.description = description
    if "cover_asset_id" in fields:
        project.cover_asset_id = cover_asset_id
    project.updated_at = _now()
    session.add(project)
    if next_name != previous_name:
        audit.stage(
            session,
            audit_ctx,
            audit.Event(audit.PROJECT_RENAME, project.id, {"from": previous_name, "to": next_name}),
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Project name already exists") from None
    session.refresh(project)
    return project


def delete_project(session: Session, project: Project, *, audit_ctx: Optional[audit.AuditContext]) -> None:
    """Delete one project and its memberships in a single transaction.

    The memberships are deleted explicitly before the row even though
    `project_asset` declares `ON DELETE CASCADE`: it keeps the delete correct on a
    connection without `PRAGMA foreign_keys`. Assets, their files and the bytes on
    disk are never touched.
    """
    name = project.name
    session.execute(delete(ProjectAsset).where(ProjectAsset.project_id == project.id))
    session.delete(project)
    audit.stage(session, audit_ctx, audit.Event(audit.PROJECT_DELETE, project.id, {"name": name}))
    session.commit()


def list_projects(session: Session) -> List[Tuple[Project, int]]:
    """Every project with its member count, in one aggregate statement.

    The count is part of the same query, so listing N projects costs one statement
    instead of 1 + N; the ordering is case-insensitive by name, then by id so two
    projects that differ only in case still page deterministically.
    """
    statement = (
        select(Project, func.count(ProjectAsset.asset_id))
        .outerjoin(ProjectAsset, ProjectAsset.project_id == Project.id)
        .group_by(Project.id)
        .order_by(func.lower(Project.name), Project.id)
    )
    return [(project, int(count)) for project, count in session.exec(statement)]


def _failure(asset_id: str) -> dict:
    """The per-id failure shape, reused from `bulk_service` so it cannot drift."""
    return bulk_service._failure(asset_id, HTTPException(status_code=404, detail="Asset not found"))


def _membership_ids(session: Session, project_id: str) -> set[str]:
    statement = select(ProjectAsset.asset_id).where(ProjectAsset.project_id == project_id)
    return set(session.exec(statement).all())


def add_assets(project_id: str, asset_ids: List[str]) -> Tuple[List[str], List[str], List[dict]]:
    """Add existing assets to a project; returns (added, skipped, failed).

    Unknown asset ids are reported per id and never abort the rest, so the request
    is one transaction over the ids that can succeed. Adding a current member is a
    skip, which makes a repeated request idempotent instead of a duplicate row.
    """
    ids = bulk_service.unique_asset_ids(asset_ids)
    added: List[str] = []
    skipped: List[str] = []
    failed: List[dict] = []
    with Session(engine) as session:
        project = get_project(session, project_id)
        known = set(session.exec(select(Asset.id).where(Asset.id.in_(ids))).all()) if ids else set()
        members = _membership_ids(session, project.id)
        stamp = _now()
        for asset_id in ids:
            if asset_id not in known:
                failed.append(_failure(asset_id))
            elif asset_id in members:
                skipped.append(asset_id)
            else:
                session.add(
                    ProjectAsset(project_id=project.id, asset_id=asset_id, role="member", position=0, added_at=stamp)
                )
                members.add(asset_id)
                added.append(asset_id)
        session.commit()
    return added, skipped, failed


def remove_assets(project_id: str, asset_ids: List[str]) -> Tuple[List[str], List[str], List[dict]]:
    """Remove project memberships; returns (removed, skipped, failed).

    Removing an asset that is not a member is a skip, not an error, and the asset
    row and its bytes are untouched - only the join row goes.
    """
    ids = bulk_service.unique_asset_ids(asset_ids)
    removed: List[str] = []
    skipped: List[str] = []
    failed: List[dict] = []
    with Session(engine) as session:
        project = get_project(session, project_id)
        known = set(session.exec(select(Asset.id).where(Asset.id.in_(ids))).all()) if ids else set()
        members = _membership_ids(session, project.id)
        for asset_id in ids:
            if asset_id not in known:
                failed.append(_failure(asset_id))
            elif asset_id not in members:
                skipped.append(asset_id)
            else:
                session.execute(
                    delete(ProjectAsset).where(
                        ProjectAsset.project_id == project.id,
                        ProjectAsset.asset_id == asset_id,
                    )
                )
                members.discard(asset_id)
                removed.append(asset_id)
        session.commit()
    return removed, skipped, failed
