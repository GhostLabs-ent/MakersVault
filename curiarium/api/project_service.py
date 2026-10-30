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

Imported projects are de-duplicated on `url_utils.source_key` with no stored
canonical column and no migration: the comparison runs over the `project` table
in Python, which `list_projects` already reads in full, so a scan is sound at
household scale and migration 007 stays untouched.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, delete, select

import audit
import bulk_service
import url_utils
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


def require_project(project_id: str) -> str:
    """Prove an explicit project id exists, before anything else writes.

    An import downloads and creates its asset BEFORE it touches the project, so
    an id validated only afterwards would leave that asset orphaned in the
    library behind a 404. This reads the row up front and returns the id.
    """
    with Session(engine) as session:
        return get_project(session, project_id).id


def member_stats(session: Session, project_id: str) -> Tuple[int, int, int]:
    """(member count, summed member size, cover version) of one project, one statement.

    All three numbers are needed by every response that serializes a project,
    so they are fetched together: extra queries for one row is an N+1 with N=1.
    The cover version commutes in the same statement, so a cover thumbnail never
    costs a second round trip.

    The aggregate keeps `select_from(ProjectAsset)` with no group by: it must
    return exactly one row even for a project with no members, which
    `project_with_stats` relies on. The cover version is a scalar subquery, and
    its `Asset` is aliased because the outer query joins `Asset` unaliased - an
    unaliased inner reference would be auto-correlated away and read the wrong
    row.
    """
    cover = aliased(Asset)
    cover_version = (
        select(func.coalesce(cover.thumb_version, 0))
        .select_from(Project)
        .outerjoin(cover, cover.id == Project.cover_asset_id)
        .where(Project.id == project_id)
        .scalar_subquery()
    )
    statement = (
        select(
            func.count(ProjectAsset.asset_id),
            func.coalesce(func.sum(Asset.size), 0),
            cover_version,
        )
        .select_from(ProjectAsset)
        .outerjoin(Asset, Asset.id == ProjectAsset.asset_id)
        .where(ProjectAsset.project_id == project_id)
    )
    count, total_size, cover_thumb_version = session.exec(statement).one()
    return int(count), int(total_size), int(cover_thumb_version)


def create_project(
    session: Session,
    name: str,
    description: Optional[str],
    cover_asset_id: Optional[str],
    creator: Optional[str] = None,
    source_url: Optional[str] = None,
    licence: Optional[str] = None,
    licence_url: Optional[str] = None,
    origin: str = "own",
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
        creator=creator,
        source_url=source_url,
        licence=licence,
        licence_url=licence_url,
        origin=origin,
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
    creator: Optional[str] = None,
    source_url: Optional[str] = None,
    licence: Optional[str] = None,
    licence_url: Optional[str] = None,
    *,
    audit_ctx: Optional[audit.AuditContext],
) -> Project:
    """Apply the fields the patch actually carried, then commit.

    `fields` is the request body's `model_fields_set`: a field that is present and
    None clears its column, a field that is absent is left alone. Only a real
    rename is audited, so a description or provenance PATCH stages no event; the
    provenance columns are an exempt metadata class, like tags.
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
    if "creator" in fields:
        project.creator = creator
    if "source_url" in fields:
        project.source_url = source_url
    if "licence" in fields:
        project.licence = licence
    if "licence_url" in fields:
        project.licence_url = licence_url
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


def list_projects(session: Session) -> List[Tuple[Project, int, int, int]]:
    """Every project with its member count, summed size and cover version, one statement.

    All aggregates come from the same query, so listing N projects costs one
    statement instead of 1 + 3N; the ordering is case-insensitive by name, then
    by id so two projects that differ only in case still page deterministically.
    The cover version is folded in through an aliased outer join - `max` over the
    group is right because it is constant per project, and `coalesce` makes "no
    cover" and "cover with no thumbnail" both 0.
    """
    cover = aliased(Asset)
    statement = (
        select(
            Project,
            func.count(ProjectAsset.asset_id),
            func.coalesce(func.sum(Asset.size), 0),
            func.coalesce(func.max(cover.thumb_version), 0),
        )
        .outerjoin(ProjectAsset, ProjectAsset.project_id == Project.id)
        .outerjoin(Asset, Asset.id == ProjectAsset.asset_id)
        .outerjoin(cover, cover.id == Project.cover_asset_id)
        .group_by(Project.id)
        .order_by(func.lower(Project.name), Project.id)
    )
    return [
        (project, int(count), int(total_size), int(cover_version))
        for project, count, total_size, cover_version in session.exec(statement)
    ]


def find_project_by_source(session: Session, source_url: Optional[str]) -> Optional[Project]:
    """The project whose stored source is the same page, or None.

    De-duplication compares `url_utils.source_key`, not the raw URL, so a renamed
    slug or a tracking parameter still finds the project. `source_key` is total:
    one garbage `source_url` row cannot 500 an unrelated import.
    """
    key = url_utils.source_key(source_url or "")
    if not key:
        return None
    statement = select(Project).order_by(func.lower(Project.name), Project.id)
    for project in session.exec(statement):
        if not (project.source_url or "").strip():
            continue
        if url_utils.source_key(project.source_url) == key:
            return project
    return None


def _fill_empty_provenance(
    project: Project,
    *,
    creator: Optional[str] = None,
    licence: Optional[str] = None,
    licence_url: Optional[str] = None,
    source_url: Optional[str] = None,
) -> bool:
    """Fill only the provenance fields the project left empty; report a change.

    A value the user already put on the project is never overwritten - an import
    adds what the page knows and leaves every existing answer alone.
    """
    changed = False
    values = {
        "creator": creator,
        "licence": licence,
        "licence_url": licence_url,
        "source_url": source_url,
    }
    for field, value in values.items():
        if value and not (getattr(project, field) or "").strip():
            setattr(project, field, value)
            changed = True
    return changed


def _create_import_project(
    session: Session,
    name: str,
    source_url: Optional[str],
    creator: Optional[str],
    licence: Optional[str],
    licence_url: Optional[str],
) -> Project:
    """Create an imported project, suffixing the name past a NOCASE collision.

    `create_project` raises 409 on `idx_project_name_unique`, and by then the
    import has already written its files: a propagated 409 would leave orphaned
    assets behind a failed response. A suffixed name is the honest answer.
    """
    base = _clean_name(name)
    for attempt in range(1, 6):
        candidate = base if attempt == 1 else f"{base} ({attempt})"
        try:
            return create_project(
                session,
                candidate,
                None,
                None,
                creator=creator,
                source_url=source_url,
                licence=licence,
                licence_url=licence_url,
                origin="imported",
            )
        except HTTPException as err:
            if err.status_code != 409:
                raise
    # Five suffixed names collided; a random one cannot, and a 409 here would
    # still orphan the files the import just wrote.
    return create_project(
        session,
        f"{base} ({uuid4().hex[:8]})",
        None,
        None,
        creator=creator,
        source_url=source_url,
        licence=licence,
        licence_url=licence_url,
        origin="imported",
    )


def find_or_create_import_project(
    *,
    project_id: Optional[str],
    suggested_name: str,
    source_url: Optional[str],
    creator: Optional[str] = None,
    licence: Optional[str] = None,
    licence_url: Optional[str] = None,
) -> Tuple[str, bool]:
    """The project an import belongs to: (id, created).

    An explicit `project_id` always wins over a canonical match - the user chose
    the target - and only its empty provenance fields are filled. Otherwise a
    project with the same `source_key` is reused, and the last resort creates an
    `origin="imported"` row.
    """
    with Session(engine) as session:
        if project_id:
            project = get_project(session, project_id)
            if _fill_empty_provenance(
                project, creator=creator, licence=licence, licence_url=licence_url, source_url=source_url
            ):
                session.add(project)
                session.commit()
            return project.id, False
        existing = find_project_by_source(session, source_url)
        if existing is not None:
            if _fill_empty_provenance(
                existing, creator=creator, licence=licence, licence_url=licence_url, source_url=source_url
            ):
                session.add(existing)
                session.commit()
            return existing.id, False
        project = _create_import_project(session, suggested_name, source_url, creator, licence, licence_url)
        return project.id, True


def set_project_metadata_marker(project_id: str, marker: dict) -> None:
    """Merge a reserved `_`-prefixed marker into the project's metadata object.

    The column is parsed here rather than through `routers.presenters`, because a
    service importing a router's presenter would invert the layering. Anything
    that is not a JSON object reads as {}, the same rule the presenter uses, and
    a non-underscore key (real print settings) is never clobbered.
    """
    with Session(engine) as session:
        project = get_project(session, project_id)
        try:
            parsed = json.loads(project.metadata_json or "{}")
        except (TypeError, ValueError):
            parsed = {}
        metadata = parsed if isinstance(parsed, dict) else {}
        for key, value in marker.items():
            if key.startswith("_"):
                metadata[key] = value
        project.metadata_json = json.dumps(metadata)
        project.updated_at = _now()
        session.add(project)
        session.commit()


def project_with_stats(project_id: str) -> Tuple[Project, int, int, int]:
    """One project plus its member count, size and cover version, safe after close.

    This exists so a handler can serialize a project from a session that has
    already been closed: nothing here commits, so no attribute is expired and
    the detached row still has every column it was loaded with. The cover
    version commutes in the same statement as the two aggregates.
    """
    with Session(engine) as session:
        project = get_project(session, project_id)
        asset_count, total_size, cover_thumb_version = member_stats(session, project.id)
    return project, asset_count, total_size, cover_thumb_version


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
