import json
import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote, urlparse
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from jwt import PyJWTError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect

import asset_service
import bulk_service
import folder_service
import login_throttle as login_throttle_module
import multipart_stream
import trash_service
from asset_file_service import (
    backfill_prepared_print_metadata,
    delete_prepared_file,
    delete_supporting_file,
    list_supporting_files,
    managed_asset_file_path,
    save_asset_file,
)
from asset_service import (
    STORAGE_TEMPLATE_TOKENS,
    backfill_embedded_thumbnails,
    create_asset_record,
    delete_asset_permanently,
    ensure_model_thumbnail,
    filename_for_model_name,
    finalize_asset_record,
    managed_asset_path,
    move_asset_to_folder_by_id,
    move_managed_file,
    raise_asset_conflict,
    rename_asset_in_place,
    restore_moved_file,
    sample_storage_path,
    save_thumb,
    save_thumb_bytes,
    unique_model_name,
    validate_storage_template,
)
from auth import (
    AUTH_ALGO,
    AUTH_ENABLED,
    AUTH_SECRET,
    AUTH_TOKEN_TTL,
    create_token,
    credentials_match,
    require_auth,
    validate_auth_configuration,
)
from config import IMPORT_MAX_BYTES, MAX_UPLOAD_BYTES, MOUNT_IMPORT_COPY, MOUNT_IMPORT_ENABLED, MOUNT_IMPORT_PATH
from db import THUMBS, engine
from file_utils import (
    build_import_filename,
    mime_from_content_type,
    sanitize_filename,
    sanitize_path_segment,
)
from import_service import download_import_to_temp, import_asset_from_url, open_import_response
from library_scan import scan_status, start_scan
from migrations import run_migrations
from models import Asset, AssetFile, Folder
from mount_import import mount_import_should_run, scan_mount_imports
from prepared_print import prepared_filename
from schemas import (
    AssetFileOut,
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
    FolderDeletePreviewOut,
    FolderIn,
    FolderOut,
    ImportInspectOut,
    ImportRequest,
    ImportZipEntriesOut,
    ImportZipEntriesRequest,
    ImportZipExtractRequest,
    ImportZipResult,
    LibraryScanStatusOut,
    LoginRequest,
    LoginResponse,
    MountImportSettings,
    MountImportSettingsOut,
    StorageSettings,
    StorageSettingsOut,
    TagUpdate,
    TrashEntryOut,
    TrashListOut,
    TrashPurgeOut,
)
from settings_service import (
    DEFAULT_STORAGE_TEMPLATE,
    get_mount_import_copy,
    get_mount_import_enabled,
    get_storage_template,
    set_mount_import_copy,
    set_mount_import_enabled,
    set_storage_template,
)
from url_utils import normalize_import_url
from zip_service import extract_zip_entries_to_assets, list_zip_entries

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    login_throttle_module.limiter.reset()
    run_migrations(engine)
    # Runs before the server accepts connections, so a single-process deployment
    # cannot have an in-flight upload for the sweep to race.
    asset_service.sweep_staging_dir()
    threading.Thread(target=backfill_embedded_thumbnails, daemon=True).start()
    threading.Thread(target=backfill_prepared_print_metadata, daemon=True).start()
    if mount_import_should_run():
        threading.Thread(target=scan_mount_imports, daemon=True).start()
    yield


app = FastAPI(title="MakerVault API", lifespan=lifespan)


def normalize_origin(raw: str) -> Optional[str]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def resolve_cors_origins() -> str:
    raw = os.getenv("CORS_ORIGINS")
    if raw:
        return raw
    candidates: List[str] = []
    for name in ("PUBLIC_URL", "VITE_API_URL"):
        origin = normalize_origin(os.getenv(name, ""))
        if origin:
            candidates.append(origin)
    if candidates:
        # Preserve order, remove duplicates.
        return ",".join(dict.fromkeys(candidates))
    return "http://localhost:5173"


origins_env = resolve_cors_origins()
origins = [o.strip() for o in origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Has-More", "X-Next-Offset"],
)


# Utilities ------------------------------------------------------

def is_mount_source_allowed(path: Path) -> bool:
    if not MOUNT_IMPORT_PATH:
        return False
    try:
        root = Path(MOUNT_IMPORT_PATH).resolve()
        candidate = path.resolve()
    except Exception:
        return False
    return candidate == root or root in candidate.parents


def resolve_asset_file(asset: Asset) -> Optional[Path]:
    p = managed_asset_path(asset)
    if p.exists():
        return p
    if asset.source_path:
        source = Path(asset.source_path)
        if source.exists() and is_mount_source_allowed(source):
            return source
    return None


def folder_to_out(f: Folder) -> "FolderOut":
    return FolderOut(
        id=f.id,
        name=f.name,
        tags=json.loads(f.tags_json or "[]"),
        parent_id=f.parent_id,
        storage_path=f.storage_path,
    )


def to_out(a: Asset) -> AssetOut:
    tags = json.loads(a.tags_json or "[]")
    safe_filename = quote(a.filename or "", safe="")
    try:
        prepared = json.loads(a.prepared_metadata_json) if a.prepared_metadata_json else None
    except (TypeError, ValueError):
        prepared = None
    if prepared:
        prepared["removable"] = bool(a.prepared_file_id)
    primary_url = f"/file/{a.id}/{safe_filename}"
    slicer_url = f"/asset/{a.id}/prepared-print" if a.prepared_file_id else primary_url
    return AssetOut(
        id=a.id,
        name=a.name or Path(a.filename).stem,
        filename=a.filename,
        mime=a.mime,
        size=a.size,
        title=a.title,
        notes=a.notes,
        creator=a.creator,
        collection=a.collection,
        tags=tags,
        url=primary_url,
        thumb_url=(
            f"/thumb/{a.id}.jpg?v={(THUMBS / f'{a.id}.jpg').stat().st_mtime_ns}"
            if (THUMBS / f"{a.id}.jpg").exists()
            else None
        ),
        folder_id=a.folder_id,
        storage_path=a.storage_path,
        missing_since=a.missing_since,
        supporting_file_count=int(a.supporting_file_count or 0),
        prepared_print=prepared,
        slicer_url=slicer_url,
        slicer_filename=(prepared_filename(a.name, prepared) if a.prepared_file_id else a.filename),
    )


def asset_file_to_out(asset_file: AssetFile) -> AssetFileOut:
    return AssetFileOut(
        id=asset_file.id,
        filename=asset_file.filename,
        mime=asset_file.mime,
        size=asset_file.size,
        url=f"/asset/{asset_file.asset_id}/files/{asset_file.id}",
    )


def arcname_for_asset(asset: Asset, folder_label_map: Optional[dict] = None) -> str:
    folder_part = "unassigned"
    if asset.folder_id:
        folder_part = (folder_label_map or {}).get(asset.folder_id, asset.folder_id)
    # folder labels are user input: an unsanitised "../.." here becomes a
    # traversal entry for whoever extracts the downloaded zip
    return f"{sanitize_path_segment(folder_part, 'unassigned')}/{sanitize_path_segment(asset.filename, 'file')}"


def zip_assets_response(assets: List[Asset], download_name: str, background: BackgroundTasks, folder_label_map: Optional[dict] = None):
    files: List[tuple[str, Path]] = []
    supporting: dict[str, List[AssetFile]] = {}
    asset_ids = [asset.id for asset in assets]
    if asset_ids:
        with Session(engine) as session:
            for row in session.exec(
                select(AssetFile).where(AssetFile.asset_id.in_(asset_ids), AssetFile.role == "supporting")
            ):
                supporting.setdefault(row.asset_id, []).append(row)
    for a in assets:
        path = resolve_asset_file(a)
        if not path:
            continue
        files.append((arcname_for_asset(a, folder_label_map), path))
        folder_part = "unassigned"
        if a.folder_id:
            folder_part = (folder_label_map or {}).get(a.folder_id, a.folder_id)
        for related in supporting.get(a.id, []):
            related_path = managed_asset_file_path(related)
            if related_path.exists():
                files.append((
                    f"{sanitize_path_segment(folder_part, 'unassigned')}/"
                    f"{sanitize_path_segment(a.name, 'model')}/supporting/"
                    f"{sanitize_path_segment(related.filename, 'file')}",
                    related_path,
                ))
    if not files:
        raise HTTPException(status_code=404, detail="No files available for download")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()
    with ZipFile(tmp_path, "w", ZIP_DEFLATED) as zf:
        for arc, fs_path in files:
            zf.write(fs_path, arcname=arc)

    background.add_task(lambda p=tmp_path: p.unlink(missing_ok=True))
    return FileResponse(tmp_path, media_type="application/zip", filename=download_name)


# Routes ---------------------------------------------------------


@app.get("/health")
def health():
    return {"ok": True, "auth_required": AUTH_ENABLED}


@app.get("/settings/mount-import", response_model=MountImportSettingsOut)
def get_mount_import_settings(_: Optional[str] = Depends(require_auth)):
    return MountImportSettingsOut(
        enabled=get_mount_import_enabled(MOUNT_IMPORT_ENABLED),
        copy_files=get_mount_import_copy(MOUNT_IMPORT_COPY),
        path=MOUNT_IMPORT_PATH or None,
    )


@app.post("/settings/mount-import", response_model=MountImportSettingsOut)
def update_mount_import_settings(body: MountImportSettings, _: Optional[str] = Depends(require_auth)):
    set_mount_import_enabled(body.enabled)
    set_mount_import_copy(body.copy_files)
    return MountImportSettingsOut(
        enabled=get_mount_import_enabled(MOUNT_IMPORT_ENABLED),
        copy_files=get_mount_import_copy(MOUNT_IMPORT_COPY),
        path=MOUNT_IMPORT_PATH or None,
    )


def storage_settings_out(template: str, moved: int = 0, skipped: int = 0) -> StorageSettingsOut:
    return StorageSettingsOut(
        template=template,
        default_template=DEFAULT_STORAGE_TEMPLATE,
        allowed_tokens=list(STORAGE_TEMPLATE_TOKENS),
        sample_path=sample_storage_path(template),
        moved=moved,
        skipped=skipped,
    )


@app.get("/settings/storage", response_model=StorageSettingsOut)
def get_storage_settings(_: Optional[str] = Depends(require_auth)):
    template = validate_storage_template(get_storage_template())
    return storage_settings_out(template)


@app.post("/settings/storage", response_model=StorageSettingsOut)
def update_storage_settings(body: StorageSettings, _: Optional[str] = Depends(require_auth)):
    template = validate_storage_template(body.template)
    # The template governs new uploads and imports only; existing files never move.
    set_storage_template(template)
    return storage_settings_out(template)


@app.get("/library/scan", response_model=LibraryScanStatusOut)
def library_scan_status(_: Optional[str] = Depends(require_auth)):
    return scan_status()


@app.post("/library/scan", response_model=LibraryScanStatusOut, status_code=202)
def library_scan_start(_: Optional[str] = Depends(require_auth)):
    if not start_scan():
        raise HTTPException(status_code=409, detail="A library scan is already running")
    return scan_status()


@app.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    if not AUTH_ENABLED:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server")
    client_host = request.client.host if request.client else "unknown"
    username = login_throttle_module.normalize_username(body.username)
    retry_after = login_throttle_module.limiter.retry_after(username)
    if retry_after:
        log.warning("Login throttled for username %r from %s (retry after %ss)", username, client_host, retry_after)
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    if not credentials_match(body.username, body.password):
        lockout_seconds = login_throttle_module.limiter.record_failure(username)
        log.warning("Failed login attempt for username %r from %s", username, client_host)
        if lockout_seconds:
            log.warning("Login throttled for username %r from %s (retry after %ss)", username, client_host, lockout_seconds)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    login_throttle_module.limiter.record_success(username)
    token = create_token(body.username)
    return LoginResponse(token=token, expires_in=AUTH_TOKEN_TTL)


@app.post("/refresh", response_model=LoginResponse)
def refresh_token(token: Optional[str] = Depends(require_auth)):
    if not AUTH_ENABLED:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[AUTH_ALGO])
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    new_token = create_token(username)
    return LoginResponse(token=new_token, expires_in=AUTH_TOKEN_TTL)


# nginx's "client closed request": the upload was aborted, so there is nobody
# left to read a body.
CLIENT_CLOSED_REQUEST = 499


def delete_asset_row_only(asset_id: str) -> None:
    """Drop the row an upload created without touching any bytes on disk.

    ``cleanup_asset`` unlinks ``managed_asset_path(row)``, which is exactly the
    wrong move when a no-clobber move found a foreign file already at that path.
    """
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if asset:
            session.delete(asset)
            session.commit()
    try:
        (THUMBS / f"{asset_id}.jpg").unlink(missing_ok=True)
    except OSError:
        pass


def upload_too_large_detail(limit: int) -> str:
    if limit >= 1024 * 1024:
        return f"Upload exceeds the {limit // (1024 * 1024)} MB limit"
    return f"Upload exceeds the {limit} byte limit"


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


@app.post("/upload", response_model=AssetOut, openapi_extra=multipart_form_openapi("title", "notes", "tags", "folder_id"))
async def upload(request: Request, _: Optional[str] = Depends(require_auth)):
    staging = asset_service.new_staging_path()
    asset: Optional[Asset] = None
    try:
        staged = await multipart_stream.stream_file_part(request, staging, max_bytes=MAX_UPLOAD_BYTES)
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
        raise HTTPException(status_code=413, detail=upload_too_large_detail(MAX_UPLOAD_BYTES)) from None
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


@app.post("/import", response_model=AssetOut)
def import_from_link(body: ImportRequest, _: Optional[str] = Depends(require_auth)):
    url = normalize_import_url(body.url)
    asset = import_asset_from_url(url, body)
    return to_out(asset)


@app.post("/import/inspect", response_model=ImportInspectOut)
def inspect_import_link(body: ImportRequest, _: Optional[str] = Depends(require_auth)):
    url = normalize_import_url(body.url)
    resp, final_url = open_import_response(url, body)
    with resp:
        filename = build_import_filename(final_url, resp.headers, body.filename)
        mime = mime_from_content_type(resp.headers.get("Content-Type", ""), filename)
    is_zip = Path(filename).suffix.lower() == ".zip"
    return ImportInspectOut(filename=filename, mime=mime, is_zip=is_zip)


@app.post("/import/zip/entries", response_model=ImportZipEntriesOut)
def list_import_zip_entries(body: ImportZipEntriesRequest, _: Optional[str] = Depends(require_auth)):
    url = normalize_import_url(body.url)
    tmp_path, filename, _ = download_import_to_temp(url, body)
    try:
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=415, detail="Imported file is not a zip")
        try:
            entries = list_zip_entries(tmp_path)
        except BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file") from None
        if not entries:
            raise HTTPException(status_code=400, detail="No files found in zip")
        return ImportZipEntriesOut(filename=filename, entries=entries)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/import/zip", response_model=ImportZipResult)
def import_zip_entries(body: ImportZipExtractRequest, _: Optional[str] = Depends(require_auth)):
    url = normalize_import_url(body.url)
    tmp_path, filename, _ = download_import_to_temp(url, body)
    try:
        if Path(filename).suffix.lower() != ".zip":
            raise HTTPException(status_code=415, detail="Imported file is not a zip")
        try:
            assets, failed = extract_zip_entries_to_assets(tmp_path, body.entries, body)
        except BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file") from None
        return ImportZipResult(assets=[to_out(asset) for asset in assets], failed=failed)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/file/{asset_id}/{name}")
def get_file(asset_id: str, name: str, _: Optional[str] = Depends(require_auth)):
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


@app.get("/asset/{asset_id}/files", response_model=List[AssetFileOut])
def get_supporting_files(asset_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        if not session.get(Asset, asset_id):
            raise HTTPException(404)
    return [asset_file_to_out(row) for row in list_supporting_files(asset_id)]


@app.post("/asset/{asset_id}/files", response_model=AssetOut, openapi_extra=multipart_form_openapi())
async def upload_related_file(
    asset_id: str,
    request: Request,
    _: Optional[str] = Depends(require_auth),
):
    staging = asset_service.new_staging_path()
    try:
        staged = await multipart_stream.stream_file_part(request, staging, max_bytes=IMPORT_MAX_BYTES)
        asset = await save_asset_file(asset_id, staged)
        return to_out(asset)
    except multipart_stream.UploadTooLarge:
        raise HTTPException(status_code=413, detail="Related file exceeds size limit") from None
    except multipart_stream.UploadRequestError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    except ClientDisconnect:
        return Response(status_code=CLIENT_CLOSED_REQUEST)
    finally:
        staging.unlink(missing_ok=True)


@app.get("/asset/{asset_id}/files/{file_id}")
def download_supporting_file(asset_id: str, file_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        record = session.get(AssetFile, file_id)
        if not record or record.asset_id != asset_id or record.role != "supporting":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        mime = record.mime
        filename = record.filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type=mime or "application/octet-stream", filename=filename)


@app.delete("/asset/{asset_id}/files/{file_id}", response_model=AssetOut)
def remove_supporting_file(asset_id: str, file_id: str, _: Optional[str] = Depends(require_auth)):
    return to_out(delete_supporting_file(asset_id, file_id))


@app.get("/asset/{asset_id}/prepared-print")
def get_prepared_print(asset_id: str, _: Optional[str] = Depends(require_auth)):
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


@app.delete("/asset/{asset_id}/prepared-print", response_model=AssetOut)
def remove_prepared_print(asset_id: str, _: Optional[str] = Depends(require_auth)):
    return to_out(delete_prepared_file(asset_id))


@app.get("/thumb/{asset_id}.jpg")
def get_thumb(asset_id: str, _: Optional[str] = Depends(require_auth)):
    p = THUMBS / f"{asset_id}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(
        p,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@app.post("/asset/{asset_id}/thumbnail-generated", response_model=AssetOut)
async def save_generated_thumbnail(
    asset_id: str,
    file: UploadFile = File(...),
    _: Optional[str] = Depends(require_auth),
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


def apply_asset_filters(stmt, q: Optional[str], tags: Optional[str], folder_id: Optional[str]):
    if q:
        qlike = f"%{q}%"
        stmt = stmt.where(
            (Asset.name.like(qlike))
            | (Asset.filename.like(qlike))
            | (Asset.title.like(qlike))
            | (Asset.notes.like(qlike))
            | (Asset.creator.like(qlike))
            | (Asset.collection.like(qlike))
        )
    if folder_id:
        stmt = stmt.where(Asset.folder_id == folder_id)
    tag_filter = [t.strip() for t in (tags or "").split(",") if t.strip()]
    for tag in tag_filter:
        stmt = stmt.where(Asset.tags_json.like(f'%"{tag}"%'))
    return stmt


@app.get("/assets", response_model=List[AssetOut])
def list_assets(
    response: Response,
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as s:
        stmt = apply_asset_filters(select(Asset), q, tags, folder_id)
        stmt = stmt.order_by(Asset.name, Asset.filename, Asset.id)
        if limit is not None:
            stmt = stmt.limit(limit + 1)
            if offset:
                stmt = stmt.offset(offset)
        assets = list(s.exec(stmt))

    has_more = False
    if limit is not None and len(assets) > limit:
        has_more = True
        assets = assets[:limit]
    if limit is not None and response is not None:
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str((offset or 0) + len(assets))

    out: List[AssetOut] = [to_out(a) for a in assets]
    return out


@app.get("/tags", response_model=List[str])
def list_tags(
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as s:
        stmt = apply_asset_filters(select(Asset.tags_json), q, tags, folder_id)
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


@app.post("/download/zip")
def download_zip(body: DownloadRequest, background: BackgroundTasks, _: Optional[str] = Depends(require_auth)):
    if not (body.asset_ids or body.tag or body.folder_id):
        raise HTTPException(status_code=400, detail="Provide asset_ids, tag, or folder_id to download.")

    with Session(engine) as s:
        stmt = select(Asset)
        if body.asset_ids:
            stmt = stmt.where(Asset.id.in_(body.asset_ids))
        if body.folder_id:
            stmt = stmt.where(Asset.folder_id == body.folder_id)
        assets = list(s.exec(stmt))
        folder_map = {}
        folder_ids = {a.folder_id for a in assets if a.folder_id}
        if folder_ids:
            for f in s.exec(select(Folder).where(Folder.id.in_(folder_ids))):
                folder_map[f.id] = f.name

    if body.tag:
        tag = body.tag.strip()
        assets = [a for a in assets if tag in json.loads(a.tags_json or "[]")]

    download_name = body.filename or "makersvault.zip"
    if body.tag:
        safe_tag = body.tag.replace(" ", "_")[:50] or "tag"
        download_name = f"{safe_tag}.zip"
    if body.folder_id and folder_map.get(body.folder_id):
        safe_name = folder_map[body.folder_id].replace(" ", "_")[:50] or "folder"
        download_name = f"{safe_name}.zip"

    return zip_assets_response(assets, download_name, background, folder_map)


# Batch endpoints -----------------------------------------------
# One request, one result per id. A failing item is reported in `failed` and the
# rest still apply, so a partial success is a 200; only a request that could
# change nothing at all (no ids, nothing to change, unknown folder) is a 400.


def require_asset_ids(raw: List[str]) -> List[str]:
    asset_ids = bulk_service.unique_asset_ids(raw)
    if not asset_ids:
        raise HTTPException(status_code=400, detail="asset_ids is required")
    return asset_ids


@app.post("/assets/batch/tags", response_model=BatchTagsOut)
def batch_set_tags(body: BatchTagsRequest, _: Optional[str] = Depends(require_auth)):
    asset_ids = require_asset_ids(body.asset_ids)
    add_tags = [t.strip() for t in body.add_tags if t and t.strip()]
    remove_tags = [t.strip() for t in body.remove_tags if t and t.strip()]
    if not add_tags and not remove_tags:
        raise HTTPException(status_code=400, detail="Provide add_tags or remove_tags")
    updated, failed = bulk_service.update_tags(asset_ids, add_tags, remove_tags)
    return BatchTagsOut(updated=[to_out(a) for a in updated], failed=failed)


@app.post("/assets/batch/folder", response_model=BatchFolderOut)
def batch_move_to_folder(body: BatchFolderRequest, _: Optional[str] = Depends(require_auth)):
    asset_ids = require_asset_ids(body.asset_ids)
    folder_id = body.folder_id or None
    if folder_id:
        # Validate once for the whole request: an unknown target is a bad request,
        # not one failure per asset.
        with Session(engine) as s:
            if not s.get(Folder, folder_id):
                raise HTTPException(status_code=400, detail="Folder not found")
    updated, failed = bulk_service.move_to_folder(asset_ids, folder_id)
    return BatchFolderOut(updated=[to_out(a) for a in updated], failed=failed)


@app.post("/assets/batch/delete", response_model=BatchDeleteOut)
def batch_delete_assets(body: BatchDeleteRequest, _: Optional[str] = Depends(require_auth)):
    asset_ids = require_asset_ids(body.asset_ids)
    deleted, failed = bulk_service.delete_assets(asset_ids)
    return BatchDeleteOut(deleted=deleted, failed=failed)


@app.post("/asset/{asset_id}/tags", response_model=AssetOut)
def set_tags(asset_id: str, body: TagUpdate, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        a.tags_json = json.dumps(body.tags)
        s.add(a)
        s.commit()
        s.refresh(a)
        return to_out(a)


@app.post("/asset/{asset_id}/meta", response_model=AssetOut)
def update_asset_meta(asset_id: str, body: AssetMetaUpdate, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        old_path = managed_asset_path(a)
        moved = False
        new_path = old_path
        requested_name = body.name if body.name is not None else body.title
        if requested_name is not None:
            next_name = unique_model_name(s, requested_name, a.folder_id, exclude_id=a.id)
            if next_name != a.name:
                if not old_path.exists() and a.source_path:
                    raise HTTPException(400, "Renaming is not supported for mounted no-copy files.")
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


@app.post("/asset/{asset_id}/rename", response_model=AssetOut)
def rename_asset(asset_id: str, body: AssetRename, _: Optional[str] = Depends(require_auth)):
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
        a.name = model_name
        a.title = model_name
        a.filename = new_name_only
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


@app.delete("/asset/{asset_id}")
def delete_asset(asset_id: str, _: Optional[str] = Depends(require_auth)):
    delete_asset_permanently(asset_id)
    return {"ok": True}


# Folder endpoints ----------------------------------------------


@app.get("/folders", response_model=List[FolderOut])
def list_folders(_: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        rows = list(s.exec(select(Folder)))
    return [folder_to_out(f) for f in rows]


@app.post("/folders", response_model=FolderOut)
def create_folder(body: FolderIn, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        f = folder_service.create_folder(s, body.name, json.dumps(body.tags), body.parent_id)
    return folder_to_out(f)


@app.patch("/folder/{folder_id}", response_model=FolderOut)
def update_folder(folder_id: str, body: FolderIn, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        f = s.get(Folder, folder_id)
        if not f:
            raise HTTPException(404)
        f = folder_service.move_folder(s, f, body.name, json.dumps(body.tags), body.parent_id)
        result = folder_to_out(f)
    return result


@app.delete("/folder/{folder_id}")
def delete_folder(
    folder_id: str,
    confirm_name: Optional[str] = Query(None),
    _: Optional[str] = Depends(require_auth),
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
        if scan_status().get("running"):
            raise HTTPException(status_code=409, detail="A library scan is running; try again when it finishes")
        result = trash_service.trash_folder(s, folder)
    return {"ok": True, **result}


@app.get("/folder/{folder_id}/delete-preview", response_model=FolderDeletePreviewOut)
def folder_delete_preview(folder_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        folder = s.get(Folder, folder_id)
        if not folder:
            raise HTTPException(404)
        return trash_service.folder_delete_preview(s, folder)


@app.get("/folder/{folder_id}/download")
def download_folder(folder_id: str, background: BackgroundTasks, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        folder = s.get(Folder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        assets = list(s.exec(select(Asset).where(Asset.folder_id == folder_id)))
        folder_map = {folder_id: folder.name}
    download_name = f"{(folder.name or 'folder').replace(' ', '_')[:50] or 'folder'}.zip"
    return zip_assets_response(assets, download_name, background, folder_map)


# Trash endpoints -----------------------------------------------


@app.get("/trash", response_model=TrashListOut)
def list_trash(_: Optional[str] = Depends(require_auth)):
    entries = trash_service.list_entries()
    return TrashListOut(
        entries=[TrashEntryOut(**entry) for entry in entries],
        total_size=sum(entry["size"] for entry in entries),
    )


@app.post("/trash/purge", response_model=TrashPurgeOut)
def purge_trash(older_than_days: Optional[int] = Query(None, ge=0), _: Optional[str] = Depends(require_auth)):
    return TrashPurgeOut(**trash_service.purge(older_than_days))


@app.post("/asset/{asset_id}/folder", response_model=AssetOut)
def update_asset_folder(asset_id: str, body: AssetFolderUpdate, _: Optional[str] = Depends(require_auth)):
    return to_out(move_asset_to_folder_by_id(asset_id, body.folder_id))
