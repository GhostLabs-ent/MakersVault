"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import json
import os
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

import audit
import bulk_service
import project_service
from asset_service import (
    delete_asset_permanently,
    filename_for_model_name,
    managed_asset_path,
    move_asset_to_folder_by_id,
    raise_asset_conflict,
    rename_asset_in_place,
    restore_moved_file,
    unique_model_name,
)
from auth import AuthContext
from db import engine
from models import Asset, Folder, Project, ProjectAsset
from permissions import require_read, require_write
from routers.asset_helpers import apply_asset_filters, asset_page, require_asset_ids
from routers.presenters import to_out
from schemas import (
    AssetFolderUpdate,
    AssetMetaUpdate,
    AssetOut,
    AssetRename,
    BatchDeleteOut,
    BatchDeleteRequest,
    BatchFolderOut,
    BatchFolderRequest,
    BatchTagsOut,
    BatchTagsRequest,
    DownloadRequest,
    TagUpdate,
)
from zip_service import zip_assets_response

router = APIRouter()


@router.get("/assets", response_model=List[AssetOut])
def list_assets(
    response: Response,
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    not_in_project: bool = Query(default=False, description="Only assets that belong to no project"),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    _: Optional[AuthContext] = Depends(require_read),
):
    with Session(engine) as s:
        stmt = apply_asset_filters(select(Asset), q, tags, folder_id, not_in_project=not_in_project)
        stmt = stmt.order_by(Asset.name, Asset.filename, Asset.id)
        assets = asset_page(s, stmt, response, limit, offset)

    out: List[AssetOut] = [to_out(a) for a in assets]
    return out


@router.get("/tags", response_model=List[str])
def list_tags(
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    project_id: Optional[str] = Query(default=None, description="Only tags on this project's assets"),
    not_in_project: bool = Query(default=False, description="Only tags on assets that belong to no project"),
    _: Optional[AuthContext] = Depends(require_read),
):
    with Session(engine) as s:
        # An unknown project is a 404 here like every other project route, so the
        # chips and the listing fail together instead of silently going empty.
        if project_id:
            project_service.get_project(s, project_id)
        stmt = apply_asset_filters(
            select(Asset.tags_json), q, tags, folder_id, project_id=project_id, not_in_project=not_in_project
        )
        rows = list(s.exec(stmt))

    found: set[str] = set()
    for raw in rows:
        try:
            parsed = json.loads(raw or "[]")
        except Exception:
            continue
        if not isinstance(parsed, list):
            continue
        for tag in parsed:
            if isinstance(tag, str):
                cleaned = tag.strip()
                if cleaned:
                    found.add(cleaned)

    return sorted(found, key=lambda v: v.lower())


@router.post("/download/zip")
def download_zip(body: DownloadRequest, background: BackgroundTasks, _: Optional[AuthContext] = Depends(require_read)):
    if not (body.asset_ids or body.tag or body.folder_id or body.project_id):
        raise HTTPException(status_code=400, detail="Provide asset_ids, tag, folder_id, or project_id to download.")

    project: Optional[Project] = None
    with Session(engine) as s:
        # An unknown project is a whole-request 404, like every other project route.
        if body.project_id:
            project = project_service.get_project(s, body.project_id)
        stmt = select(Asset)
        if body.asset_ids:
            stmt = stmt.where(Asset.id.in_(body.asset_ids))
        if body.folder_id:
            stmt = stmt.where(Asset.folder_id == body.folder_id)
        # Membership is one more AND filter, not a replacement for the others.
        if body.project_id:
            stmt = stmt.where(Asset.id.in_(select(ProjectAsset.asset_id).where(ProjectAsset.project_id == body.project_id)))
        assets = list(s.exec(stmt))
        folder_map = {}
        folder_ids = {a.folder_id for a in assets if a.folder_id}
        if folder_ids:
            for f in s.exec(select(Folder).where(Folder.id.in_(folder_ids))):
                folder_map[f.id] = f.name

    if body.tag:
        tag = body.tag.strip()
        assets = [a for a in assets if tag in json.loads(a.tags_json or "[]")]

    # Precedence: filename < tag < folder_id, and a project name wins over all of
    # them because the project is the surface the caller asked for.
    download_name = body.filename or "makersvault.zip"
    if body.tag:
        safe_tag = body.tag.replace(" ", "_")[:50] or "tag"
        download_name = f"{safe_tag}.zip"
    if body.folder_id and folder_map.get(body.folder_id):
        safe_name = folder_map[body.folder_id].replace(" ", "_")[:50] or "folder"
        download_name = f"{safe_name}.zip"
    if project is not None:
        safe_name = (project.name or "project").replace(" ", "_")[:50] or "project"
        download_name = f"{safe_name}.zip"

    return zip_assets_response(
        assets, download_name, background, folder_map, allow_empty=project is not None, project=project
    )


# Batch endpoints -----------------------------------------------
# One request, one result per id. A failing item is reported in `failed` and the
# rest still apply, so a partial success is a 200; only a request that could
# change nothing at all (no ids, nothing to change, unknown folder) is a 400.
# `require_asset_ids` (routers/asset_helpers.py) raises that 400 for the empty case.


@router.post("/assets/batch/tags", response_model=BatchTagsOut)
def batch_set_tags(
    body: BatchTagsRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    asset_ids = require_asset_ids(body.asset_ids)
    add_tags = [t.strip() for t in body.add_tags if t and t.strip()]
    remove_tags = [t.strip() for t in body.remove_tags if t and t.strip()]
    if not add_tags and not remove_tags:
        raise HTTPException(status_code=400, detail="Provide add_tags or remove_tags")
    updated, failed = bulk_service.update_tags(
        asset_ids, add_tags, remove_tags, audit_ctx=audit.context_for(request, context)
    )
    return BatchTagsOut(updated=[to_out(a) for a in updated], failed=failed)


@router.post("/assets/batch/folder", response_model=BatchFolderOut)
def batch_move_to_folder(
    body: BatchFolderRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    asset_ids = require_asset_ids(body.asset_ids)
    folder_id = body.folder_id or None
    if folder_id:
        # Validate once for the whole request: an unknown target is a bad request,
        # not one failure per asset.
        with Session(engine) as s:
            if not s.get(Folder, folder_id):
                raise HTTPException(status_code=400, detail="Folder not found")
    updated, failed = bulk_service.move_to_folder(
        asset_ids, folder_id, audit_ctx=audit.context_for(request, context)
    )
    return BatchFolderOut(updated=[to_out(a) for a in updated], failed=failed)


@router.post("/assets/batch/delete", response_model=BatchDeleteOut)
def batch_delete_assets(
    body: BatchDeleteRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    asset_ids = require_asset_ids(body.asset_ids)
    deleted, failed = bulk_service.delete_assets(asset_ids, audit_ctx=audit.context_for(request, context))
    return BatchDeleteOut(deleted=deleted, failed=failed)


@router.post("/asset/{asset_id}/tags", response_model=AssetOut)
def set_tags(asset_id: str, body: TagUpdate, _: Optional[AuthContext] = Depends(require_write)):
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        a.tags_json = json.dumps(body.tags)
        s.add(a)
        s.commit()
        s.refresh(a)
        return to_out(a)


@router.post("/asset/{asset_id}/meta", response_model=AssetOut)
def update_asset_meta(
    asset_id: str,
    body: AssetMetaUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        old_path = managed_asset_path(a)
        moved = False
        new_path = old_path
        previous_name = a.name
        requested_name = body.name if body.name is not None else body.title
        if requested_name is not None:
            next_name = unique_model_name(s, requested_name, a.folder_id, exclude_id=a.id)
            if next_name != a.name:
                if not old_path.exists() and a.source_path:
                    raise HTTPException(400, "Renaming is not supported for mounted no-copy files.")
                audit.stage(
                    s,
                    audit.context_for(request, context),
                    audit.Event(audit.ASSET_RENAME, asset_id, {"from": previous_name, "to": next_name}),
                )
                a.name = next_name
                a.title = next_name
                a.filename = filename_for_model_name(next_name, a.filename)
                # A rename only changes the basename; the storage template is never rendered.
                new_path = old_path.parent / a.filename
                moved = rename_asset_in_place(a, old_path, a.filename)
        if body.notes is not None:
            a.notes = body.notes
        if body.creator is not None:
            a.creator = body.creator.strip() or None
        if body.collection is not None:
            a.collection = body.collection.strip() or None
        # Rollback expires the row, so the conflict classifier gets locals.
        conflict_name = a.name
        folder_id = a.folder_id
        new_relative = a.storage_path if moved else None
        s.add(a)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            restore_moved_file(moved, old_path, new_path)
            raise_asset_conflict(conflict_name, folder_id, new_relative, exclude_id=asset_id)
        s.refresh(a)
        return to_out(a)


@router.post("/asset/{asset_id}/rename", response_model=AssetOut)
def rename_asset(
    asset_id: str,
    body: AssetRename,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    new_name = (body.filename or "").strip()
    if not new_name:
        raise HTTPException(400, "Filename cannot be empty")
    if "/" in new_name or "\\" in new_name:
        raise HTTPException(400, "Invalid filename")

    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        old_path = managed_asset_path(a)
        if not old_path.exists():
            if a.source_path:
                raise HTTPException(400, "Renaming is not supported for mounted files.")
            raise HTTPException(404, "File not found on disk")
        proposed_root, _ = os.path.splitext(os.path.basename(new_name))
        model_name = unique_model_name(s, proposed_root or new_name, a.folder_id, exclude_id=a.id)
        new_name_only = filename_for_model_name(model_name, a.filename)
        if new_name_only == a.filename and model_name == a.name:
            return to_out(a)
        previous_name = a.name
        a.name = model_name
        a.title = model_name
        a.filename = new_name_only
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.ASSET_RENAME, asset_id, {"from": previous_name, "to": model_name}),
        )
        moved = rename_asset_in_place(a, old_path, a.filename)
        new_path = old_path.parent / a.filename
        # Rollback expires the row, so the conflict classifier gets locals.
        folder_id = a.folder_id
        new_relative = a.storage_path
        s.add(a)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            restore_moved_file(moved, old_path, new_path)
            raise_asset_conflict(model_name, folder_id, new_relative, exclude_id=asset_id)
        s.refresh(a)
        return to_out(a)


@router.delete("/asset/{asset_id}")
def delete_asset(asset_id: str, request: Request, context: Optional[AuthContext] = Depends(require_write)):
    delete_asset_permanently(asset_id, audit_ctx=audit.context_for(request, context))
    return {"ok": True}


@router.post("/asset/{asset_id}/folder", response_model=AssetOut)
def update_asset_folder(
    asset_id: str,
    body: AssetFolderUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(
        move_asset_to_folder_by_id(asset_id, body.folder_id, audit_ctx=audit.context_for(request, context))
    )
