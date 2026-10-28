"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

import audit
import db
from asset_file_service import (
    PREVIEW_TEXT_MEDIA_TYPE,
    UNPREVIEWABLE_DETAIL,
    delete_prepared_file,
    delete_supporting_file,
    list_supporting_files,
    managed_asset_file_path,
    preview_media_type,
    rename_supporting_file,
    reorder_supporting_files,
    supporting_file_limits,
)
from asset_service import resolve_asset_file, save_thumb_bytes
from auth import AuthContext
from db import engine
from models import Asset, AssetFile
from permissions import require_read, require_write
from routers.presenters import asset_file_to_out, to_out
from schemas import AssetFileLimitsOut, AssetFileOrderUpdate, AssetFileOut, AssetFileRename, AssetOut

router = APIRouter()


@router.get("/file/{asset_id}/{name}")
def get_file(asset_id: str, name: str, _: Optional[AuthContext] = Depends(require_read)):
    media_type: Optional[str] = None
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if a:
            media_type = a.mime
            p = resolve_asset_file(a)
        else:
            p = None

    if not p or not p.exists():
        raise HTTPException(404)

    return FileResponse(
        p,
        media_type=media_type or "application/octet-stream",
        filename=name,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/asset/{asset_id}/files", response_model=List[AssetFileOut])
def get_supporting_files(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as session:
        if not session.get(Asset, asset_id):
            raise HTTPException(404)
    return [asset_file_to_out(row) for row in list_supporting_files(asset_id)]


@router.get("/asset/{asset_id}/files/limits", response_model=AssetFileLimitsOut)
def get_supporting_file_limits(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
    # Declared before `/{file_id}` so "limits" is never read as a file id.
    return supporting_file_limits(asset_id)


@router.put("/asset/{asset_id}/files/order", response_model=List[AssetFileOut])
def reorder_supporting_files_route(
    asset_id: str,
    body: AssetFileOrderUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    rows = reorder_supporting_files(
        asset_id,
        body.file_ids,
        audit_ctx=audit.context_for(request, context),
    )
    return [asset_file_to_out(row) for row in rows]


@router.get("/asset/{asset_id}/files/{file_id}")
def download_supporting_file(
    asset_id: str,
    file_id: str,
    inline: bool = False,
    _: Optional[AuthContext] = Depends(require_read),
):
    with Session(engine) as session:
        record = session.get(AssetFile, file_id)
        if not record or record.asset_id != asset_id or record.role != "supporting":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        mime = record.mime
        filename = record.filename
        preview_type = preview_media_type(record) if inline else None
    if not path.exists():
        raise HTTPException(404)
    if not inline:
        return FileResponse(path, media_type=mime or "application/octet-stream", filename=filename)
    if preview_type is None:
        raise HTTPException(status_code=415, detail=UNPREVIEWABLE_DETAIL)
    # `nosniff` on every inline response; the CSP sandbox is for text only,
    # because it stops Chrome's built-in PDF viewer from rendering at all.
    headers = {"X-Content-Type-Options": "nosniff"}
    if preview_type == PREVIEW_TEXT_MEDIA_TYPE:
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(
        path,
        media_type=preview_type,
        filename=filename,
        content_disposition_type="inline",
        headers=headers,
    )


@router.patch("/asset/{asset_id}/files/{file_id}", response_model=AssetFileOut)
def rename_supporting_file_route(
    asset_id: str,
    file_id: str,
    body: AssetFileRename,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    record = rename_supporting_file(
        asset_id,
        file_id,
        body.filename,
        audit_ctx=audit.context_for(request, context),
    )
    return asset_file_to_out(record)


@router.delete("/asset/{asset_id}/files/{file_id}", response_model=AssetOut)
def remove_supporting_file(
    asset_id: str,
    file_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(delete_supporting_file(asset_id, file_id, audit_ctx=audit.context_for(request, context)))


@router.get("/asset/{asset_id}/prepared-print")
def get_prepared_print(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset or not asset.prepared_file_id:
            raise HTTPException(404)
        record = session.get(AssetFile, asset.prepared_file_id)
        if not record or record.asset_id != asset_id or record.role != "prepared":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        mime = record.mime
        filename = record.filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type=mime or "application/octet-stream", filename=filename)


@router.delete("/asset/{asset_id}/prepared-print", response_model=AssetOut)
def remove_prepared_print(
    asset_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(delete_prepared_file(asset_id, audit_ctx=audit.context_for(request, context)))


@router.get("/thumb/{asset_id}.jpg")
def get_thumb(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
    p = db.THUMBS / f"{asset_id}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(
        p,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.post("/asset/{asset_id}/thumbnail-generated", response_model=AssetOut)
async def save_generated_thumbnail(
    asset_id: str,
    file: UploadFile = File(...),
    _: Optional[AuthContext] = Depends(require_write),
):
    if (file.content_type or "").lower() not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=415, detail="Generated thumbnail must be PNG, JPEG, or WebP")
    data = await file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Generated thumbnail exceeds 8 MB")
    with Session(engine) as s:
        asset = s.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        if not save_thumb_bytes(asset_id, data):
            raise HTTPException(status_code=400, detail="Invalid thumbnail image")
        s.refresh(asset)
        return to_out(asset)
