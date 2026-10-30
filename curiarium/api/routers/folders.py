"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import json
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

import audit
import folder_service
import seams
import snapshot_guard
import snapshots
import trash_service
from auth import AuthContext
from db import engine
from models import Asset, Folder
from permissions import require_contribute, require_read, require_write
from routers.presenters import folder_to_out
from schemas import FolderDeletePreviewOut, FolderIn, FolderOut
from zip_service import zip_assets_response

router = APIRouter()


# Folder endpoints ----------------------------------------------


@router.get("/folders", response_model=List[FolderOut])
def list_folders(_: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        rows = list(s.exec(select(Folder)))
    return [folder_to_out(f) for f in rows]


@router.post("/folders", response_model=FolderOut)
def create_folder(body: FolderIn, _: Optional[AuthContext] = Depends(require_contribute)):
    with Session(engine) as s:
        f = folder_service.create_folder(s, body.name, json.dumps(body.tags), body.parent_id)
    return folder_to_out(f)


@router.patch("/folder/{folder_id}", response_model=FolderOut)
def update_folder(
    folder_id: str,
    body: FolderIn,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    with Session(engine) as s:
        f = s.get(Folder, folder_id)
        if not f:
            raise HTTPException(404)
        f = folder_service.move_folder(
            s,
            f,
            body.name,
            json.dumps(body.tags),
            body.parent_id,
            audit_ctx=audit.context_for(request, context),
        )
        result = folder_to_out(f)
    return result


@router.delete("/folder/{folder_id}")
def delete_folder(
    folder_id: str,
    request: Request,
    confirm_name: Optional[str] = Query(None),
    context: Optional[AuthContext] = Depends(require_write),
):
    """Delete a folder's whole directory subtree through the trash.

    ``confirm_name`` is compared by hand and declared optional: a required query
    parameter would make FastAPI answer 422 for a missing name, while the API
    contract is a 400 "you did not confirm this folder".
    """
    with Session(engine) as s:
        folder = s.get(Folder, folder_id)
        if not folder:
            raise HTTPException(404)
        if confirm_name is None or confirm_name != folder.name:
            raise HTTPException(status_code=400, detail="confirm_name must match the folder name exactly")
        if seams.scan_status().get("running"):
            raise HTTPException(status_code=409, detail="A library scan is running; try again when it finishes")
        notice = snapshot_guard.guard(
            snapshots.SnapshotReason.PRE_DELETE, folder_id, ctx=audit.context_for(request, context)
        )
        result = trash_service.trash_folder(s, folder, audit_ctx=audit.context_for(request, context))
    return {"ok": True, **result, "snapshot": notice}


@router.get("/folder/{folder_id}/delete-preview", response_model=FolderDeletePreviewOut)
def folder_delete_preview(folder_id: str, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        folder = s.get(Folder, folder_id)
        if not folder:
            raise HTTPException(404)
        return FolderDeletePreviewOut(
            **trash_service.folder_delete_preview(s, folder),
            snapshot=snapshot_guard.describe(snapshots.SnapshotReason.PRE_DELETE),
        )


@router.get("/folder/{folder_id}/download")
def download_folder(folder_id: str, background: BackgroundTasks, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        folder = s.get(Folder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        assets = list(s.exec(select(Asset).where(Asset.folder_id == folder_id)))
        folder_map = {folder_id: folder.name}
    download_name = f"{(folder.name or 'folder').replace(' ', '_')[:50] or 'folder'}.zip"
    return zip_assets_response(assets, download_name, background, folder_map)
