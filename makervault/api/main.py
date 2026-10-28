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

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect

import accounts
import asset_service
import audit
import auth
import bulk_service
import folder_service
import login_throttle as login_throttle_module
import multipart_stream
import permissions
import project_service
import sessions
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
from auth import AuthContext, validate_auth_configuration
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
from models import Asset, AssetFile, AuditEvent, Folder, Project, ProjectAsset, User
from mount_import import mount_import_should_run, scan_mount_imports
from permissions import require_admin, require_read, require_write
from prepared_print import prepared_filename
from request_id import RequestIDMiddleware
from schemas import (
    AssetFileOut,
    AssetFolderUpdate,
    AssetMetaUpdate,
    AssetOut,
    AssetRename,
    AuditEventOut,
    AuditListOut,
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
    MeOut,
    MountImportSettings,
    MountImportSettingsOut,
    ProjectAssetsRequest,
    ProjectIn,
    ProjectMembersOut,
    ProjectOut,
    ProjectRemovalOut,
    ProjectUpdate,
    RefreshRequest,
    StorageSettings,
    StorageSettingsOut,
    TagUpdate,
    TrashEntryOut,
    TrashListOut,
    TrashPurgeOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from settings_service import (
    DEFAULT_STORAGE_TEMPLATE,
    STORAGE_TEMPLATE_KEY,
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
AUTH_NOT_CONFIGURED = "Authentication is not configured on the server"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_auth_configuration()
    # Fail at boot, not at the first request: a route that forgot its permission
    # level (or drifted from ROUTE_PERMISSIONS) is a security bug, so this check
    # refuses to start serving until it is fixed.
    permissions.assert_routes_classified(app)
    # Same contract one level down: a mutating route that emits no audit event
    # (and is not exempt with a reason) is a bug that must not reach production.
    audit.assert_audit_coverage()
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
    expose_headers=["X-Has-More", "X-Next-Offset", "X-Request-ID"],
)
app.add_middleware(RequestIDMiddleware)


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


def thumb_url_for(asset_id: Optional[str]) -> Optional[str]:
    """The versioned thumbnail URL for an asset, or None when nothing was generated.

    One helper for every `thumb_url`/`cover_thumb_url` field, so the versioned form
    (`?v=<st_mtime_ns>`, which makes the URL change when the thumbnail does) cannot
    drift between the asset and project serializers.
    """
    if not asset_id:
        return None
    path = THUMBS / f"{asset_id}.jpg"
    if not path.exists():
        return None
    return f"/thumb/{asset_id}.jpg?v={path.stat().st_mtime_ns}"


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
        thumb_url=thumb_url_for(a.id),
        folder_id=a.folder_id,
        storage_path=a.storage_path,
        missing_since=a.missing_since,
        supporting_file_count=int(a.supporting_file_count or 0),
        prepared_print=prepared,
        slicer_url=slicer_url,
        slicer_filename=(prepared_filename(a.name, prepared) if a.prepared_file_id else a.filename),
    )


def project_metadata(raw: Optional[str]) -> dict:
    """Parse the project's `metadata_json` TEXT column; anything but an object is {}."""
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def project_to_out(project: Project, asset_count: int, total_size: int) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        creator=project.creator,
        source_url=project.source_url,
        licence=project.licence,
        licence_url=project.licence_url,
        origin=project.origin,
        cover_asset_id=project.cover_asset_id,
        cover_thumb_url=thumb_url_for(project.cover_asset_id),
        asset_count=asset_count,
        total_size=total_size,
        metadata_json=project_metadata(project.metadata_json),
        created_at=project.created_at,
        updated_at=project.updated_at,
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


def zip_assets_response(
    assets: List[Asset],
    download_name: str,
    background: BackgroundTasks,
    folder_label_map: Optional[dict] = None,
    allow_empty: bool = False,
):
    """Stream the resolved assets as a zip; `allow_empty` is the project contract.

    A tag/folder/asset_ids selection that resolves to nothing is a 404 (the caller
    asked for files that are not there), while an existing project with no members
    is a valid empty zip: the project exists, its file set is simply empty.
    """
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
    if not files and not allow_empty:
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
    return {"ok": True, "auth_required": auth.AUTH_ENABLED}


@app.get("/settings/mount-import", response_model=MountImportSettingsOut)
def get_mount_import_settings(_: Optional[AuthContext] = Depends(require_admin)):
    return MountImportSettingsOut(
        enabled=get_mount_import_enabled(MOUNT_IMPORT_ENABLED),
        copy_files=get_mount_import_copy(MOUNT_IMPORT_COPY),
        path=MOUNT_IMPORT_PATH or None,
    )


@app.post("/settings/mount-import", response_model=MountImportSettingsOut)
def update_mount_import_settings(
    body: MountImportSettings,
    request: Request,
    context: Optional[AuthContext] = Depends(require_admin),
):
    # One session, one transaction: the two settings and the audit row commit or
    # roll back together.
    with Session(engine) as s:
        set_mount_import_enabled(body.enabled, session=s)
        set_mount_import_copy(body.copy_files, session=s)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(
                audit.SETTINGS_MOUNT_IMPORT_UPDATE,
                "mount_import",
                {"enabled": body.enabled, "copy_files": body.copy_files},
            ),
        )
        s.commit()
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
def get_storage_settings(_: Optional[AuthContext] = Depends(require_admin)):
    template = validate_storage_template(get_storage_template())
    return storage_settings_out(template)


@app.post("/settings/storage", response_model=StorageSettingsOut)
def update_storage_settings(
    body: StorageSettings,
    request: Request,
    context: Optional[AuthContext] = Depends(require_admin),
):
    template = validate_storage_template(body.template)
    previous = validate_storage_template(get_storage_template())
    # The template governs new uploads and imports only; existing files never move.
    with Session(engine) as s:
        set_storage_template(template, session=s)
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.SETTINGS_STORAGE_UPDATE, STORAGE_TEMPLATE_KEY, {"from": previous, "to": template}),
        )
        s.commit()
    return storage_settings_out(template)


@app.get("/library/scan", response_model=LibraryScanStatusOut)
def library_scan_status(_: Optional[AuthContext] = Depends(require_read)):
    return scan_status()


@app.post("/library/scan", response_model=LibraryScanStatusOut, status_code=202)
def library_scan_start(request: Request, context: Optional[AuthContext] = Depends(require_admin)):
    if not start_scan():
        raise HTTPException(status_code=409, detail="A library scan is already running")
    # The scan has no DB row to join: fail-loud, and the log line explains why a
    # request that started a scan returned an error.
    audit.record(audit.Event(audit.LIBRARY_SCAN_START, "library"), ctx=audit.context_for(request, context))
    return scan_status()


@app.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
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
    with Session(engine) as s:
        result = auth.login(
            s,
            body.username,
            body.password,
            user_agent=request.headers.get("user-agent"),
            client_ip=client_host,
        )
        if result is not None:
            # The login route has no AuthContext (it creates the principal), so
            # the actor comes from the session row `auth.login` just wrote. No
            # password, token or refresh token ever reaches the row.
            actor = audit.Actor(result.username, result.role, result.kind, result.user_id)
            audit.stage(
                s,
                audit.context_for_actor(request, actor),
                audit.Event(audit.LOGIN_SUCCEEDED, result.username, {"kind": result.kind, "client_ip": client_host}),
            )
        s.commit()
    if result is None:
        lockout_seconds = login_throttle_module.limiter.record_failure(username)
        log.warning("Failed login attempt for username %r from %s", username, client_host)
        if lockout_seconds:
            log.warning("Login throttled for username %r from %s (retry after %ss)", username, client_host, lockout_seconds)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    login_throttle_module.limiter.record_success(username)
    return LoginResponse(
        token=result.token,
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
    )


def presented_refresh_token(
    body: Optional[RefreshRequest],
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """The refresh token from the JSON body, or the documented Bearer fallback."""
    if body is not None and body.refresh_token:
        return body.refresh_token
    if credentials is not None:
        return credentials.credentials
    return None


@app.post("/refresh", response_model=LoginResponse)
def refresh_token(
    body: Optional[RefreshRequest] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth.auth_scheme),
):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    presented = presented_refresh_token(body, credentials)
    if not presented:
        raise HTTPException(status_code=401, detail="Unauthorized")
    token_hash = sessions.hash_refresh_token(presented)
    with Session(engine) as s:
        session_row = sessions.find_by_refresh_hash(s, token_hash)
        user = accounts.get_user(s, session_row.user_id) if session_row is not None else None
        if session_row is None or not sessions.is_refreshable(session_row, user):
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        refresh_token_value = sessions.rotate(s, session_row, access_ttl=auth.AUTH_ACCESS_TOKEN_TTL)
        if refresh_token_value is None:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        token = auth.create_access_token(session_row, sessions.role_for(session_row, user))
        s.commit()
    return LoginResponse(token=token, expires_in=auth.AUTH_ACCESS_TOKEN_TTL, refresh_token=refresh_token_value)


@app.post("/logout", status_code=204)
def logout(
    body: Optional[RefreshRequest] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth.auth_scheme),
):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    presented = presented_refresh_token(body, credentials)
    if presented:
        with Session(engine) as s:
            sessions.revoke_by_refresh_hash(s, sessions.hash_refresh_token(presented))
            s.commit()
    return Response(status_code=204)


@app.get("/me", response_model=MeOut)
def me(context: Optional[AuthContext] = Depends(require_read)):
    if not auth.AUTH_ENABLED or context is None:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        user = accounts.get_user(s, context.user_id)
    return MeOut(
        id=context.user_id,
        username=context.username,
        email=user.email if user is not None else None,
        role=context.role,
        disabled=bool(user.disabled) if user is not None else False,
        kind=context.kind,
    )


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        disabled=bool(user.disabled),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@app.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, context: Optional[AuthContext] = Depends(require_admin)):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        try:
            user = accounts.create_user(s, body.username, body.password, body.email, body.role)
        except accounts.AccountError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        audit.stage(
            s,
            audit.context_for(request, context),
            audit.Event(audit.USER_CREATE, user.username, {"role": user.role, "user_id": user.id}),
        )
        # The first account replaces the env break-glass admin, so its sessions
        # die with it. Same transaction as the insert: either both or neither.
        sessions.revoke_break_glass(s)
        result = user_out(user)
        s.commit()
    return result


@app.get("/users", response_model=List[UserOut])
def list_users(_: Optional[AuthContext] = Depends(require_admin)):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        users = accounts.list_users(s)
    return [user_out(user) for user in users]


@app.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, request: Request, context: Optional[AuthContext] = Depends(require_admin)):
    if not auth.AUTH_ENABLED:
        raise HTTPException(status_code=503, detail=AUTH_NOT_CONFIGURED)
    with Session(engine) as s:
        # Snapshot before the update: both reads share the session's identity map,
        # so the row object is mutated in place and the old values must be kept.
        before = accounts.get_user(s, user_id)
        previous_role = before.role if before is not None else None
        previous_disabled = bool(before.disabled) if before is not None else False
        try:
            user = accounts.update_user(s, user_id, disabled=body.disabled, role=body.role)
        except accounts.AccountError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        events = []
        if previous_role is not None and user.role != previous_role:
            events.append(audit.Event(audit.USER_ROLE_CHANGE, user.username, {"from": previous_role, "to": user.role}))
        if bool(user.disabled) != previous_disabled:
            action = audit.USER_DISABLE if user.disabled else audit.USER_ENABLE
            events.append(
                audit.Event(action, user.username, {"from": previous_disabled, "to": bool(user.disabled)})
            )
        audit.stage(s, audit.context_for(request, context), *events)
        result = user_out(user)
        s.commit()
    return result


def audit_event_to_out(row: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=row.id,
        created_at=row.created_at,
        actor=row.actor,
        actor_user_id=row.actor_user_id,
        actor_role=row.actor_role,
        actor_kind=row.actor_kind,
        action=row.action,
        target=row.target,
        detail=json.loads(row.detail_json) if row.detail_json else None,
        request_id=row.request_id,
        method=row.method,
        path=row.path,
    )


@app.get("/audit", response_model=AuditListOut)
def list_audit_events(
    actor: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Optional[AuthContext] = Depends(require_admin),
):
    with Session(engine) as s:
        rows, total = audit.list_events(
            s, actor=actor, action=action, target=target, since=since, until=until, limit=limit, offset=offset
        )
        events = [audit_event_to_out(row) for row in rows]
    return AuditListOut(events=events, total=total, limit=limit, offset=offset)


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
async def upload(request: Request, _: Optional[AuthContext] = Depends(require_write)):
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
def import_from_link(body: ImportRequest, _: Optional[AuthContext] = Depends(require_write)):
    url = normalize_import_url(body.url)
    asset = import_asset_from_url(url, body)
    return to_out(asset)


@app.post("/import/inspect", response_model=ImportInspectOut)
def inspect_import_link(body: ImportRequest, _: Optional[AuthContext] = Depends(require_write)):
    url = normalize_import_url(body.url)
    resp, final_url = open_import_response(url, body)
    with resp:
        filename = build_import_filename(final_url, resp.headers, body.filename)
        mime = mime_from_content_type(resp.headers.get("Content-Type", ""), filename)
    is_zip = Path(filename).suffix.lower() == ".zip"
    return ImportInspectOut(filename=filename, mime=mime, is_zip=is_zip)


@app.post("/import/zip/entries", response_model=ImportZipEntriesOut)
def list_import_zip_entries(body: ImportZipEntriesRequest, _: Optional[AuthContext] = Depends(require_write)):
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
def import_zip_entries(body: ImportZipExtractRequest, _: Optional[AuthContext] = Depends(require_write)):
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


@app.get("/asset/{asset_id}/files", response_model=List[AssetFileOut])
def get_supporting_files(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as session:
        if not session.get(Asset, asset_id):
            raise HTTPException(404)
    return [asset_file_to_out(row) for row in list_supporting_files(asset_id)]


@app.post("/asset/{asset_id}/files", response_model=AssetOut, openapi_extra=multipart_form_openapi())
async def upload_related_file(
    asset_id: str,
    request: Request,
    _: Optional[AuthContext] = Depends(require_write),
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
def download_supporting_file(asset_id: str, file_id: str, _: Optional[AuthContext] = Depends(require_read)):
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
def remove_supporting_file(
    asset_id: str,
    file_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(delete_supporting_file(asset_id, file_id, audit_ctx=audit.context_for(request, context)))


@app.get("/asset/{asset_id}/prepared-print")
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


@app.delete("/asset/{asset_id}/prepared-print", response_model=AssetOut)
def remove_prepared_print(
    asset_id: str,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(delete_prepared_file(asset_id, audit_ctx=audit.context_for(request, context)))


@app.get("/thumb/{asset_id}.jpg")
def get_thumb(asset_id: str, _: Optional[AuthContext] = Depends(require_read)):
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


def asset_page(session: Session, stmt, response: Response, limit: Optional[int], offset: Optional[int]) -> List[Asset]:
    """The one pagination contract: at most `limit` rows plus the two headers.

    Shared by `GET /assets` and `GET /project/{project_id}/assets`, so the two
    listings cannot disagree about `X-Has-More`, `X-Next-Offset`, or about sending
    no pagination header at all when `limit` is absent. The extra `+ 1` row is how
    `has_more` is known without a second count query.
    """
    if limit is not None:
        stmt = stmt.limit(limit + 1)
        if offset:
            stmt = stmt.offset(offset)
    assets = list(session.exec(stmt))

    has_more = False
    if limit is not None and len(assets) > limit:
        has_more = True
        assets = assets[:limit]
    if limit is not None and response is not None:
        response.headers["X-Has-More"] = "true" if has_more else "false"
        response.headers["X-Next-Offset"] = str((offset or 0) + len(assets))
    return assets


@app.get("/assets", response_model=List[AssetOut])
def list_assets(
    response: Response,
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    _: Optional[AuthContext] = Depends(require_read),
):
    with Session(engine) as s:
        stmt = apply_asset_filters(select(Asset), q, tags, folder_id)
        stmt = stmt.order_by(Asset.name, Asset.filename, Asset.id)
        assets = asset_page(s, stmt, response, limit, offset)

    out: List[AssetOut] = [to_out(a) for a in assets]
    return out


@app.get("/tags", response_model=List[str])
def list_tags(
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    folder_id: Optional[str] = None,
    _: Optional[AuthContext] = Depends(require_read),
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

    return zip_assets_response(assets, download_name, background, folder_map, allow_empty=project is not None)


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


@app.post("/assets/batch/folder", response_model=BatchFolderOut)
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


@app.post("/assets/batch/delete", response_model=BatchDeleteOut)
def batch_delete_assets(
    body: BatchDeleteRequest,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    asset_ids = require_asset_ids(body.asset_ids)
    deleted, failed = bulk_service.delete_assets(asset_ids, audit_ctx=audit.context_for(request, context))
    return BatchDeleteOut(deleted=deleted, failed=failed)


@app.post("/asset/{asset_id}/tags", response_model=AssetOut)
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


@app.post("/asset/{asset_id}/meta", response_model=AssetOut)
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


@app.post("/asset/{asset_id}/rename", response_model=AssetOut)
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


@app.delete("/asset/{asset_id}")
def delete_asset(asset_id: str, request: Request, context: Optional[AuthContext] = Depends(require_write)):
    delete_asset_permanently(asset_id, audit_ctx=audit.context_for(request, context))
    return {"ok": True}


# Folder endpoints ----------------------------------------------


@app.get("/folders", response_model=List[FolderOut])
def list_folders(_: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        rows = list(s.exec(select(Folder)))
    return [folder_to_out(f) for f in rows]


@app.post("/folders", response_model=FolderOut)
def create_folder(body: FolderIn, _: Optional[AuthContext] = Depends(require_write)):
    with Session(engine) as s:
        f = folder_service.create_folder(s, body.name, json.dumps(body.tags), body.parent_id)
    return folder_to_out(f)


@app.patch("/folder/{folder_id}", response_model=FolderOut)
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


@app.delete("/folder/{folder_id}")
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
        if scan_status().get("running"):
            raise HTTPException(status_code=409, detail="A library scan is running; try again when it finishes")
        result = trash_service.trash_folder(s, folder, audit_ctx=audit.context_for(request, context))
    return {"ok": True, **result}


@app.get("/folder/{folder_id}/delete-preview", response_model=FolderDeletePreviewOut)
def folder_delete_preview(folder_id: str, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        folder = s.get(Folder, folder_id)
        if not folder:
            raise HTTPException(404)
        return trash_service.folder_delete_preview(s, folder)


@app.get("/folder/{folder_id}/download")
def download_folder(folder_id: str, background: BackgroundTasks, _: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        folder = s.get(Folder, folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        assets = list(s.exec(select(Asset).where(Asset.folder_id == folder_id)))
        folder_map = {folder_id: folder.name}
    download_name = f"{(folder.name or 'folder').replace(' ', '_')[:50] or 'folder'}.zip"
    return zip_assets_response(assets, download_name, background, folder_map)


# Project endpoints ---------------------------------------------
# A project is a row and a join table: it owns no storage path and no bytes, so
# no route here creates, moves or deletes a file. The templates are deliberately
# asymmetric (`/projects` for the collection, `/project/{project_id}` for one),
# matching `/folders` vs `/folder/{folder_id}`.


@app.get("/projects", response_model=List[ProjectOut])
def list_projects(_: Optional[AuthContext] = Depends(require_read)):
    with Session(engine) as s:
        rows = project_service.list_projects(s)
    return [project_to_out(project, count, total_size) for project, count, total_size in rows]


@app.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, _: Optional[AuthContext] = Depends(require_write)):
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
        asset_count, total_size = project_service.member_stats(s, project.id)
    return project_to_out(project, asset_count, total_size)


@app.patch("/project/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
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
        asset_count, total_size = project_service.member_stats(s, project.id)
        result = project_to_out(project, asset_count, total_size)
    return result


@app.delete("/project/{project_id}")
def delete_project(project_id: str, request: Request, context: Optional[AuthContext] = Depends(require_write)):
    with Session(engine) as s:
        project_service.delete_project(
            s,
            project_service.get_project(s, project_id),
            audit_ctx=audit.context_for(request, context),
        )
    return {"ok": True}


@app.get("/project/{project_id}/assets", response_model=List[AssetOut])
def list_project_assets(
    project_id: str,
    response: Response,
    q: Optional[str] = None,
    tags: Optional[str] = Query(default=None, description="Comma-separated tags"),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    _: Optional[AuthContext] = Depends(require_read),
):
    """The project's members, ordered and paged exactly like `GET /assets`.

    `folder_id` is not a parameter here on purpose: membership, not location,
    decides what is listed.
    """
    with Session(engine) as s:
        project_service.get_project(s, project_id)
        stmt = select(Asset).join(ProjectAsset, ProjectAsset.asset_id == Asset.id).where(ProjectAsset.project_id == project_id)
        stmt = apply_asset_filters(stmt, q, tags, None)
        stmt = stmt.order_by(Asset.name, Asset.filename, Asset.id)
        assets = asset_page(s, stmt, response, limit, offset)
    return [to_out(a) for a in assets]


@app.post("/project/{project_id}/assets", response_model=ProjectMembersOut)
def add_project_assets(
    project_id: str,
    body: ProjectAssetsRequest,
    _: Optional[AuthContext] = Depends(require_write),
):
    """Add memberships; unknown asset ids are reported per id (200 partial)."""
    asset_ids = require_asset_ids(body.asset_ids)
    added, skipped, failed = project_service.add_assets(project_id, asset_ids)
    return ProjectMembersOut(added=added, skipped=skipped, failed=failed)


@app.delete("/project/{project_id}/assets", response_model=ProjectRemovalOut)
def remove_project_assets(
    project_id: str,
    body: ProjectAssetsRequest,
    _: Optional[AuthContext] = Depends(require_write),
):
    """Remove memberships; assets and files are never touched.

    This is the one DELETE route in the API that carries a JSON body, so a client
    must send it explicitly - `client.request("DELETE", path, json=...)` - because
    some convenience helpers drop a body on DELETE.
    """
    asset_ids = require_asset_ids(body.asset_ids)
    removed, skipped, failed = project_service.remove_assets(project_id, asset_ids)
    return ProjectRemovalOut(removed=removed, skipped=skipped, failed=failed)


# Trash endpoints -----------------------------------------------


@app.get("/trash", response_model=TrashListOut)
def list_trash(_: Optional[AuthContext] = Depends(require_read)):
    entries = trash_service.list_entries()
    return TrashListOut(
        entries=[TrashEntryOut(**entry) for entry in entries],
        total_size=sum(entry["size"] for entry in entries),
    )


@app.post("/trash/purge", response_model=TrashPurgeOut)
def purge_trash(
    request: Request,
    older_than_days: Optional[int] = Query(None, ge=0),
    context: Optional[AuthContext] = Depends(require_admin),
):
    result = trash_service.purge(older_than_days)
    # The bytes are already gone and there is no row to roll back: fail-loud.
    audit.record(audit.Event(audit.TRASH_PURGE, "trash", dict(result)), ctx=audit.context_for(request, context))
    return TrashPurgeOut(**result)


@app.post("/asset/{asset_id}/folder", response_model=AssetOut)
def update_asset_folder(
    asset_id: str,
    body: AssetFolderUpdate,
    request: Request,
    context: Optional[AuthContext] = Depends(require_write),
):
    return to_out(
        move_asset_to_folder_by_id(asset_id, body.folder_id, audit_ctx=audit.context_for(request, context))
    )
