from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile
from contextlib import asynccontextmanager
import tempfile
import threading
from urllib.parse import quote, urlparse
import hmac
import hashlib
import json
import logging
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
    HANDOFF_TOKEN_TTL,
    create_handoff_token,
    create_token,
    decode_handoff_token,
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
    managed_thumbnail_path,
    prune_empty_storage_dirs,
    relocate_asset,
    reorganize_managed_assets,
    sanitize_path_segment,
    sample_storage_path,
    save_thumb,
    save_thumb_bytes_path,
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
from http_security import HostPolicyMiddleware, SecurityHeadersMiddleware, resolve_trusted_hosts
from import_service import download_import_to_temp, import_asset_from_url, open_import_response
from content_identity import (
    content_hash_failure_details,
    latest_content_hash_job,
    recover_interrupted_content_hash_jobs,
    start_content_hash_job,
)
from login_security import LoginAttemptLimiter
from mount_import import (
    latest_mount_scan,
    mount_scan_failure_details,
    recover_interrupted_mount_scans,
    resolve_safe_mount_file,
    start_mount_scan,
)
from models import ArtifactRevision, Asset, AssetFile, ContentHashJob, Folder, MountScan
from migrations import run_migrations
from prepared_print import prepared_filename
from preview_policy import (
    PREVIEW_POLICY_VERSION,
    preview_policy_payload,
    preview_timestamp,
    validate_preview_state,
)
from revision_service import delete_artifact_revisions, sync_current_revision
from revision_workflow import (
    create_revision_from_upload,
    managed_revision_path,
    resolve_revision_content_path,
    restore_revision,
)
from revision_export import build_history_export
from resource_limits import ensure_storage_reserve, stream_upload_to_file
from settings_service import (
    DEFAULT_STORAGE_TEMPLATE,
    get_mount_import_copy,
    get_mount_import_enabled,
    get_storage_template,
    set_mount_import_copy,
    set_mount_import_enabled,
    set_storage_template,
    get_trash_retention,
    set_trash_retention,
    TRASH_RETENTION_CHOICES,
)
from trash_service import (
    EMPTY_TRASH_CONFIRMATION,
    PERMANENT_DELETE_CONFIRMATION,
    list_trash,
    permanently_delete,
    purge_expired_trash,
    reconcile_trash_operations,
    require_active_asset,
    restore_asset,
    soft_delete_asset,
    start_trash_maintenance,
)
from schemas import (
    AssetOut,
    AssetFileOut,
    FolderIn,
    FolderOut,
    LoginRequest,
    LoginResponse,
    HandoffGrantOut,
    HandoffGrantRequest,
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
    MountScanOut,
    MountScanStartOut,
    StorageSettings,
    StorageSettingsOut,
    ArtifactRevisionOut,
    ContentHashJobOut,
    ContentHashStartOut,
    ContentHashStartRequest,
    RevisionCreateOut,
    RevisionRestoreRequest,
    TrashItemOut,
    TrashPermanentDeleteRequest,
    TrashPurgeItemOut,
    TrashRestoreRequest,
    TrashRetentionUpdate,
    TrashSettingsOut,
    PreviewPolicyOut,
    PreviewStateUpdate,
)
from zip_service import extract_zip_entries_to_assets, list_zip_entries
from url_utils import normalize_import_url


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_config()
    run_migrations(engine)
    trash_stop = start_trash_maintenance()
    recover_interrupted_mount_scans()
    recover_interrupted_content_hash_jobs()
    threading.Thread(target=backfill_embedded_thumbnails, daemon=True).start()
    threading.Thread(target=backfill_prepared_print_metadata, daemon=True).start()
    start_content_hash_job("startup")
    if MOUNT_IMPORT_PATH and get_mount_import_enabled(MOUNT_IMPORT_ENABLED):
        start_mount_scan("startup")
    try:
        yield
    finally:
        trash_stop.set()


app = FastAPI(title="MakerVault API", lifespan=lifespan)
app.add_middleware(
    HostPolicyMiddleware,
    allowed_hosts=resolve_trusted_hosts(os.environ),
)

security_logger = logging.getLogger("makersvault.security")
login_limiter = LoginAttemptLimiter()
organization_mutation_lock = threading.Lock()

SLICER_HANDOFF_EXTS = {".stl", ".3mf", ".step", ".stp", ".obj", ".gcode", ".gco", ".bgcode"}
ENGRAVER_HANDOFF_EXTS = {
    ".svg", ".dxf", ".ai", ".eps", ".pdf", ".plt", ".hpgl", ".png", ".jpg",
    ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".lbrn", ".lbrn2", ".ezd",
}
PROTECTED_FILE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
}


def commit_asset_organization_change(session: Session, asset: Asset, old_path: Path) -> Asset:
    """Commit a path-changing asset mutation and restore the file on a DB conflict."""
    new_path = managed_asset_path(asset)
    session.add(asset)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if new_path != old_path and new_path.exists() and not old_path.exists():
            old_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.rename(old_path)
            prune_empty_storage_dirs(new_path.parent)
        raise HTTPException(
            status_code=409,
            detail="A model with this name already exists in the destination folder",
        ) from exc
    session.refresh(asset)
    return asset


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
app.add_middleware(SecurityHeadersMiddleware)


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


def validate_handoff_extension(filename: str, tool: str) -> None:
    allowed = SLICER_HANDOFF_EXTS if tool == "slicer" else ENGRAVER_HANDOFF_EXTS
    if Path(filename or "").suffix.lower() not in allowed:
        raise HTTPException(status_code=415, detail=f"File type is not supported for {tool} handoff")


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
    thumb_path: Optional[Path] = None
    if a.current_thumb_path:
        try:
            thumb_path = managed_thumbnail_path(a.current_thumb_path)
        except HTTPException:
            thumb_path = None
    elif (THUMBS / f"{a.id}.jpg").exists():
        thumb_path = THUMBS / f"{a.id}.jpg"
    thumb_url = None
    if thumb_path and thumb_path.exists():
        thumb_url = (
            f"/asset/{a.id}/revisions/{a.current_revision_id}/thumbnail?v={thumb_path.stat().st_mtime_ns}"
            if a.current_revision_id
            else f"/thumb/{a.id}.jpg?v={thumb_path.stat().st_mtime_ns}"
        )
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
        thumb_url=thumb_url,
        folder_id=a.folder_id,
        storage_path=a.storage_path,
        supporting_file_count=int(a.supporting_file_count or 0),
        prepared_print=prepared,
        slicer_url=slicer_url,
        slicer_filename=(prepared_filename(a.name, prepared) if a.prepared_file_id else a.filename),
        preview_status=("ready" if thumb_path and thumb_path.exists() else a.preview_status),
        preview_reason=(None if thumb_path and thumb_path.exists() else a.preview_reason),
        preview_attempts=a.preview_attempts,
        preview_policy_version=a.preview_policy_version,
        preview_updated_at=a.preview_updated_at,
        preview_source=a.preview_source,
        current_revision_id=a.current_revision_id,
    )


def asset_file_to_out(asset_file: AssetFile) -> AssetFileOut:
    return AssetFileOut(
        id=asset_file.id,
        filename=asset_file.filename,
        mime=asset_file.mime,
        size=asset_file.size,
        url=f"/asset/{asset_file.asset_id}/files/{asset_file.id}",
        revision_id=asset_file.revision_id,
    )


def revision_to_out(revision: ArtifactRevision, current_revision_id: Optional[str]) -> ArtifactRevisionOut:
    try:
        prepared = json.loads(revision.prepared_metadata_json) if revision.prepared_metadata_json else None
    except (TypeError, ValueError):
        prepared = None
    if prepared:
        prepared["removable"] = False
    thumb_url = None
    if revision.preview_thumb_path:
        try:
            thumb = managed_thumbnail_path(revision.preview_thumb_path)
            if thumb.exists():
                thumb_url = (
                    f"/asset/{revision.asset_id}/revisions/{revision.id}/thumbnail"
                    f"?v={thumb.stat().st_mtime_ns}"
                )
        except HTTPException:
            thumb_url = None
    return ArtifactRevisionOut(
        id=revision.id,
        revision_number=revision.revision_number,
        created_at=revision.created_at,
        origin_revision_id=revision.origin_revision_id,
        filename=revision.filename,
        mime=revision.mime,
        size=revision.size,
        sha256=revision.sha256,
        content_state=revision.content_state,
        content_reason=revision.content_reason,
        content_checked_at=revision.content_checked_at,
        change_note=revision.change_note,
        prepared_print=prepared,
        url=f"/asset/{revision.asset_id}/revisions/{revision.id}/file",
        thumb_url=thumb_url,
        is_current=revision.id == current_revision_id,
    )


def content_hash_job_out(job: Optional[ContentHashJob]) -> Optional[ContentHashJobOut]:
    if not job:
        return None
    return ContentHashJobOut(
        id=job.id,
        trigger=job.trigger,
        status=job.status,
        started_at=job.started_at,
        finished_at=job.finished_at,
        total=job.total,
        processed=job.processed,
        ready=job.ready,
        unavailable=job.unavailable,
        changed=job.changed,
        failed=job.failed,
        failure_details=content_hash_failure_details(job),
        failure_details_omitted=job.failure_details_omitted,
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
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=download_name,
        headers=PROTECTED_FILE_HEADERS,
    )


# Routes ---------------------------------------------------------


@app.get("/health")
def health():
    return {
        "ok": True,
        "auth_required": AUTH_ENABLED,
        "version": os.getenv("MAKERSVAULT_VERSION", "development"),
        "revision": os.getenv("MAKERSVAULT_REVISION", "unknown"),
    }


@app.get("/settings/mount-import", response_model=MountImportSettingsOut)
def get_mount_import_settings(_: Optional[str] = Depends(require_auth)):
    return MountImportSettingsOut(
        enabled=get_mount_import_enabled(MOUNT_IMPORT_ENABLED),
        copy_files=get_mount_import_copy(MOUNT_IMPORT_COPY),
        path=MOUNT_IMPORT_PATH or None,
        last_scan=mount_scan_out(latest_mount_scan()),
    )


@app.post("/settings/mount-import", response_model=MountImportSettingsOut)
def update_mount_import_settings(body: MountImportSettings, _: Optional[str] = Depends(require_auth)):
    set_mount_import_enabled(body.enabled)
    set_mount_import_copy(body.copy_files)
    return MountImportSettingsOut(
        enabled=get_mount_import_enabled(MOUNT_IMPORT_ENABLED),
        copy_files=get_mount_import_copy(MOUNT_IMPORT_COPY),
        path=MOUNT_IMPORT_PATH or None,
        last_scan=mount_scan_out(latest_mount_scan()),
    )


def mount_scan_out(scan: Optional[MountScan]) -> Optional[MountScanOut]:
    if not scan:
        return None
    return MountScanOut(
        id=scan.id,
        trigger=scan.trigger,
        status=scan.status,
        mode=scan.mode,
        root_path=scan.root_path,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        imported=scan.imported,
        skipped=scan.skipped,
        failed=scan.failed,
        failure_details=mount_scan_failure_details(scan),
        failure_details_omitted=scan.failure_details_omitted,
    )


@app.get("/settings/mount-import/scan", response_model=Optional[MountScanOut])
def get_mount_import_scan(_: Optional[str] = Depends(require_auth)):
    return mount_scan_out(latest_mount_scan())


@app.post("/settings/mount-import/rescan", response_model=MountScanStartOut)
def rescan_mount_import(_: Optional[str] = Depends(require_auth)):
    try:
        scan, started = start_mount_scan("manual")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MountScanStartOut(scan=mount_scan_out(scan), started=started)


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


@app.get("/settings/preview-policy", response_model=PreviewPolicyOut)
def get_preview_policy(_: Optional[str] = Depends(require_auth)):
    return PreviewPolicyOut(**preview_policy_payload())


@app.get("/settings/content-identity", response_model=Optional[ContentHashJobOut])
def get_content_identity_job(_: Optional[str] = Depends(require_auth)):
    return content_hash_job_out(latest_content_hash_job())


@app.post("/settings/content-identity/backfill", response_model=ContentHashStartOut)
def start_content_identity_backfill(
    body: ContentHashStartRequest,
    _: Optional[str] = Depends(require_auth),
):
    job, started = start_content_hash_job(
        "verify" if body.verify_all else "manual",
        verify_all=body.verify_all,
    )
    return ContentHashStartOut(job=content_hash_job_out(job), started=started)


@app.post("/settings/storage", response_model=StorageSettingsOut)
def update_storage_settings(body: StorageSettings, _: Optional[str] = Depends(require_auth)):
    template = validate_storage_template(body.template)
    set_storage_template(template)
    moved, skipped = reorganize_managed_assets(template) if body.apply_existing else (0, 0)
    return storage_settings_out(template, moved, skipped)


@app.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    if not AUTH_ENABLED:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server")
    source = request.client.host if request.client else "unknown"
    retry_after = login_limiter.retry_after(source, body.username)
    if retry_after:
        security_logger.warning("login_throttled source=%s", source)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )
    username_matches = hmac.compare_digest(
        body.username.encode("utf-8"),
        AUTH_USERNAME.encode("utf-8"),
    )
    password_matches = hmac.compare_digest(
        body.password.encode("utf-8"),
        AUTH_PASSWORD.encode("utf-8"),
    )
    if not username_matches or not password_matches:
        login_limiter.record_failure(source, body.username)
        security_logger.warning("login_failed source=%s", source)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    login_limiter.record_success(source, body.username)
    security_logger.info("login_succeeded source=%s", source)
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
        digest = hashlib.sha256()
        size = await stream_upload_to_file(file, dest, "Uploaded file", digest=digest)
        if (asset.mime or "").lower().startswith("image/") and dest.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            save_thumb(asset.id, dest)
        elif dest.suffix.lower() == ".3mf":
            ensure_model_thumbnail(asset.id, dest)
        asset = finalize_asset_record(asset.id, size, asset.mime, digest.hexdigest()) or asset
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
        a = require_active_asset(s, asset_id)
        media_type = a.mime
        p = resolve_asset_file(a)

    if not p or not p.exists():
        raise HTTPException(404)

    return FileResponse(
        p,
        media_type=media_type or "application/octet-stream",
        filename=name,
        headers=PROTECTED_FILE_HEADERS,
    )


@app.get("/asset/{asset_id}/files", response_model=List[AssetFileOut])
def get_supporting_files(asset_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        require_active_asset(session, asset_id)
    return [asset_file_to_out(row) for row in list_supporting_files(asset_id)]


@app.get("/asset/{asset_id}/revisions", response_model=List[ArtifactRevisionOut])
def get_artifact_revisions(asset_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        asset = require_active_asset(session, asset_id)
        revisions = list(
            session.exec(
                select(ArtifactRevision)
                .where(ArtifactRevision.asset_id == asset_id)
                .order_by(
                    ArtifactRevision.revision_number.desc(),
                    ArtifactRevision.id.desc(),
                )
            )
        )
        return [revision_to_out(row, asset.current_revision_id) for row in revisions]


@app.get("/asset/{asset_id}/revisions/export")
def export_artifact_revisions(
    asset_id: str,
    background_tasks: BackgroundTasks,
    _: Optional[str] = Depends(require_auth),
):
    path, filename = build_history_export(asset_id)
    background_tasks.add_task(path.unlink, missing_ok=True)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        headers=PROTECTED_FILE_HEADERS,
        background=background_tasks,
    )


@app.post("/asset/{asset_id}/revisions", response_model=RevisionCreateOut)
async def upload_artifact_revision(
    asset_id: str,
    file: UploadFile = File(...),
    change_note: Optional[str] = Form(default=None),
    expected_current_revision_id: Optional[str] = Form(default=None),
    _: Optional[str] = Depends(require_auth),
):
    result = await create_revision_from_upload(
        asset_id, file, change_note, expected_current_revision_id
    )
    return RevisionCreateOut(
        asset=to_out(result.asset),
        revision=revision_to_out(result.revision, result.asset.current_revision_id),
        created=result.created,
    )


@app.post(
    "/asset/{asset_id}/revisions/{revision_id}/restore",
    response_model=RevisionCreateOut,
)
def restore_artifact_revision(
    asset_id: str,
    revision_id: str,
    body: RevisionRestoreRequest,
    _: Optional[str] = Depends(require_auth),
):
    result = restore_revision(asset_id, revision_id, body.change_note)
    return RevisionCreateOut(
        asset=to_out(result.asset),
        revision=revision_to_out(result.revision, result.asset.current_revision_id),
        created=result.created,
    )


@app.get("/asset/{asset_id}/revisions/{revision_id}/file")
def download_artifact_revision(
    asset_id: str,
    revision_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        require_active_asset(session, asset_id)
        revision = session.get(ArtifactRevision, revision_id)
        if not revision or revision.asset_id != asset_id:
            raise HTTPException(404)
        if revision.content_state != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Revision content is {revision.content_state}; verify it before download",
            )
        path = resolve_revision_content_path(revision)
        mime = revision.mime
        filename = revision.filename
    if not path or not path.is_file():
        raise HTTPException(404)
    return FileResponse(
        path,
        media_type=mime or "application/octet-stream",
        filename=filename,
        headers=PROTECTED_FILE_HEADERS,
    )


@app.get("/asset/{asset_id}/revisions/{revision_id}/thumbnail")
def get_revision_thumbnail(
    asset_id: str,
    revision_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        require_active_asset(session, asset_id)
        revision = session.get(ArtifactRevision, revision_id)
        if not revision or revision.asset_id != asset_id or not revision.preview_thumb_path:
            raise HTTPException(404)
        path = managed_thumbnail_path(revision.preview_thumb_path)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers=PROTECTED_FILE_HEADERS)


@app.get("/asset/{asset_id}/duplicates", response_model=List[AssetOut])
def get_duplicate_suggestions(asset_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        asset = require_active_asset(session, asset_id)
        revision = (
            session.get(ArtifactRevision, asset.current_revision_id)
            if asset.current_revision_id
            else None
        )
        if not revision or revision.content_state != "ready" or not revision.sha256:
            return []
        matching_revision_ids = list(
            session.exec(
                select(ArtifactRevision.id).where(
                    ArtifactRevision.id != revision.id,
                    ArtifactRevision.sha256 == revision.sha256,
                    ArtifactRevision.size == revision.size,
                    ArtifactRevision.content_state == "ready",
                )
            )
        )
        if not matching_revision_ids:
            return []
        matches = list(
            session.exec(
                select(Asset)
                .where(
                    Asset.id != asset.id,
                    Asset.deleted_at == None,  # noqa: E711
                    Asset.current_revision_id.in_(matching_revision_ids),
                )
                .order_by(Asset.name, Asset.id)
            )
        )
        return [to_out(row) for row in matches]


@app.post("/asset/{asset_id}/files", response_model=AssetOut)
async def upload_related_file(
    asset_id: str,
    file: UploadFile = File(...),
    revision_id: Optional[str] = Form(default=None),
    _: Optional[str] = Depends(require_auth),
):
    asset = await save_asset_file(asset_id, file, revision_id=revision_id)
    return to_out(asset)


@app.get("/asset/{asset_id}/files/{file_id}")
def download_supporting_file(asset_id: str, file_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        require_active_asset(session, asset_id)
        record = session.get(AssetFile, file_id)
        if not record or record.asset_id != asset_id or record.role != "supporting":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        mime = record.mime
        filename = record.filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(
        path,
        media_type=mime or "application/octet-stream",
        filename=filename,
        headers=PROTECTED_FILE_HEADERS,
    )


@app.delete("/asset/{asset_id}/files/{file_id}", response_model=AssetOut)
def remove_supporting_file(asset_id: str, file_id: str, _: Optional[str] = Depends(require_auth)):
    return to_out(delete_supporting_file(asset_id, file_id))


@app.get("/asset/{asset_id}/prepared-print")
def get_prepared_print(asset_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        asset = require_active_asset(session, asset_id)
        if not asset.prepared_file_id:
            raise HTTPException(404)
        record = session.get(AssetFile, asset.prepared_file_id)
        if not record or record.asset_id != asset_id or record.role != "prepared":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        mime = record.mime
        filename = record.filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(
        path,
        media_type=mime or "application/octet-stream",
        filename=filename,
        headers=PROTECTED_FILE_HEADERS,
    )


@app.post("/asset/{asset_id}/handoff", response_model=HandoffGrantOut)
def create_asset_handoff(
    asset_id: str,
    body: HandoffGrantRequest,
    response: Response,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        asset = require_active_asset(session, asset_id)

        file_kind = "primary"
        file_id = asset.id
        filename = asset.filename
        size = int(asset.size or 0)
        path = resolve_asset_file(asset)
        if body.tool == "slicer" and asset.prepared_file_id:
            record = session.get(AssetFile, asset.prepared_file_id)
            if not record or record.asset_id != asset.id or record.role != "prepared":
                raise HTTPException(status_code=409, detail="Prepared file record is unavailable")
            file_kind = "prepared"
            file_id = record.id
            filename = record.filename
            size = int(record.size or 0)
            path = managed_asset_file_path(record)

    validate_handoff_extension(filename, body.tool)
    if not path or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Handoff file is unavailable")
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Handoff file is unavailable") from exc
    if actual_size != size:
        raise HTTPException(status_code=409, detail="Handoff file changed; refresh the asset and try again")

    grant = create_handoff_token(asset_id, file_kind, file_id, body.tool, filename, size)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return HandoffGrantOut(
        redeem_url="/handoff/redeem",
        grant=grant,
        filename=filename,
        expires_in=HANDOFF_TOKEN_TTL,
    )


@app.get("/handoff/redeem")
def redeem_handoff(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    tool: Optional[str] = Header(default=None, alias="X-MakerVault-Handoff-Tool"),
):
    prefix = "MakerVault-Handoff "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Handoff grant is required")
    if tool not in {"slicer", "engraver"}:
        raise HTTPException(status_code=400, detail="Handoff tool is required")
    payload = decode_handoff_token(authorization[len(prefix):].strip())
    if payload.get("tool") != tool:
        raise HTTPException(status_code=403, detail="Handoff grant is not valid for this tool")

    asset_id = payload.get("sub")
    file_kind = payload.get("file_kind")
    file_id = payload.get("file_id")
    filename = payload.get("filename")
    expected_size = payload.get("size")
    if not all(isinstance(value, str) and value for value in (asset_id, file_id, filename)):
        raise HTTPException(status_code=401, detail="Invalid handoff grant")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise HTTPException(status_code=401, detail="Invalid handoff grant")

    with Session(engine) as session:
        try:
            asset = require_active_asset(session, asset_id)
        except HTTPException as exc:
            raise HTTPException(status_code=404, detail="Handoff asset no longer exists") from exc
        if file_kind == "primary":
            if file_id != asset.id or filename != asset.filename or expected_size != int(asset.size or 0):
                raise HTTPException(status_code=409, detail="Handoff file changed")
            path = resolve_asset_file(asset)
            mime = asset.mime
        else:
            record = session.get(AssetFile, file_id)
            if (
                not record
                or record.asset_id != asset.id
                or record.role != "prepared"
                or asset.prepared_file_id != record.id
                or filename != record.filename
                or expected_size != int(record.size or 0)
            ):
                raise HTTPException(status_code=409, detail="Handoff file changed")
            path = managed_asset_file_path(record)
            mime = record.mime

    validate_handoff_extension(filename, tool)
    if not path or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Handoff file is unavailable")
    try:
        if path.stat().st_size != expected_size:
            raise HTTPException(status_code=409, detail="Handoff file changed")
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Handoff file is unavailable") from exc
    return FileResponse(
        path,
        media_type=mime or "application/octet-stream",
        filename=filename,
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.delete("/asset/{asset_id}/prepared-print", response_model=AssetOut)
def remove_prepared_print(asset_id: str, _: Optional[str] = Depends(require_auth)):
    return to_out(delete_prepared_file(asset_id))


@app.get("/thumb/{asset_id}.jpg")
def get_thumb(asset_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        require_active_asset(session, asset_id)
    p = THUMBS / f"{asset_id}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(
        p,
        media_type="image/jpeg",
        headers=PROTECTED_FILE_HEADERS,
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
        asset = require_active_asset(s, asset_id)
        current_revision = (
            s.get(ArtifactRevision, asset.current_revision_id)
            if asset.current_revision_id else None
        )
        if current_revision and current_revision.revision_number > 1:
            thumb_relative = f"thumbs/revisions/{current_revision.id}.jpg"
        else:
            thumb_relative = asset.current_thumb_path or f"thumbs/{asset_id}.jpg"
        if not save_thumb_bytes_path(thumb_relative, data):
            raise HTTPException(status_code=400, detail="Invalid thumbnail image")
        asset.current_thumb_path = thumb_relative
        asset.preview_status = "ready"
        asset.preview_reason = None
        asset.preview_policy_version = PREVIEW_POLICY_VERSION
        asset.preview_updated_at = preview_timestamp()
        asset.preview_source = "generated"
        asset.preview_attempts = max(1, asset.preview_attempts)
        sync_current_revision(s, asset)
        s.commit()
        s.refresh(asset)
        return to_out(asset)


@app.post("/asset/{asset_id}/preview-state", response_model=AssetOut)
def update_preview_state(
    asset_id: str,
    body: PreviewStateUpdate,
    _: Optional[str] = Depends(require_auth),
):
    try:
        status, reason = validate_preview_state(body.status, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with Session(engine) as session:
        asset = require_active_asset(session, asset_id)
        if (THUMBS / f"{asset_id}.jpg").exists():
            asset.preview_status = "ready"
            asset.preview_reason = None
        else:
            asset.preview_status = status
            asset.preview_reason = reason
            if status == "pending":
                asset.preview_attempts += 1
        asset.preview_policy_version = PREVIEW_POLICY_VERSION
        asset.preview_updated_at = preview_timestamp()
        sync_current_revision(session, asset)
        session.commit()
        session.refresh(asset)
        return to_out(asset)


@app.post("/asset/{asset_id}/preview-retry", response_model=AssetOut)
def request_preview_retry(asset_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        asset = require_active_asset(session, asset_id)
        if (THUMBS / f"{asset_id}.jpg").exists():
            asset.preview_status = "ready"
        else:
            asset.preview_status = "retry_requested"
        asset.preview_reason = None
        asset.preview_policy_version = PREVIEW_POLICY_VERSION
        asset.preview_updated_at = preview_timestamp()
        sync_current_revision(session, asset)
        session.commit()
        session.refresh(asset)
        return to_out(asset)


def apply_asset_filters(stmt, q: Optional[str], tags: Optional[str], folder_id: Optional[str]):
    stmt = stmt.where(Asset.deleted_at == None)  # noqa: E711
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
        stmt = select(Asset).where(Asset.deleted_at == None)  # noqa: E711
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
        a = require_active_asset(s, asset_id)
        old_path = managed_asset_path(a)
        a.tags_json = json.dumps(body.tags)
        relocate_asset(a, s, old_path)
        s.add(a)
        s.commit()
        s.refresh(a)
        return to_out(a)


@app.post("/asset/{asset_id}/meta", response_model=AssetOut)
def update_asset_meta(asset_id: str, body: AssetMetaUpdate, _: Optional[str] = Depends(require_auth)):
    with organization_mutation_lock, Session(engine) as s:
        a = require_active_asset(s, asset_id)
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
        return to_out(commit_asset_organization_change(s, a, old_path))


@app.post("/asset/{asset_id}/rename", response_model=AssetOut)
def rename_asset(asset_id: str, body: AssetRename, _: Optional[str] = Depends(require_auth)):
    new_name = (body.filename or "").strip()
    if not new_name:
        raise HTTPException(400, "Filename cannot be empty")
    if "/" in new_name or "\\" in new_name:
        raise HTTPException(400, "Invalid filename")

    with organization_mutation_lock, Session(engine) as s:
        a = require_active_asset(s, asset_id)
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
        return to_out(commit_asset_organization_change(s, a, old_path))


@app.delete("/asset/{asset_id}")
def delete_asset(asset_id: str, _: Optional[str] = Depends(require_auth)):
    soft_delete_asset(asset_id)
    return {"ok": True, "trashed": True}


@app.get("/trash", response_model=List[TrashItemOut])
def get_trash(_: Optional[str] = Depends(require_auth)):
    return [TrashItemOut(**row) for row in list_trash()]


@app.post("/trash/{asset_id}/restore", response_model=AssetOut)
def restore_trashed_asset(
    asset_id: str,
    body: TrashRestoreRequest,
    _: Optional[str] = Depends(require_auth),
):
    return to_out(restore_asset(asset_id, body.restore_unassigned))


@app.post("/trash/permanent", response_model=List[TrashPurgeItemOut])
def permanently_delete_trash(
    body: TrashPermanentDeleteRequest,
    _: Optional[str] = Depends(require_auth),
):
    return permanently_delete(
        body.asset_ids,
        trigger="manual",
        confirmation=body.confirmation,
    )


@app.post("/trash/empty", response_model=List[TrashPurgeItemOut])
def empty_trash(
    body: TrashPermanentDeleteRequest,
    _: Optional[str] = Depends(require_auth),
):
    asset_ids = [row["id"] for row in list_trash()]
    return permanently_delete(
        asset_ids,
        trigger="empty",
        confirmation=body.confirmation,
    )


def trash_settings_out() -> TrashSettingsOut:
    reconciliation = reconcile_trash_operations()
    items = list_trash()
    return TrashSettingsOut(
        policy=get_trash_retention(),
        choices=["until_needed", "day", "week", "month", "never"],
        trash_count=len(items),
        managed_bytes=sum(row["managed_bytes"] for row in items),
        orphaned_quarantine=reconciliation["orphaned"],
    )


@app.get("/settings/trash", response_model=TrashSettingsOut)
def get_trash_settings(_: Optional[str] = Depends(require_auth)):
    return trash_settings_out()


@app.post("/settings/trash", response_model=TrashSettingsOut)
def update_trash_settings(
    body: TrashRetentionUpdate,
    _: Optional[str] = Depends(require_auth),
):
    set_trash_retention(body.policy)
    purge_expired_trash()
    return trash_settings_out()


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
            if not asset.deleted_at:
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
        assets = list(s.exec(select(Asset).where(
            Asset.folder_id == folder_id,
            Asset.deleted_at == None,  # noqa: E711
        )))
        folder_map = {folder_id: folder.name}
    download_name = f"{(folder.name or 'folder').replace(' ', '_')[:50] or 'folder'}.zip"
    return zip_assets_response(assets, download_name, background, folder_map)

@app.post("/asset/{asset_id}/folder", response_model=AssetOut)
def update_asset_folder(asset_id: str, body: AssetFolderUpdate, _: Optional[str] = Depends(require_auth)):
    with organization_mutation_lock, Session(engine) as s:
        asset = require_active_asset(s, asset_id)
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
        return to_out(commit_asset_organization_change(s, asset, old_path))
