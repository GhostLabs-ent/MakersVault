"""Split from main.py in Mf-x9dx; behaviour-preserving move.

Both streaming uploads live here on purpose: the direct upload and the
supporting-file upload share the staging-directory and exception contract. The
generated-thumbnail route in ``routers.asset_files`` streams through the same
module and shares that contract as well.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session, delete
from starlette.requests import ClientDisconnect

import asset_service
import db
import multipart_stream
import seams
from asset_file_service import save_asset_file, size_limit_label
from asset_service import (
    create_asset_record,
    ensure_model_thumbnail,
    finalize_asset_record,
    managed_asset_path,
    move_managed_file,
    save_thumb,
)
from auth import AuthContext
from db import engine
from file_utils import sanitize_filename
from models import Asset, AssetFile
from permissions import require_contribute
from routers.presenters import to_out
from schemas import AssetOut

router = APIRouter()


# nginx's "client closed request": the upload was aborted, so there is nobody
# left to read a body.
CLIENT_CLOSED_REQUEST = 499


def delete_asset_row_only(asset_id: str) -> None:
    """Drop the row an upload created without touching any bytes on disk.

    ``cleanup_asset`` unlinks ``managed_asset_path(row)``, which is exactly the
    wrong move when a no-clobber move found a foreign file already at that path.
    Migration 007 enforces foreign keys, so the dependent ``AssetFile`` rows are
    deleted first, with the asset row, in the same transaction; their stored
    bytes are deliberately left alone because the foreign file at the managed
    path is not ours to remove.
    """
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if asset:
            session.exec(delete(AssetFile).where(AssetFile.asset_id == asset_id))
            session.delete(asset)
            session.commit()
    try:
        (db.THUMBS / f"{asset_id}.jpg").unlink(missing_ok=True)
    except OSError:
        pass


def upload_too_large_detail(limit: int) -> str:
    return f"Upload exceeds the {size_limit_label(limit)} limit"


def supporting_file_too_large_detail(limit: int) -> str:
    return f"Supporting file exceeds the {size_limit_label(limit)} limit"


def multipart_form_openapi(*text_fields: str) -> dict:
    """Describe a streamed multipart body, which FastAPI no longer derives itself."""
    properties = {"file": {"type": "string", "format": "binary"}}
    for name in text_fields:
        properties[name] = {"type": "string"}
    return {"requestBody": {"content": {"multipart/form-data": {"schema": {
        "type": "object",
        "required": ["file"],
        "properties": properties,
    }}}}}


@router.post("/upload", response_model=AssetOut, openapi_extra=multipart_form_openapi("title", "notes", "tags", "folder_id"))
async def upload(request: Request, _: Optional[AuthContext] = Depends(require_contribute)):
    staging = asset_service.new_staging_path()
    asset: Optional[Asset] = None
    try:
        staged = await multipart_stream.stream_file_part(request, staging, max_bytes=seams.max_upload_bytes())
        safe_name = sanitize_filename(staged.filename)
        tags = [t.strip() for t in (staged.fields.get("tags") or "").split(",") if t.strip()]
        asset = create_asset_record(
            safe_name,
            staged.content_type or "application/octet-stream",
            staged.fields.get("title"),
            staged.fields.get("notes"),
            tags,
            staged.fields.get("folder_id"),
        )
        dest = managed_asset_path(asset)
        dest.parent.mkdir(parents=True, exist_ok=True)
        move_managed_file(staging, dest)
    except multipart_stream.UploadTooLarge:
        raise HTTPException(status_code=413, detail=upload_too_large_detail(seams.max_upload_bytes())) from None
    except multipart_stream.UploadRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except ClientDisconnect:
        return Response(status_code=CLIENT_CLOSED_REQUEST)
    except HTTPException:
        # A move rejected with 409 found foreign bytes at the destination; the
        # row we created goes, the bytes stay.
        if asset:
            delete_asset_row_only(asset.id)
        raise
    except Exception as exc:
        if asset:
            delete_asset_row_only(asset.id)
        raise HTTPException(status_code=500, detail="Failed to store uploaded file") from exc
    finally:
        staging.unlink(missing_ok=True)

    # make a thumbnail for common image formats (best effort: a thumbnail
    # failure must not discard a file that is already safely on disk)
    try:
        if (asset.mime or "").lower().startswith("image/") and dest.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            save_thumb(asset.id, dest)
        elif dest.suffix.lower() == ".3mf":
            ensure_model_thumbnail(asset.id, dest)
    except Exception:
        pass

    asset = finalize_asset_record(asset.id, staged.size, asset.mime) or asset

    return to_out(asset)


@router.post("/asset/{asset_id}/files", response_model=AssetOut, openapi_extra=multipart_form_openapi())
async def upload_related_file(
    asset_id: str,
    request: Request,
    _: Optional[AuthContext] = Depends(require_contribute),
):
    staging = asset_service.new_staging_path()
    limit = seams.asset_file_upload_max_bytes()
    try:
        staged = await multipart_stream.stream_file_part(request, staging, max_bytes=limit)
        asset = await save_asset_file(asset_id, staged)
        return to_out(asset)
    except multipart_stream.UploadTooLarge:
        raise HTTPException(status_code=413, detail=supporting_file_too_large_detail(limit)) from None
    except multipart_stream.UploadRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except ClientDisconnect:
        return Response(status_code=CLIENT_CLOSED_REQUEST)
    finally:
        staging.unlink(missing_ok=True)
