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
import hashlib
import json
import logging
import os
import time

from auth import (
    AUTH_ENABLED,
    AUTH_PASSWORD,
    AUTH_USERNAME,
    HANDOFF_TOKEN_TTL,
    clear_browser_session_cookies,
    create_handoff_token,
    decode_handoff_token,
    require_auth,
    set_browser_session_cookies,
    validate_auth_config,
)
from authorization import (
    Role,
    SystemService,
    permissions_for_role,
    run_system_service,
    validate_route_inventory,
)
from account_service import (
    change_own_password,
    create_account,
    list_accounts,
    reset_account_password,
    update_account,
    verify_account_password,
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
from identity_service import (
  authenticate_initial_administrator,
  bootstrap_initial_administrator,
)
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
from models import (
    ArtifactMachine,
    ArtifactRevision,
    Asset,
    AssetFile,
    ContentHashJob,
    Folder,
    MountScan,
    MachineProfile,
    Project,
    ProjectMembership,
    ProjectRelationship,
    UserAccount,
)
from machine_service import (
    archive_machine,
    create_machine,
    permanently_delete_machine,
    require_active_machine,
    require_machine,
    restore_machine,
    update_machine,
)
from machine_context_service import (
    DESCRIPTIVE_CONTEXT_NOTICE,
    add_machine_association,
    list_machine_context,
    remove_machine_association,
    set_prepared_machine,
)
from migrations import run_migrations
from prepared_print import prepared_filename
from preview_policy import (
    PREVIEW_POLICY_VERSION,
    preview_policy_payload,
    preview_timestamp,
    validate_preview_state,
)
from project_service import (
    active_member_counts,
    add_project_membership,
    create_project,
    list_trashed_projects,
    permanently_delete_project,
    remove_project_membership,
    require_active_project,
    restore_project,
    soft_delete_project,
    update_project,
)
from project_export import build_project_export
from relationship_service import (
    create_relationship,
    delete_relationship,
    list_active_relationships,
    relationship_labels,
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
    AssetMachineContextOut,
    AssetOut,
    AssetFileOut,
    FolderIn,
    FolderOut,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    PasswordResetRequest,
    ReauthenticateOut,
    ReauthenticateRequest,
    BrowserSessionOut,
    SessionRevokeAllOut,
    SessionStatusOut,
    UserCreate,
    UserOut,
    UserUpdate,
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
    MachineCategory,
    MachineScope,
    MachineAssociationOut,
    MachineCreate,
    MachineOut,
    MachinePermanentDeleteOut,
    MachinePermanentDeleteRequest,
    MachineUpdate,
    PreparedMachineUpdate,
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
    ProjectCreate,
    ProjectMembershipOut,
    ProjectOut,
    ProjectPermanentDeleteOut,
    ProjectPermanentDeleteRequest,
    ProjectRelationshipCreate,
    ProjectRelationshipOut,
    ProjectTrashOut,
    ProjectUpdate,
)
from zip_service import extract_zip_entries_to_assets, list_zip_entries
from url_utils import normalize_import_url
from session_service import (
    SessionPrincipal,
    cleanup_browser_sessions,
    cookie_policy,
    create_browser_session,
    mark_session_reauthenticated,
    list_user_sessions,
    revoke_all_user_sessions,
    revoke_browser_session,
    revoke_session_secret,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_config()
    validate_route_inventory(_app)
    run_migrations(engine)
    bootstrap = bootstrap_initial_administrator(
        engine,
        username=AUTH_USERNAME,
        password=AUTH_PASSWORD,
    )
    if bootstrap.created:
        security_logger.info(
            "persistent_administrator_bootstrapped password_change_required=%s",
            str(bootstrap.password_change_required).lower(),
        )
    run_system_service(
        SystemService.SESSION_CLEANUP,
        lambda: cleanup_browser_sessions(engine),
    )
    trash_stop = run_system_service(
        SystemService.TRASH_MAINTENANCE,
        start_trash_maintenance,
    )
    run_system_service(
        SystemService.MOUNT_SCAN_RECOVER,
        recover_interrupted_mount_scans,
    )
    run_system_service(
        SystemService.CONTENT_IDENTITY_RECOVER,
        recover_interrupted_content_hash_jobs,
    )
    run_system_service(
        SystemService.THUMBNAIL_BACKFILL,
        lambda: threading.Thread(
            target=backfill_embedded_thumbnails,
            daemon=True,
        ).start(),
    )
    run_system_service(
        SystemService.PREPARED_METADATA_BACKFILL,
        lambda: threading.Thread(
            target=backfill_prepared_print_metadata,
            daemon=True,
        ).start(),
    )
    run_system_service(
        SystemService.CONTENT_IDENTITY_STARTUP,
        lambda: start_content_hash_job("startup"),
    )
    if MOUNT_IMPORT_PATH and get_mount_import_enabled(MOUNT_IMPORT_ENABLED):
        run_system_service(
            SystemService.MOUNT_SCAN_STARTUP,
            lambda: start_mount_scan("startup"),
        )
    try:
        yield
    finally:
        trash_stop.set()


app = FastAPI(
    title="MakerVault API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
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
    if tool == "slicer":
        allowed = SLICER_HANDOFF_EXTS
    elif tool == "engraver":
        allowed = ENGRAVER_HANDOFF_EXTS
    else:
        allowed = SLICER_HANDOFF_EXTS | ENGRAVER_HANDOFF_EXTS
    if Path(filename or "").suffix.lower() not in allowed:
        raise HTTPException(status_code=415, detail=f"File type is not supported for {tool} handoff")


def folder_to_out(f: Folder) -> "FolderOut":
    return FolderOut(id=f.id, name=f.name, tags=json.loads(f.tags_json or "[]"), parent_id=f.parent_id)


def project_to_out(project: Project, member_count: int = 0) -> ProjectOut:
    try:
        tags = json.loads(project.tags_json or "[]")
    except (TypeError, ValueError):
        tags = []
    if not isinstance(tags, list):
        tags = []
    return ProjectOut(
        id=project.id,
        name=project.name,
        notes=project.notes,
        creator=project.creator,
        source_url=project.source_url,
        license=project.license,
        tags=[tag for tag in tags if isinstance(tag, str)],
        created_at=project.created_at,
        updated_at=project.updated_at,
        deleted_at=project.deleted_at,
        member_count=member_count,
    )


def machine_to_out(machine: MachineProfile) -> MachineOut:
    return MachineOut(
        id=machine.id,
        name=machine.name,
        category=machine.category,
        manufacturer=machine.manufacturer,
        model=machine.model,
        location=machine.location,
        notes=machine.notes,
        created_at=machine.created_at,
        updated_at=machine.updated_at,
        archived_at=machine.archived_at,
    )


def user_to_out(user: UserAccount) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        enabled=user.enabled,
        password_change_required=user.password_change_required,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def machine_context_to_out(session: Session, asset_id: str) -> AssetMachineContextOut:
    asset, associations, prepared_machine = list_machine_context(session, asset_id)
    return AssetMachineContextOut(
        asset_id=asset.id,
        associations=[
            MachineAssociationOut(
                machine=machine_to_out(machine),
                created_at=association.created_at,
            )
            for association, machine in associations
        ],
        prepared_machine=(
            machine_to_out(prepared_machine) if prepared_machine else None
        ),
        prepared_revision_id=(
            asset.current_revision_id if prepared_machine else None
        ),
        notice=DESCRIPTIVE_CONTEXT_NOTICE,
    )


def relationship_to_out(
    relationship: ProjectRelationship,
    source: Asset,
    target: Asset,
) -> ProjectRelationshipOut:
    forward_label, inverse_label = relationship_labels(relationship.kind)
    return ProjectRelationshipOut(
        id=relationship.id,
        project_id=relationship.project_id,
        source_asset_id=relationship.source_asset_id,
        target_asset_id=relationship.target_asset_id,
        source_name=source.name,
        target_name=target.name,
        kind=relationship.kind,
        created_at=relationship.created_at,
        forward_label=forward_label,
        inverse_label=inverse_label,
    )


def validate_project_association(project_id: Optional[str]) -> None:
    if not project_id:
        return
    with Session(engine) as session:
        require_active_project(session, project_id)


def associate_asset_with_project(asset_id: str, project_id: Optional[str]) -> None:
    if not project_id:
        return
    with Session(engine) as session:
        add_project_membership(session, project_id, asset_id)


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
        prepared_machine_id=a.prepared_machine_id,
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
        prepared_machine_id=revision.prepared_machine_id,
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
def login(body: LoginRequest, request: Request, response: Response):
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
    identity = authenticate_initial_administrator(
        engine,
        username=body.username,
        password=body.password,
    )
    if identity is None:
        login_limiter.record_failure(source, body.username)
        security_logger.warning("login_failed source=%s", source)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    login_limiter.record_success(source, body.username)
    security_logger.info("login_succeeded source=%s", source)
    policy = cookie_policy()
    revoke_session_secret(engine, request.cookies.get(policy.session_name))
    created = create_browser_session(
        engine,
        user_id=identity.id,
        client_address=source,
        user_agent=request.headers.get("User-Agent"),
    )
    set_browser_session_cookies(response, created)
    response.headers["Cache-Control"] = "private, no-store"
    return LoginResponse(
        role=identity.role.value,
        permissions=sorted(permission.value for permission in permissions_for_role(identity.role)),
        password_change_required=identity.password_change_required,
        csrf_token=created.csrf_token,
        expires_in=max(1, created.idle_expires_at - int(time.time())),
        absolute_expires_at=created.absolute_expires_at,
    )


@app.get("/session", response_model=SessionStatusOut)
def current_session(
    response: Response,
    principal: SessionPrincipal = Depends(require_auth),
):
    response.headers["Cache-Control"] = "private, no-store"
    return SessionStatusOut(
        session_id=principal.session_id,
        username=principal.username,
        role=principal.role.value,
        permissions=sorted(permission.value for permission in permissions_for_role(principal.role)),
        password_change_required=principal.password_change_required,
        csrf_token=principal.csrf_token,
        reauthenticated_at=principal.reauthenticated_at,
        idle_expires_at=principal.idle_expires_at,
        absolute_expires_at=principal.absolute_expires_at,
    )


@app.post("/session/reauthenticate", response_model=ReauthenticateOut)
def reauthenticate_session(
    body: ReauthenticateRequest,
    principal: SessionPrincipal = Depends(require_auth),
):
    if not verify_account_password(engine, principal.user_id, body.password):
        raise HTTPException(status_code=401, detail="Password confirmation failed")
    reauthenticated_at = mark_session_reauthenticated(
        engine,
        user_id=principal.user_id,
        session_id=principal.session_id,
    )
    return ReauthenticateOut(reauthenticated_at=reauthenticated_at)


@app.post("/account/password", response_model=LoginResponse)
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    principal: SessionPrincipal = Depends(require_auth),
):
    account = change_own_password(
        engine,
        principal.user_id,
        password=body.new_password,
    )
    source = request.client.host if request.client else "unknown"
    created = create_browser_session(
        engine,
        user_id=account.id,
        client_address=source,
        user_agent=request.headers.get("User-Agent"),
    )
    set_browser_session_cookies(response, created)
    response.headers["Cache-Control"] = "private, no-store"
    role = Role(account.role)
    return LoginResponse(
        role=role.value,
        permissions=sorted(
            permission.value for permission in permissions_for_role(role)
        ),
        password_change_required=False,
        csrf_token=created.csrf_token,
        expires_in=max(1, created.idle_expires_at - int(time.time())),
        absolute_expires_at=created.absolute_expires_at,
    )


@app.get("/users", response_model=List[UserOut])
def users(_: SessionPrincipal = Depends(require_auth)):
    return [user_to_out(user) for user in list_accounts(engine)]


@app.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    _: SessionPrincipal = Depends(require_auth),
):
    return user_to_out(
        create_account(
            engine,
            username=body.username,
            display_name=body.display_name,
            password=body.password,
            role=Role(body.role),
        )
    )


@app.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdate,
    _: SessionPrincipal = Depends(require_auth),
):
    return user_to_out(
        update_account(
            engine,
            user_id,
            display_name=body.display_name,
            role=Role(body.role) if body.role is not None else None,
            enabled=body.enabled,
        )
    )


@app.post("/users/{user_id}/password-reset", response_model=UserOut)
def reset_user_password(
    user_id: str,
    body: PasswordResetRequest,
    principal: SessionPrincipal = Depends(require_auth),
):
    if user_id == principal.user_id:
        raise HTTPException(
            status_code=409,
            detail="Use the self-service password change for your own account",
        )
    return user_to_out(
        reset_account_password(
            engine,
            user_id,
            password=body.new_password,
        )
    )


@app.get("/sessions", response_model=List[BrowserSessionOut])
def browser_sessions(
    response: Response,
    principal: SessionPrincipal = Depends(require_auth),
):
    response.headers["Cache-Control"] = "private, no-store"
    return [
        BrowserSessionOut(
            id=item.id,
            current=item.id == principal.session_id,
            created_at=item.created_at,
            last_seen_at=item.last_seen_at,
            idle_expires_at=item.idle_expires_at,
            absolute_expires_at=item.absolute_expires_at,
            client_address=item.client_address,
            user_agent=item.user_agent,
        )
        for item in list_user_sessions(engine, user_id=principal.user_id)
    ]


@app.post("/logout", status_code=204)
def logout(
    response: Response,
    principal: SessionPrincipal = Depends(require_auth),
):
    revoke_browser_session(
        engine,
        user_id=principal.user_id,
        session_id=principal.session_id,
    )
    clear_browser_session_cookies(response)
    response.status_code = 204
    return response


@app.delete("/sessions/{session_id}", status_code=204)
def revoke_one_browser_session(
    session_id: str,
    response: Response,
    principal: SessionPrincipal = Depends(require_auth),
):
    if not revoke_browser_session(
        engine,
        user_id=principal.user_id,
        session_id=session_id,
    ):
        raise HTTPException(status_code=404, detail="Session not found")
    if session_id == principal.session_id:
        clear_browser_session_cookies(response)
    response.status_code = 204
    return response


@app.post("/sessions/revoke-all", response_model=SessionRevokeAllOut)
def revoke_all_browser_sessions(
    response: Response,
    principal: SessionPrincipal = Depends(require_auth),
):
    revoked = revoke_all_user_sessions(engine, user_id=principal.user_id)
    clear_browser_session_cookies(response)
    return SessionRevokeAllOut(revoked=revoked)


@app.post("/upload", response_model=AssetOut)
async def upload(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    notes: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),  # comma-separated
    folder_id: Optional[str] = Form(default=None),
    project_id: Optional[str] = Form(default=None),
    _: Optional[str] = Depends(require_auth),
):
    validate_project_association(project_id)
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
        associate_asset_with_project(asset.id, project_id)
        return to_out(asset)
    except Exception:
        cleanup_asset(asset.id)
        raise


@app.post("/import", response_model=AssetOut)
def import_from_link(body: ImportRequest, _: Optional[str] = Depends(require_auth)):
    validate_project_association(body.project_id)
    url = normalize_import_url(body.url)
    asset = import_asset_from_url(url, body)
    try:
        associate_asset_with_project(asset.id, body.project_id)
        return to_out(asset)
    except Exception:
        cleanup_asset(asset.id)
        raise


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
    validate_project_association(body.project_id)
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

        tool = body.tool or "open"
        file_kind = body.content_role or "primary"
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
        elif body.content_role == "revision_primary":
            revision = session.get(ArtifactRevision, body.revision_id)
            if (
                not revision
                or revision.asset_id != asset.id
                or revision.content_state != "ready"
            ):
                raise HTTPException(status_code=404, detail="Revision content is unavailable")
            file_id = revision.id
            filename = revision.filename
            size = int(revision.size or 0)
            path = resolve_revision_content_path(revision)
        elif body.content_role == "supporting":
            record = session.get(AssetFile, body.file_id)
            if not record or record.asset_id != asset.id or record.role != "supporting":
                raise HTTPException(status_code=404, detail="Supporting file is unavailable")
            file_id = record.id
            filename = record.filename
            size = int(record.size or 0)
            path = managed_asset_file_path(record)
        elif body.content_role == "prepared":
            if not asset.prepared_file_id:
                raise HTTPException(status_code=404, detail="Prepared file is unavailable")
            record = session.get(AssetFile, asset.prepared_file_id)
            if not record or record.asset_id != asset.id or record.role != "prepared":
                raise HTTPException(status_code=409, detail="Prepared file record is unavailable")
            file_id = record.id
            filename = record.filename
            size = int(record.size or 0)
            path = managed_asset_file_path(record)

    validate_handoff_extension(filename, tool)
    if not path or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Handoff file is unavailable")
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Handoff file is unavailable") from exc
    if actual_size != size:
        raise HTTPException(status_code=409, detail="Handoff file changed; refresh the asset and try again")

    grant = create_handoff_token(
        asset_id,
        file_kind,
        file_id,
        tool,
        filename,
        size,
        body.content_role,
        body.adapter_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return HandoffGrantOut(
        redeem_url="/handoff/redeem",
        grant=grant,
        filename=filename,
        expires_in=HANDOFF_TOKEN_TTL,
        adapter_id=body.adapter_id,
        content_role=body.content_role,
    )


@app.get("/handoff/redeem")
def redeem_handoff(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    tool: Optional[str] = Header(default=None, alias="X-MakerVault-Handoff-Tool"),
    adapter_id: Optional[str] = Header(default=None, alias="X-MakerVault-Handoff-Adapter"),
    content_role: Optional[str] = Header(default=None, alias="X-MakerVault-Handoff-Role"),
):
    prefix = "MakerVault-Handoff "
    if not authorization or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Handoff grant is required")
    if tool not in {"slicer", "engraver", "open"}:
        raise HTTPException(status_code=400, detail="Handoff tool is required")
    payload = decode_handoff_token(authorization[len(prefix):].strip())
    if payload.get("tool") != tool:
        raise HTTPException(status_code=403, detail="Handoff grant is not valid for this tool")
    if tool == "open":
        if payload.get("adapter_id") != adapter_id or payload.get("content_role") != content_role:
            raise HTTPException(status_code=403, detail="Handoff grant is not valid for this adapter or role")
    elif adapter_id is not None or content_role is not None:
        raise HTTPException(status_code=403, detail="General adapter headers are not valid for this tool")

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
        elif file_kind == "revision_primary":
            revision = session.get(ArtifactRevision, file_id)
            if (
                not revision
                or revision.asset_id != asset.id
                or revision.content_state != "ready"
                or filename != revision.filename
                or expected_size != int(revision.size or 0)
            ):
                raise HTTPException(status_code=409, detail="Handoff file changed")
            path = resolve_revision_content_path(revision)
            mime = revision.mime
        else:
            record = session.get(AssetFile, file_id)
            expected_role = "supporting" if file_kind == "supporting" else "prepared"
            if (
                not record
                or record.asset_id != asset.id
                or record.role != expected_role
                or (expected_role == "prepared" and asset.prepared_file_id != record.id)
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


def apply_asset_filters(
    stmt,
    q: Optional[str],
    tags: Optional[str],
    folder_id: Optional[str],
    project_id: Optional[str] = None,
    project_unassigned: bool = False,
    machine_id: Optional[str] = None,
    machine_scope: Optional[MachineScope] = None,
):
    stmt = stmt.where(Asset.deleted_at == None)  # noqa: E711
    if project_id:
        stmt = stmt.join(
            ProjectMembership,
            ProjectMembership.asset_id == Asset.id,
        ).where(ProjectMembership.project_id == project_id)
    elif project_unassigned:
        active_membership = (
            select(ProjectMembership.asset_id)
            .join(Project, Project.id == ProjectMembership.project_id)
            .where(
                ProjectMembership.asset_id == Asset.id,
                Project.deleted_at == None,  # noqa: E711
            )
            .exists()
        )
        stmt = stmt.where(~active_membership)
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
    if machine_id:
        associated = select(ArtifactMachine.asset_id).where(
            ArtifactMachine.asset_id == Asset.id,
            ArtifactMachine.machine_id == machine_id,
        ).exists()
        if machine_scope == "associated":
            stmt = stmt.where(associated)
        elif machine_scope == "prepared":
            stmt = stmt.where(Asset.prepared_machine_id == machine_id)
        else:
            stmt = stmt.where(
                associated | (Asset.prepared_machine_id == machine_id)
            )
    return stmt


def validate_machine_filter(
    session: Session,
    machine_id: Optional[str],
    machine_scope: Optional[MachineScope],
) -> None:
    if machine_scope and not machine_id:
        raise HTTPException(
            status_code=422,
            detail="machine_scope requires machine_id",
        )
    if machine_id:
        require_machine(session, machine_id)


@app.get("/assets", response_model=List[AssetOut])
def list_assets(
    response: Response,
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    project_id: Optional[str] = None,
    project_unassigned: bool = False,
    machine_id: Optional[str] = None,
    machine_scope: Optional[MachineScope] = None,
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    _: Optional[str] = Depends(require_auth),
):
    if project_id and project_unassigned:
        raise HTTPException(status_code=422, detail="Choose a Project or Unassigned, not both")
    with Session(engine) as s:
        if project_id:
            require_active_project(s, project_id)
        validate_machine_filter(s, machine_id, machine_scope)
        stmt = apply_asset_filters(
            select(Asset),
            q,
            tags,
            folder_id,
            project_id,
            project_unassigned,
            machine_id,
            machine_scope,
        )
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
    project_id: Optional[str] = None,
    project_unassigned: bool = False,
    machine_id: Optional[str] = None,
    machine_scope: Optional[MachineScope] = None,
    _: Optional[str] = Depends(require_auth),
):
    if project_id and project_unassigned:
        raise HTTPException(status_code=422, detail="Choose a Project or Unassigned, not both")
    with Session(engine) as s:
        if project_id:
            require_active_project(s, project_id)
        validate_machine_filter(s, machine_id, machine_scope)
        stmt = apply_asset_filters(
            select(Asset.tags_json),
            q,
            tags,
            folder_id,
            project_id,
            project_unassigned,
            machine_id,
            machine_scope,
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


# Machine endpoints ---------------------------------------------


@app.get(
    "/asset/{asset_id}/machines",
    response_model=AssetMachineContextOut,
)
def get_asset_machine_context(
    asset_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return machine_context_to_out(session, asset_id)


@app.post(
    "/asset/{asset_id}/machines/{machine_id}",
    response_model=AssetMachineContextOut,
    status_code=201,
)
def associate_machine_with_asset(
    asset_id: str,
    machine_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        add_machine_association(session, asset_id, machine_id)
        return machine_context_to_out(session, asset_id)


@app.delete(
    "/asset/{asset_id}/machines/{machine_id}",
    response_model=AssetMachineContextOut,
)
def remove_machine_from_asset(
    asset_id: str,
    machine_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        remove_machine_association(session, asset_id, machine_id)
        return machine_context_to_out(session, asset_id)


@app.put(
    "/asset/{asset_id}/prepared-machine",
    response_model=AssetMachineContextOut,
)
def update_asset_prepared_machine(
    asset_id: str,
    body: PreparedMachineUpdate,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        set_prepared_machine(session, asset_id, body.machine_id)
        return machine_context_to_out(session, asset_id)


@app.get("/machines", response_model=List[MachineOut])
def list_machines(
    response: Response,
    q: Optional[str] = Query(default=None, max_length=200),
    category: Optional[MachineCategory] = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: SessionPrincipal = Depends(require_auth),
):
    with Session(engine) as session:
        statement = select(MachineProfile)
        if not include_archived or principal.role is Role.VIEWER:
            statement = statement.where(MachineProfile.archived_at == None)  # noqa: E711
        if category:
            statement = statement.where(MachineProfile.category == category)
        if q and q.strip():
            pattern = f"%{q.strip()}%"
            statement = statement.where(
                (MachineProfile.name.like(pattern))
                | (MachineProfile.manufacturer.like(pattern))
                | (MachineProfile.model.like(pattern))
                | (MachineProfile.location.like(pattern))
                | (MachineProfile.notes.like(pattern))
            )
        machines = list(session.exec(
            statement.order_by(MachineProfile.name, MachineProfile.id)
            .offset(offset)
            .limit(limit + 1)
        ))
        has_more = len(machines) > limit
        if has_more:
            machines = machines[:limit]
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str(offset + len(machines))
        return [machine_to_out(machine) for machine in machines]


@app.post("/machines", response_model=MachineOut, status_code=201)
def create_machine_route(
    body: MachineCreate,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return machine_to_out(create_machine(session, body))


@app.get("/machine/{machine_id}", response_model=MachineOut)
def get_machine(
    machine_id: str,
    principal: SessionPrincipal = Depends(require_auth),
):
    with Session(engine) as session:
        machine = (
            require_active_machine(session, machine_id)
            if principal.role is Role.VIEWER
            else require_machine(session, machine_id)
        )
        return machine_to_out(machine)


@app.patch("/machine/{machine_id}", response_model=MachineOut)
def update_machine_route(
    machine_id: str,
    body: MachineUpdate,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return machine_to_out(update_machine(session, machine_id, body))


@app.post("/machine/{machine_id}/archive", response_model=MachineOut)
def archive_machine_route(
    machine_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return machine_to_out(archive_machine(session, machine_id))


@app.post("/machine/{machine_id}/restore", response_model=MachineOut)
def restore_machine_route(
    machine_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return machine_to_out(restore_machine(session, machine_id))


@app.post(
    "/machine/{machine_id}/permanent",
    response_model=MachinePermanentDeleteOut,
)
def permanently_delete_machine_route(
    machine_id: str,
    body: MachinePermanentDeleteRequest,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return MachinePermanentDeleteOut(**permanently_delete_machine(
            session,
            machine_id,
            body.confirmation,
        ))


# Project endpoints ---------------------------------------------


@app.get("/projects", response_model=List[ProjectOut])
def list_projects(
    response: Response,
    q: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        statement = select(Project).where(Project.deleted_at == None)  # noqa: E711
        if q and q.strip():
            pattern = f"%{q.strip()}%"
            statement = statement.where(
                (Project.name.like(pattern))
                | (Project.notes.like(pattern))
                | (Project.creator.like(pattern))
                | (Project.license.like(pattern))
                | (Project.tags_json.like(pattern))
            )
        projects = list(
            session.exec(
                statement.order_by(Project.name, Project.id).offset(offset).limit(limit + 1)
            )
        )
        has_more = len(projects) > limit
        if has_more:
            projects = projects[:limit]
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str(offset + len(projects))
        counts = active_member_counts(session, [project.id for project in projects])
        return [project_to_out(project, counts.get(project.id, 0)) for project in projects]


@app.get("/projects/trash", response_model=List[ProjectTrashOut])
def list_project_trash(
    response: Response,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        rows = list_trashed_projects(session, limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    response.headers["X-Has-More"] = "true" if has_more else "false"
    response.headers["X-Next-Offset"] = str(offset + len(rows))
    return [ProjectTrashOut(**row) for row in rows]


@app.post("/projects", response_model=ProjectOut, status_code=201)
def create_project_route(
    body: ProjectCreate,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return project_to_out(create_project(session, body))


@app.get("/project/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        project = require_active_project(session, project_id)
        count = active_member_counts(session, [project_id]).get(project_id, 0)
        return project_to_out(project, count)


@app.patch("/project/{project_id}", response_model=ProjectOut)
def update_project_route(
    project_id: str,
    body: ProjectUpdate,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        project = update_project(session, project_id, body)
        count = active_member_counts(session, [project_id]).get(project_id, 0)
        return project_to_out(project, count)


@app.delete("/project/{project_id}")
def delete_project(project_id: str, _: Optional[str] = Depends(require_auth)):
    with Session(engine) as session:
        soft_delete_project(session, project_id)
    return {"ok": True}


@app.post("/project/{project_id}/restore", response_model=ProjectOut)
def restore_project_route(
    project_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        project = restore_project(session, project_id)
        count = active_member_counts(session, [project_id]).get(project_id, 0)
        return project_to_out(project, count)


@app.post(
    "/project/{project_id}/permanent",
    response_model=ProjectPermanentDeleteOut,
)
def permanently_delete_project_route(
    project_id: str,
    body: ProjectPermanentDeleteRequest,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        return ProjectPermanentDeleteOut(**permanently_delete_project(
            session,
            project_id,
            body.confirmation,
        ))


@app.get("/project/{project_id}/export")
def export_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    _: Optional[str] = Depends(require_auth),
):
    path, filename = build_project_export(project_id)
    background_tasks.add_task(path.unlink, missing_ok=True)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        headers=PROTECTED_FILE_HEADERS,
        background=background_tasks,
    )


@app.get("/project/{project_id}/items", response_model=List[AssetOut])
def list_project_items(
    project_id: str,
    response: Response,
    q: Optional[str] = Query(default=None, max_length=200),
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    machine_id: Optional[str] = None,
    machine_scope: Optional[MachineScope] = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        require_active_project(session, project_id)
        validate_machine_filter(session, machine_id, machine_scope)
        statement = apply_asset_filters(
            select(Asset),
            q,
            tags,
            None,
            project_id,
            False,
            machine_id,
            machine_scope,
        )
        assets = list(session.exec(
            statement.order_by(Asset.name, Asset.filename, Asset.id)
            .offset(offset)
            .limit(limit + 1)
        ))
        has_more = len(assets) > limit
        if has_more:
            assets = assets[:limit]
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str(offset + len(assets))
        return [to_out(asset) for asset in assets]


@app.get("/project/{project_id}/tags", response_model=List[str])
def list_project_tags(
    project_id: str,
    machine_id: Optional[str] = None,
    machine_scope: Optional[MachineScope] = None,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        require_active_project(session, project_id)
        validate_machine_filter(session, machine_id, machine_scope)
        rows = list(session.exec(apply_asset_filters(
            select(Asset.tags_json),
            None,
            None,
            None,
            project_id,
            False,
            machine_id,
            machine_scope,
        )))
    found: set[str] = set()
    for raw in rows:
        try:
            parsed = json.loads(raw or "[]")
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, list):
            found.update(tag.strip() for tag in parsed if isinstance(tag, str) and tag.strip())
    return sorted(found, key=str.casefold)


@app.get("/project/{project_id}/candidates", response_model=List[AssetOut])
def list_project_candidates(
    project_id: str,
    response: Response,
    q: Optional[str] = Query(default=None, max_length=200),
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    machine_id: Optional[str] = None,
    machine_scope: Optional[MachineScope] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        require_active_project(session, project_id)
        validate_machine_filter(session, machine_id, machine_scope)
        membership_exists = select(ProjectMembership.asset_id).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.asset_id == Asset.id,
        ).exists()
        statement = apply_asset_filters(
            select(Asset).where(~membership_exists),
            q,
            tags,
            None,
            None,
            False,
            machine_id,
            machine_scope,
        )
        assets = list(session.exec(
            statement.order_by(Asset.name, Asset.filename, Asset.id)
            .offset(offset)
            .limit(limit + 1)
        ))
        has_more = len(assets) > limit
        if has_more:
            assets = assets[:limit]
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str(offset + len(assets))
        return [to_out(asset) for asset in assets]


@app.post(
    "/project/{project_id}/items/{asset_id}",
    response_model=ProjectMembershipOut,
    status_code=201,
)
def add_project_item(
    project_id: str,
    asset_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        membership = add_project_membership(session, project_id, asset_id)
        return ProjectMembershipOut(
            project_id=membership.project_id,
            asset_id=membership.asset_id,
            created_at=membership.created_at,
        )


@app.delete("/project/{project_id}/items/{asset_id}")
def remove_project_item(
    project_id: str,
    asset_id: str,
    confirm_relationship_cleanup: bool = Query(default=False),
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        remove_project_membership(
            session,
            project_id,
            asset_id,
            confirm_relationship_cleanup=confirm_relationship_cleanup,
        )
    return {"ok": True}


@app.get(
    "/project/{project_id}/relationships",
    response_model=List[ProjectRelationshipOut],
)
def list_project_relationships(
    project_id: str,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        rows = list_active_relationships(
            session,
            project_id,
            limit=limit,
            offset=offset,
        )
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str(offset + len(rows))
        return [
            relationship_to_out(relationship, source, target)
            for relationship, source, target in rows
        ]


@app.post(
    "/project/{project_id}/relationships",
    response_model=ProjectRelationshipOut,
    status_code=201,
)
def create_project_relationship(
    project_id: str,
    body: ProjectRelationshipCreate,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        relationship = create_relationship(session, project_id, body)
        source = session.get(Asset, relationship.source_asset_id)
        target = session.get(Asset, relationship.target_asset_id)
        return relationship_to_out(relationship, source, target)


@app.delete("/project/{project_id}/relationships/{relationship_id}")
def delete_project_relationship(
    project_id: str,
    relationship_id: str,
    _: Optional[str] = Depends(require_auth),
):
    with Session(engine) as session:
        delete_relationship(session, project_id, relationship_id)
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
