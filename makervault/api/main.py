from fastapi import BackgroundTasks, Depends, FastAPI, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from typing import List, Optional
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile
from contextlib import asynccontextmanager
import tempfile
import threading
from urllib.parse import quote, urlparse
import json
import os
import jwt
from jwt import PyJWTError

from auth import (
    AUTH_ENABLED,
    AUTH_PASSWORD,
    AUTH_USERNAME,
    AUTH_TOKEN_TTL,
    AUTH_SECRET,
    AUTH_ALGO,
    create_token,
    require_auth,
    validate_auth_config,
)
from asset_service import (
    STORAGE_TEMPLATE_TOKENS,
    available_model_name,
    backfill_embedded_thumbnails,
    cleanup_asset,
    create_asset_record,
    filename_for_model_name,
    ensure_model_thumbnail,
    finalize_asset_record,
    managed_asset_path,
    prune_empty_storage_dirs,
    relocate_asset,
    reorganize_managed_assets,
    sanitize_path_segment,
    sample_storage_path,
    save_thumb,
    save_thumb_bytes,
    unique_model_name,
    validate_storage_template,
)
from asset_file_service import (
    backfill_prepared_print_metadata,
    delete_all_asset_files,
    delete_prepared_file,
    delete_supporting_file,
    list_supporting_files,
    managed_asset_file_path,
    save_asset_file,
)
from config import (
    GENERATED_THUMBNAIL_MAX_BYTES,
    GENERATED_THUMBNAIL_MAX_MB,
    MOUNT_IMPORT_COPY,
    MOUNT_IMPORT_ENABLED,
    MOUNT_IMPORT_PATH,
)
from db import THUMBS, engine
from file_utils import build_import_filename, mime_from_content_type, sanitize_filename
from folder_service import validate_parent_folder
from import_service import download_import_to_temp, import_asset_from_url, open_import_response
from mount_import import resolve_safe_mount_file, scan_mount_imports
from models import Asset, AssetFile, Folder
from migrations import run_migrations
from prepared_print import prepared_filename
from resource_limits import ensure_storage_reserve, stream_upload_to_file
from settings_service import (
    DEFAULT_STORAGE_TEMPLATE,
    get_mount_import_copy,
    get_mount_import_enabled,
    get_storage_template,
    set_mount_import_copy,
    set_mount_import_enabled,
    set_storage_template,
)
from schemas import (
    AssetOut,
    AssetFileOut,
    FolderIn,
    FolderOut,
    LoginRequest,
    LoginResponse,
    DownloadRequest,
    TagUpdate,
    AssetMetaUpdate,
    AssetRename,
    AssetFolderUpdate,
    ImportRequest,
    ImportInspectOut,
    ImportZipEntriesRequest,
    ImportZipEntriesOut,
    ImportZipExtractRequest,
    ImportZipResult,
    MountImportSettings,
    MountImportSettingsOut,
    StorageSettings,
    StorageSettingsOut,
)
from zip_service import extract_zip_entries_to_assets, list_zip_entries
from url_utils import normalize_import_url


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_config()
    run_migrations(engine)
    threading.Thread(target=backfill_embedded_thumbnails, daemon=True).start()
    threading.Thread(target=backfill_prepared_print_metadata, daemon=True).start()
    if MOUNT_IMPORT_PATH and get_mount_import_enabled(MOUNT_IMPORT_ENABLED):
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
        resolve_safe_mount_file(Path(MOUNT_IMPORT_PATH), path)
    except (OSError, ValueError):
        return False
    return True


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
    return FolderOut(id=f.id, name=f.name, tags=json.loads(f.tags_json or "[]"), parent_id=f.parent_id)


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
    folder_part = sanitize_path_segment(folder_part, "unassigned")
    return f"{folder_part}/{sanitize_filename(asset.filename)}"


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
        folder_part = sanitize_path_segment(folder_part, "unassigned")
        asset_part = sanitize_path_segment(a.name, "model")
        for related in supporting.get(a.id, []):
            related_path = managed_asset_file_path(related)
            if related_path.exists():
                files.append((f"{folder_part}/{asset_part}/supporting/{sanitize_filename(related.filename)}", related_path))
    if not files:
        raise HTTPException(status_code=404, detail="No files available for download")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        source_bytes = sum(fs_path.stat().st_size for _, fs_path in files)
        ensure_storage_reserve(tmp_path, source_bytes)
        with ZipFile(tmp_path, "w", ZIP_DEFLATED) as zf:
            for arc, fs_path in files:
                zf.write(fs_path, arcname=arc)
        ensure_storage_reserve(tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

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
    set_storage_template(template)
    moved, skipped = reorganize_managed_assets(template) if body.apply_existing else (0, 0)
    return storage_settings_out(template, moved, skipped)


@app.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    if not AUTH_ENABLED:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server")
    if body.username != AUTH_USERNAME or body.password != AUTH_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid username or password")
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
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    new_token = create_token(username)
    return LoginResponse(token=new_token, expires_in=AUTH_TOKEN_TTL)


@app.post("/upload", response_model=AssetOut)
async def upload(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    notes: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),  # comma-separated
    folder_id: Optional[str] = Form(default=None),
    _: Optional[str] = Depends(require_auth),
):
    safe_name = sanitize_filename(file.filename)
    asset = create_asset_record(
        safe_name,
        file.content_type or "application/octet-stream",
        title,
        notes,
        [t.strip() for t in (tags or "").split(",") if t.strip()],
        folder_id,
    )

    dest = managed_asset_path(asset)
    try:
        size = await stream_upload_to_file(file, dest, "Uploaded file")
        if (asset.mime or "").lower().startswith("image/") and dest.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            save_thumb(asset.id, dest)
        elif dest.suffix.lower() == ".3mf":
            ensure_model_thumbnail(asset.id, dest)
        asset = finalize_asset_record(asset.id, size, asset.mime) or asset
        return to_out(asset)
    except Exception:
        cleanup_asset(asset.id)
        raise


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
            raise HTTPException(status_code=400, detail="Invalid zip file")
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
            raise HTTPException(status_code=400, detail="Invalid zip file")
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


@app.post("/asset/{asset_id}/files", response_model=AssetOut)
async def upload_related_file(
    asset_id: str,
    file: UploadFile = File(...),
    _: Optional[str] = Depends(require_auth),
):
    asset = await save_asset_file(asset_id, file)
    return to_out(asset)


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
    data = await file.read(GENERATED_THUMBNAIL_MAX_BYTES + 1)
    if len(data) > GENERATED_THUMBNAIL_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Generated thumbnail exceeds {GENERATED_THUMBNAIL_MAX_MB} MB",
        )
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


@app.post("/asset/{asset_id}/tags", response_model=AssetOut)
def set_tags(asset_id: str, body: TagUpdate, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        old_path = managed_asset_path(a)
        a.tags_json = json.dumps(body.tags)
        relocate_asset(a, s, old_path)
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
        requested_name = body.name if body.name is not None else body.title
        if requested_name is not None:
            next_name = unique_model_name(s, requested_name, a.folder_id, exclude_id=a.id)
            if next_name != a.name:
                if not old_path.exists() and a.source_path:
                    raise HTTPException(400, "Renaming is not supported for mounted no-copy files.")
                a.name = next_name
                a.title = next_name
                a.filename = filename_for_model_name(next_name, a.filename)
        if body.notes is not None:
            a.notes = body.notes
        if body.creator is not None:
            a.creator = body.creator.strip() or None
        if body.collection is not None:
            a.collection = body.collection.strip() or None
        relocate_asset(a, s, old_path)
        s.add(a)
        s.commit()
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
        relocate_asset(a, s, old_path)
        s.add(a)
        s.commit()
        s.refresh(a)
        return to_out(a)


@app.delete("/asset/{asset_id}")
def delete_asset(asset_id: str, _: Optional[str] = Depends(require_auth)):
    managed_path: Optional[Path] = None
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        managed_path = managed_asset_path(a)
    delete_all_asset_files(asset_id)
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        s.delete(a)
        s.commit()
    # best-effort cleanup
    try:
        if managed_path and managed_path.exists():
            parent = managed_path.parent
            managed_path.unlink(missing_ok=True)
            prune_empty_storage_dirs(parent)
        (THUMBS / f"{asset_id}.jpg").unlink(missing_ok=True)
    except Exception:
        pass
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
        parent_id = validate_parent_folder(s, body.parent_id)
        f = Folder(name=body.name, tags_json=json.dumps(body.tags), parent_id=parent_id)
        s.add(f)
        s.commit()
        s.refresh(f)
    return folder_to_out(f)


@app.patch("/folder/{folder_id}", response_model=FolderOut)
def update_folder(folder_id: str, body: FolderIn, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        f = s.get(Folder, folder_id)
        if not f:
            raise HTTPException(404)
        parent_id = validate_parent_folder(s, body.parent_id, folder_id)
        f.name = body.name
        f.tags_json = json.dumps(body.tags)
        f.parent_id = parent_id
        s.add(f)
        s.commit()
        s.refresh(f)
        result = folder_to_out(f)
    reorganize_managed_assets()
    return result


@app.delete("/folder/{folder_id}")
def delete_folder(folder_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        f = s.get(Folder, folder_id)
        if not f:
            raise HTTPException(404)
        # Detach children to root
        for child in s.exec(select(Folder).where(Folder.parent_id == folder_id)):
            child.parent_id = None
            s.add(child)
        # Unassign assets in this folder
        for asset in s.exec(select(Asset).where(Asset.folder_id == folder_id)):
            next_name = available_model_name(s, asset.name, None, exclude_id=asset.id)
            if next_name != asset.name:
                asset.name = next_name
                asset.title = next_name
                asset.filename = filename_for_model_name(next_name, asset.filename)
            asset.folder_id = None
            s.add(asset)
        s.delete(f)
        s.commit()
    reorganize_managed_assets()
    return {"ok": True}


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

@app.post("/asset/{asset_id}/folder", response_model=AssetOut)
def update_asset_folder(asset_id: str, body: AssetFolderUpdate, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as s:
        asset = s.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        old_path = managed_asset_path(asset)
        folder_id = body.folder_id or None
        if folder_id:
            folder = s.get(Folder, folder_id)
            if not folder:
                raise HTTPException(status_code=400, detail="Folder not found")
            unique_model_name(s, asset.name, folder.id, exclude_id=asset.id)
            asset.folder_id = folder.id
        else:
            asset.folder_id = None
            unique_model_name(s, asset.name, None, exclude_id=asset.id)
        relocate_asset(asset, s, old_path)
        s.add(asset)
        s.commit()
        s.refresh(asset)
        return to_out(asset)
