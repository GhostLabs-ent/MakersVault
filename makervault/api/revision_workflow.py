import hashlib
import json
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, select

from asset_service import (
    extract_3mf_thumbnail_path,
    filename_for_model_name,
    managed_thumbnail_path,
    save_thumb_path,
)
from config import FILE_MAX_BYTES, PREVIEW_POLICY_VERSION
from content_store import InvalidStoreKey
from db import LOCAL_CONTENT_STORE, engine
from file_utils import mime_from_content_type, sanitize_filename
from models import ArtifactRevision, Asset, AssetFile, MachineProfile
from prepared_print import inspect_prepared_print
from preview_policy import automatic_preview_disposition
from resource_limits import stream_reader_to_file, stream_upload_to_file
from revision_service import current_revision, revision_timestamp
from trash_service import require_active_asset


revision_mutation_lock = threading.Lock()


@dataclass(frozen=True)
class RevisionMutationResult:
    asset: Asset
    revision: ArtifactRevision
    created: bool


def revision_storage_path(asset_id: str, revision_id: str, filename: str) -> str:
    return f"revisions/{asset_id}/{revision_id}/{sanitize_filename(filename)}"


def managed_revision_path(revision: ArtifactRevision) -> Optional[Path]:
    if not revision.storage_path:
        return None
    try:
        candidate = LOCAL_CONTENT_STORE.local_path(revision.storage_path)
    except InvalidStoreKey:
        raise HTTPException(status_code=400, detail="Revision path resolved outside storage")
    return candidate


def resolve_revision_content_path(revision: ArtifactRevision) -> Optional[Path]:
    managed = managed_revision_path(revision)
    if managed and managed.is_file():
        return managed
    if not revision.source_path:
        return None
    import mount_import

    root_raw = (mount_import.MOUNT_IMPORT_PATH or "").strip()
    if not root_raw:
        return None
    try:
        return mount_import.resolve_safe_mount_file(
            Path(root_raw), Path(revision.source_path)
        )
    except (OSError, ValueError):
        return None


def _staging_path(operation_id: str, filename: str) -> Path:
    root = LOCAL_CONTENT_STORE.local_path(".revision-staging")
    candidate = (root / operation_id / sanitize_filename(filename)).resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Revision staging path is invalid")
    return candidate


def _prune_revision_dirs(start: Path) -> None:
    root = LOCAL_CONTENT_STORE.root
    current = start
    while current.exists() and current.resolve() != root and root in current.resolve().parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _current_revision_or_conflict(session: Session, asset: Asset) -> ArtifactRevision:
    revision = current_revision(session, asset)
    if not revision:
        raise HTTPException(status_code=409, detail="Current revision is unavailable")
    return revision


def _next_revision_number(session: Session, asset_id: str) -> int:
    latest = session.exec(
        select(ArtifactRevision)
        .where(ArtifactRevision.asset_id == asset_id)
        .order_by(ArtifactRevision.revision_number.desc())
    ).first()
    return int(latest.revision_number if latest else 0) + 1


def _preserve_legacy_thumbnail(
    asset: Asset,
    revision: ArtifactRevision,
) -> tuple[Optional[Path], Optional[str]]:
    legacy_relative = f"thumbs/{asset.id}.jpg"
    if revision.preview_thumb_path != legacy_relative:
        return None, None
    legacy = managed_thumbnail_path(legacy_relative)
    if not legacy.is_file():
        return None, None
    historical_relative = f"thumbs/revisions/{revision.id}.jpg"
    historical = managed_thumbnail_path(historical_relative)
    historical.parent.mkdir(parents=True, exist_ok=True)
    if not historical.exists():
        shutil.copy2(legacy, historical)
    revision.preview_thumb_path = historical_relative
    return historical, legacy_relative


def _create_revision_thumbnail(
    revision_id: str,
    source: Path,
    filename: str,
    mime: str,
) -> Optional[str]:
    relative = f"thumbs/revisions/{revision_id}.jpg"
    if (mime or "").startswith("image/") and source.suffix.lower() in {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp",
    }:
        return save_thumb_path(relative, source)
    if source.suffix.lower() == ".3mf":
        return extract_3mf_thumbnail_path(relative, source, filename)
    return None


def _apply_current_projection(asset: Asset, revision: ArtifactRevision) -> None:
    asset.current_revision_id = revision.id
    asset.filename = revision.filename
    asset.mime = revision.mime
    asset.size = revision.size
    asset.storage_path = revision.storage_path
    asset.source_path = revision.source_path
    asset.prepared_file_id = revision.prepared_file_id
    asset.prepared_metadata_json = revision.prepared_metadata_json
    asset.prepared_machine_id = revision.prepared_machine_id
    asset.preview_status = revision.preview_status
    asset.preview_reason = revision.preview_reason
    asset.preview_attempts = revision.preview_attempts
    asset.preview_policy_version = revision.preview_policy_version
    asset.preview_updated_at = revision.preview_updated_at
    asset.preview_source = revision.preview_source
    asset.current_thumb_path = revision.preview_thumb_path


def _finalize_staged_revision(
    *,
    asset_id: str,
    expected_current_id: str,
    staged: Path,
    filename: str,
    mime: str,
    size: int,
    sha256: str,
    change_note: Optional[str],
    origin_revision_id: Optional[str] = None,
    prepared_metadata_json: Optional[str] = None,
    prepared_machine_id: Optional[str] = None,
    copied_thumbnail: Optional[Path] = None,
    prepared_source: Optional[AssetFile] = None,
) -> RevisionMutationResult:
    revision_id = str(uuid.uuid4())
    final_relative = revision_storage_path(asset_id, revision_id, filename)
    try:
        final = LOCAL_CONTENT_STORE.local_path(final_relative)
    except InvalidStoreKey:
        raise HTTPException(status_code=400, detail="Revision path resolved outside storage")
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise HTTPException(status_code=409, detail="Revision storage path already exists")
    staged.replace(final)

    thumb_relative: Optional[str] = None
    created_thumb: Optional[Path] = None
    preserved_thumb: Optional[Path] = None
    legacy_thumb_relative: Optional[str] = None
    prepared_copy: Optional[Path] = None
    try:
        if copied_thumbnail and copied_thumbnail.is_file():
            thumb_relative = f"thumbs/revisions/{revision_id}.jpg"
            created_thumb = managed_thumbnail_path(thumb_relative)
            created_thumb.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copied_thumbnail, created_thumb)
        else:
            thumb_relative = _create_revision_thumbnail(revision_id, final, filename, mime)
            created_thumb = managed_thumbnail_path(thumb_relative) if thumb_relative else None

        preview_status, preview_reason = automatic_preview_disposition(
            filename, size, bool(thumb_relative)
        )
        prepared_metadata = prepared_metadata_json
        if prepared_metadata is None and filename.lower().endswith(".3mf"):
            inspected = inspect_prepared_print(final, filename)
            prepared_metadata = json.dumps(inspected) if inspected else None

        prepared_record: Optional[AssetFile] = None
        if prepared_source:
            from asset_file_service import managed_asset_file_path

            source = managed_asset_file_path(prepared_source)
            if not source.is_file():
                raise HTTPException(status_code=409, detail="Prepared print payload is unavailable")
            prepared_record = AssetFile(
                asset_id=asset_id,
                filename=prepared_source.filename,
                mime=prepared_source.mime,
                size=prepared_source.size,
                role="prepared",
                storage_path="pending",
                metadata_json=prepared_source.metadata_json,
                revision_id=revision_id,
            )
            prepared_record.storage_path = (
                f"bundles/{asset_id}/{prepared_record.id}/{sanitize_filename(prepared_record.filename)}"
            )
            prepared_copy = managed_asset_file_path(prepared_record)
            prepared_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, prepared_copy)

        with Session(engine) as session:
            asset = require_active_asset(session, asset_id)
            old_current = _current_revision_or_conflict(session, asset)
            if old_current.id != expected_current_id:
                raise HTTPException(status_code=409, detail="Current revision changed; retry replacement")
            revision_number = _next_revision_number(session, asset_id)
            preserved_thumb, legacy_thumb_relative = _preserve_legacy_thumbnail(asset, old_current)
            session.add(old_current)

            revision = ArtifactRevision(
                id=revision_id,
                asset_id=asset.id,
                revision_number=revision_number,
                created_at=revision_timestamp(),
                origin_revision_id=origin_revision_id,
                filename=filename,
                mime=mime,
                size=size,
                sha256=sha256,
                observed_sha256=sha256,
                content_state="ready",
                content_checked_at=revision_timestamp(),
                storage_path=final_relative,
                source_path=None,
                change_note=(change_note or "").strip() or None,
                prepared_file_id=prepared_record.id if prepared_record else None,
                prepared_metadata_json=prepared_metadata,
                prepared_machine_id=prepared_machine_id,
                preview_status=preview_status,
                preview_reason=preview_reason,
                preview_attempts=0,
                preview_policy_version=PREVIEW_POLICY_VERSION,
                preview_updated_at=revision_timestamp(),
                preview_source="embedded" if thumb_relative else None,
                preview_thumb_path=thumb_relative,
            )
            if prepared_record:
                session.add(prepared_record)
            _apply_current_projection(asset, revision)
            session.add(revision)
            session.add(asset)
            session.commit()
            session.refresh(asset)
            session.refresh(revision)

        if legacy_thumb_relative:
            managed_thumbnail_path(legacy_thumb_relative).unlink(missing_ok=True)
        return RevisionMutationResult(asset=asset, revision=revision, created=True)
    except Exception:
        final.unlink(missing_ok=True)
        _prune_revision_dirs(final.parent)
        if created_thumb:
            created_thumb.unlink(missing_ok=True)
            _prune_revision_dirs(created_thumb.parent)
        if preserved_thumb:
            preserved_thumb.unlink(missing_ok=True)
            _prune_revision_dirs(preserved_thumb.parent)
        if prepared_copy:
            prepared_copy.unlink(missing_ok=True)
            _prune_revision_dirs(prepared_copy.parent)
        raise


async def create_revision_from_upload(
    asset_id: str,
    upload: UploadFile,
    change_note: Optional[str] = None,
    expected_current_revision_id: Optional[str] = None,
) -> RevisionMutationResult:
    with Session(engine) as session:
        asset = require_active_asset(session, asset_id)
        current = _current_revision_or_conflict(session, asset)
        if expected_current_revision_id and current.id != expected_current_revision_id:
            raise HTTPException(status_code=409, detail="Current revision changed; refresh and retry")
        expected_current_id = current.id
        safe_upload_name = sanitize_filename(upload.filename or asset.filename)
        filename = filename_for_model_name(asset.name, safe_upload_name)
        mime = mime_from_content_type(upload.content_type or "", filename)

    operation_id = str(uuid.uuid4())
    staged = _staging_path(operation_id, filename)
    digest = hashlib.sha256()
    try:
        size = await stream_upload_to_file(
            upload,
            staged,
            "Revision file",
            digest=digest,
        )
        sha256 = digest.hexdigest()
        if current.sha256 == sha256 and int(current.size or 0) == size:
            staged.unlink(missing_ok=True)
            _prune_revision_dirs(staged.parent)
            return RevisionMutationResult(asset=asset, revision=current, created=False)
        with revision_mutation_lock:
            return _finalize_staged_revision(
                asset_id=asset_id,
                expected_current_id=expected_current_id,
                staged=staged,
                filename=filename,
                mime=mime,
                size=size,
                sha256=sha256,
                change_note=change_note,
            )
    except Exception:
        staged.unlink(missing_ok=True)
        _prune_revision_dirs(staged.parent)
        raise


def _copy_revision_to_staging(
    revision: ArtifactRevision,
    staged: Path,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    source_path = resolve_revision_content_path(revision)
    if source_path and source_path.is_file():
        with source_path.open("rb") as source:
            size = stream_reader_to_file(
                source,
                staged,
                "Restored revision",
                max_bytes=max(FILE_MAX_BYTES, int(revision.size or 0)),
                digest=digest,
            )
        return size, digest.hexdigest()
    raise HTTPException(status_code=409, detail="Revision content is unavailable")


def restore_revision(
    asset_id: str,
    revision_id: str,
    change_note: Optional[str] = None,
) -> RevisionMutationResult:
    with revision_mutation_lock:
        with Session(engine) as session:
            asset = require_active_asset(session, asset_id)
            target = session.get(ArtifactRevision, revision_id)
            if not target or target.asset_id != asset_id:
                raise HTTPException(404)
            current = _current_revision_or_conflict(session, asset)
            expected_current_id = current.id
            if target.id == current.id:
                return RevisionMutationResult(asset=asset, revision=current, created=False)
            target_snapshot = target.model_copy(deep=True)
            prepared_machine_id = (
                target.prepared_machine_id
                if target.prepared_machine_id
                and session.get(MachineProfile, target.prepared_machine_id)
                else None
            )
            prepared_snapshot = None
            if target.prepared_file_id:
                prepared = session.get(AssetFile, target.prepared_file_id)
                if not prepared or prepared.asset_id != asset_id or prepared.role != "prepared":
                    raise HTTPException(status_code=409, detail="Prepared print payload is unavailable")
                prepared_snapshot = prepared.model_copy(deep=True)

        operation_id = str(uuid.uuid4())
        staged = _staging_path(operation_id, target_snapshot.filename)
        try:
            size, sha256 = _copy_revision_to_staging(target_snapshot, staged)
            if (
                size != int(target_snapshot.size or 0)
                or not target_snapshot.sha256
                or sha256 != target_snapshot.sha256
            ):
                with Session(engine) as session:
                    changed = session.get(ArtifactRevision, revision_id)
                    if changed:
                        changed.observed_sha256 = sha256
                        changed.content_state = "changed"
                        changed.content_reason = (
                            "size_mismatch" if size != int(changed.size or 0) else "digest_mismatch"
                        )
                        changed.content_checked_at = revision_timestamp()
                        session.add(changed)
                        session.commit()
                raise HTTPException(status_code=409, detail="Historical revision bytes have changed")

            target_thumb = (
                managed_thumbnail_path(target_snapshot.preview_thumb_path)
                if target_snapshot.preview_thumb_path
                else None
            )
            return _finalize_staged_revision(
                asset_id=asset_id,
                expected_current_id=expected_current_id,
                staged=staged,
                filename=target_snapshot.filename,
                mime=target_snapshot.mime,
                size=size,
                sha256=sha256,
                change_note=change_note or f"Restored revision {target_snapshot.revision_number}",
                origin_revision_id=target_snapshot.id,
                prepared_metadata_json=target_snapshot.prepared_metadata_json,
                prepared_machine_id=prepared_machine_id,
                copied_thumbnail=target_thumb if target_thumb and target_thumb.is_file() else None,
                prepared_source=prepared_snapshot,
            )
        except Exception:
            staged.unlink(missing_ok=True)
            _prune_revision_dirs(staged.parent)
            raise
