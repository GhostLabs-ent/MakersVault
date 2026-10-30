"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel import Session, select

import audit
import project_service
from auth import AuthContext
from db import engine
from models import Asset, ProjectAsset
from permissions import require_contribute, require_read, require_write
from routers.asset_helpers import apply_asset_filters, apply_asset_order, asset_page, require_asset_ids
from routers.presenters import project_to_out, to_out
from schemas import (
    AssetOut,
    ProjectAssetsRequest,
    ProjectIn,
    ProjectMembersOut,
    ProjectOut,
    ProjectRemovalOut,
    ProjectUpdate,
)

router = APIRouter()


# Project endpoints ---------------------------------------------
# A project is a row and a join table: it owns no storage path and no bytes, so
# no route here creates, moves or deletes a file. The templates are deliberately
# asymmetric (`/projects` for the collection, `/project/{project_id}` for one),
# matching `/folders` vs `/folder/{folder_id}`.


@router.get("/projects", response_model=List[ProjectOut])
def list_projects(_: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        rows = project_service.list_projects(s)
    projects = []
    for project, count, total_size, cover_thumb_version in rows:
        projects.append(project_to_out(project, count, total_size, cover_thumb_version))
    return projects


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, _: Optional[AuthContext] = Depends(require_contribute)):
    with Session(engine) as s:
        project = project_service.create_project(
            s,
            body.name,
            body.description,
            body.cover_asset_id,
            creator=body.creator,
            source_url=body.source_url,
            licence=body.licence,
            licence_url=body.licence_url,
            origin=body.origin,
        )
        asset_count, total_size, cover_thumb_version = project_service.member_stats(s, project.id)
    return project_to_out(project, asset_count, total_size, cover_thumb_version)


@router.patch("/project/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_contribute),
):
    with Session(engine) as s:
        project = project_service.update_project(
            s,
            project_service.get_project(s, project_id),
            body.model_fields_set,
            body.name,
            body.description,
            body.cover_asset_id,
            body.creator,
            body.source_url,
            body.licence,
            body.licence_url,
            audit_ctx=audit.context_for(request, context),
        )
        asset_count, total_size, cover_thumb_version = project_service.member_stats(s, project.id)
        result = project_to_out(project, asset_count, total_size, cover_thumb_version)
    return result


@router.delete("/project/{project_id}")
def delete_project(project_id: str, request: Request, context: Optional[AuthContext] = Depends(require_write)):
    with Session(engine) as s:
        project_service.delete_project(
            s,
            project_service.get_project(s, project_id),
            audit_ctx=audit.context_for(request, context),
        )
    return {"ok": True}


@router.get("/project/{project_id}/assets", response_model=List[AssetOut])
def list_project_assets(
    project_id: str,
    response: Response,
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    creator: Optional[str] = Query(default=None, description="Exact creator, case-insensitive"),
    sort: Optional[Literal["name", "size", "creator"]] = Query(default=None, description="Optional sort key; omitted keeps the default order"),
    order: Literal["asc", "desc"] = Query(default="asc", description="Sort direction"),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    _: Optional[AuthContext] = Depends(require_read),
):
    """The project's members, filtered, ordered and paged like `GET /assets`.

    `folder_id` is not a parameter here on purpose: membership, not location,
    decides what is listed.
    """
    with Session(engine) as s:
        project_service.get_project(s, project_id)
        stmt = select(Asset).join(ProjectAsset, ProjectAsset.asset_id == Asset.id).where(ProjectAsset.project_id == project_id)
        stmt = apply_asset_filters(stmt, q, tags, None, creator=creator)
        stmt = apply_asset_order(stmt, sort, order)
        assets = asset_page(s, stmt, response, limit, offset)
    return [to_out(a) for a in assets]


@router.post("/project/{project_id}/assets", response_model=ProjectMembersOut)
def add_project_assets(
    project_id: str,
    body: ProjectAssetsRequest,
    _: Optional[AuthContext] = Depends(require_contribute),
):
    """Add memberships; unknown asset ids are reported per id (200 partial)."""
    asset_ids = require_asset_ids(body.asset_ids)
    added, skipped, failed = project_service.add_assets(project_id, asset_ids)
    return ProjectMembersOut(added=added, skipped=skipped, failed=failed)


@router.delete("/project/{project_id}/assets", response_model=ProjectRemovalOut)
def remove_project_assets(
    project_id: str,
    body: ProjectAssetsRequest,
    _: Optional[AuthContext] = Depends(require_contribute),
):
    """Remove memberships; assets and files are never touched.

    This is the one DELETE route in the API that carries a JSON body, so a client
    must send it explicitly - `client.request("DELETE", path, json=...)` - because
    some convenience helpers drop a body on DELETE.
    """
    asset_ids = require_asset_ids(body.asset_ids)
    removed, skipped, failed = project_service.remove_assets(project_id, asset_ids)
    return ProjectRemovalOut(removed=removed, skipped=skipped, failed=failed)
