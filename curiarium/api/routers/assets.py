"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import json
import os
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

import audit
import bulk_service
import project_service
import snapshot_guard
import snapshots
import trash_service
from asset_service import (
    filename_for_model_name,
    managed_asset_path,
    model_name_for_rename,
    move_asset_to_folder_by_id,
    raise_asset_conflict,
    rename_asset_in_place,
    restore_moved_file,
    unique_model_name,
)
from auth import AuthContext
from db import engine
from models import Asset, Folder, Project, ProjectAsset
from permissions import authorize_metadata_edit, require_contribute, require_read, require_write
from routers.asset_helpers import apply_asset_filters, apply_asset_order, asset_page, require_asset_ids
from routers.presenters import to_out
from schemas import (
    AssetDeletePreviewOut,
    AssetFolderUpdate,
    AssetMetaUpdate,
    AssetOut,
    AssetRename,
    BatchDeleteOut,
    BatchDeleteRequest,
    BatchFolderOut,
    BatchFolderRequest,
    BatchMetaOut,
    BatchMetaRequest,
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
    creator: Optional[str] = Query(default=None, description="Exact creator, case-insensitive"),
    sort: Optional[Literal["name", "size", "creator"]] = Query(default=None, description="Optional sort key; omitted keeps the default order"),
    order: Literal["asc", "desc"] = Query(default="asc", description="Sort direction"),
    not_in_project: bool = Query(default=False, description="Only assets that belong to no project"),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    _: Optional[AuthContext] = Depends(require_read),
):
    with Session(engine) as s:
        stmt = apply_asset_filters(
            select(Asset), q, tags, folder_id, not_in_project=not_in_project, creator=creator
        )
        stmt = apply_asset_order(stmt, sort, order)
        assets = asset_page(s, stmt, response, limit, offset)

    out: List[AssetOut] = [to_out(a) for a in assets]
    return out


@router.get("/assets/delete-preview", response_model=AssetDeletePreviewOut)
def asset_delete_preview(
    asset_ids: List[str] = Query(default=[], description="Assets to describe"),
    _: Optional[AuthContext] = Depends(require_read),
):
    """What a bulk delete would remove, and what it would do about a snapshot.

    Pure SELECT: the counts mirror what the delete dialog displays (a mounted
    reference contributes no files and no bytes, because deleting its row never
    touches those bytes), and `snapshot` is the pure preview of the guard's
    decision.
    """
    ids = require_asset_ids(asset_ids)
    with Session(engine) as s:
        assets = list(s.exec(select(Asset).where(Asset.id.in_(ids))))
    return AssetDeletePreviewOut(
        assets=len(assets),
        files=sum(0 if asset.is_reference else 1 + (asset.supporting_file_count or 0) for asset in assets),
        bytes=sum(0 if asset.is_reference else (asset.size or 0) for asset in assets),
        snapshot=snapshot_guard.describe(snapshots.SnapshotReason.PRE_BULK),
    )


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


@router.get("/creators", response_model=List[str])
def list_creators(
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    project_id: Optional[str] = Query(default=None, description="Only creators on this project's assets"),
    not_in_project: bool = Query(default=False, description="Only creators on assets that belong to no project"),
    _: Optional[AuthContext] = Depends(require_read),
):
    """Distinct non-empty creators, deduped and sorted case-insensitively.

    Takes the same scoping filters as `GET /assets` and `GET /tags`, so the
    facet works in library mode, folder mode and project mode. An unknown
    project is a 404 like every other project route.
    """
    with Session(engine) as s:
        if project_id:
            project_service.get_project(s, project_id)
        stmt = apply_asset_filters(
            select(Asset.creator), q, tags, folder_id, project_id=project_id, not_in_project=not_in_project
        )
        rows = list(s.exec(stmt))

    # Dedupe on casefold and keep the lexicographically smallest spelling, so
    # the choice between "Ada" and "ada" does not depend on row order.
    found: dict[str, str] = {}
    for raw in rows:
        cleaned = (raw or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        found[key] = min(found[key], cleaned) if key in found else cleaned

    return sorted(found.values(), key=lambda v: v.casefold())


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
    download_name = body.filename or "curiarium.zip"
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
    context: Optional[AuthContext] = Depends(require_contribute),
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


@router.post("/assets/batch/meta", response_model=BatchMetaOut)
def batch_update_meta(
    body: BatchMetaRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_contribute),
):
    """Set creator/notes on every id, with the batch partial-success contract.

    Deliberate divergence from `POST /asset/{asset_id}/meta`: there an explicit
    ``null`` means "unchanged", while here it clears, because a batch has no
    per-asset typed value that `null` could disambiguate. Blank strings clear in
    both places. There is no title/name field: title is a rename alias and a
    batch rename would move files on disk.

    Creator and notes are the audit-exempt metadata class, so no event is
    staged; rename and move are the audited asset edits (see
    `bulk_service.update_meta`).
    """
    asset_ids = require_asset_ids(body.asset_ids)
    changes = {field: getattr(body, field) for field in ("creator", "notes") if field in body.model_fields_set}
    if not changes:
        raise HTTPException(status_code=400, detail="Provide creator or notes")
    updated, failed = bulk_service.update_meta(asset_ids, changes, audit_ctx=audit.context_for(request, context))
    return BatchMetaOut(updated=[to_out(a) for a in updated], failed=failed)


@router.post("/assets/batch/delete", response_model=BatchDeleteOut)
def batch_delete_assets(
    body: BatchDeleteRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    """Delete each asset through the trash, reporting one result per id.

    ``confirm_count`` is compared by hand and declared optional, like the
    single-item name gate: a required field would answer 422 for a missing
    value, while the contract is a 400 "you did not confirm this selection".
    The confirmation is a count rather than one name per id because typing N
    filenames is absurd for a batch, while a count still proves the client is
    deleting exactly the rows it displayed.
    """
    asset_ids = require_asset_ids(body.asset_ids)
    if body.confirm_count is None or body.confirm_count != len(asset_ids):
        raise HTTPException(status_code=400, detail="confirm_count must equal the number of assets to delete")
    snapshot_guard.guard(
        snapshots.SnapshotReason.PRE_BULK, "assets", ctx=audit.context_for(request, context)
    )
    deleted, failed = bulk_service.delete_assets(asset_ids, audit_ctx=audit.context_for(request, context))
    return BatchDeleteOut(deleted=deleted, failed=failed)


@router.post("/asset/{asset_id}/tags", response_model=AssetOut)
def set_tags(asset_id: str, body: TagUpdate, _: Optional[AuthContext] = Depends(require_contribute)):
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
    context: Optional[AuthContext] = Depends(require_contribute),
):
    # Edits notes/creator/collection, or renames when `name`/`title` is present.
    # The route declares CONTRIBUTE, so a rename field escalates to WRITE here
    # through `authorize_metadata_edit`, before the 404 lookup. Deliberately a
    # comment and not a docstring: a handler docstring is served as the OpenAPI
    # description, and this ticket does not move the checked-in contract.
    authorize_metadata_edit(request, context, body.model_fields_set)
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
            # The metadata editor is the UI's rename path, so a typed filename
            # suffix matching this asset's extension is stripped before the
            # unique-name check: "widget.stl" stays "widget.stl".
            next_name = unique_model_name(
                s, model_name_for_rename(requested_name, a.filename), a.folder_id, exclude_id=a.id
            )
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
        # Field membership, not the value: the validators normalise a blank to
        # None, so only "present" can distinguish a clear from an absent key
        # (an explicit null was dropped before validation).
        if "notes" in body.model_fields_set:
            a.notes = body.notes
        if "creator" in body.model_fields_set:
            a.creator = body.creator
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
        # This route takes a filename, so it splits exactly one extension. The
        # metadata editor takes a model name and uses model_name_for_rename
        # instead, which strips only an extension matching the stored file.
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
def delete_asset(
    asset_id: str,
    request: Request,
    confirm_name: Optional[str] = Query(None),
    context: Optional[AuthContext] = Depends(require_write),
):
    """Delete one asset through the trash.

    ``confirm_name`` is compared by hand and declared optional: a required query
    parameter would make FastAPI answer 422 for a missing name, while the API
    contract is a 400 "you did not confirm this asset".

    The gate compares ``filename``, not ``asset.name``: ``Asset.name`` defaults
    to ``""``, so a name gate would degenerate into a no-op for any row that was
    never renamed, and the filename is what the card actually shows.
    """
    with Session(engine) as s:
        asset = s.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        if confirm_name is None or confirm_name != asset.filename:
            raise HTTPException(status_code=400, detail="confirm_name must match the asset filename exactly")
        result = trash_service.trash_asset(s, asset, audit_ctx=audit.context_for(request, context))
    return {"ok": True, **result}


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
