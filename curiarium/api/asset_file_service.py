import json
import logging
import mimetypes
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

import audit
import seams
from db import STORAGE, engine
from file_utils import mime_from_content_type, sanitize_filename
from models import Asset, AssetFile
from multipart_stream import StreamedUpload
from prepared_print import inspect_prepared_print, is_prepared_print_filename, prepared_print_stub

log = logging.getLogger(__name__)

# Inline previews are deliberately narrow: the browser renders exactly these
# types and nothing else. Text-ish types are served as `text/plain` so a stored
# `.html` or `.svg` can never become script in this origin (see
# `preview_media_type`).
PREVIEW_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"})
PREVIEW_TEXT_TYPES = frozenset({"application/json", "application/xml", "text/xml", "application/x-yaml"})
PREVIEW_TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"
UNPREVIEWABLE_DETAIL = "This file type cannot be previewed"

MAX_SUPPORTING_FILENAME_LENGTH = 200


def managed_asset_file_path(asset_file: AssetFile) -> Path:
    candidate = (STORAGE / asset_file.storage_path).resolve()
    root = STORAGE.resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Related file resolved outside storage")
    return candidate


def _supporting_rows(session: Session, asset_id: str) -> List[AssetFile]:
    """The asset's supporting rows in display order: position, name, then id."""
    return list(session.exec(
        select(AssetFile)
        .where(AssetFile.asset_id == asset_id, AssetFile.role == "supporting")
        .order_by(AssetFile.position, AssetFile.filename, AssetFile.id)
    ))


def list_supporting_files(asset_id: str) -> List[AssetFile]:
    """The asset's visible files in display order."""
    with Session(engine) as session:
        return _supporting_rows(session, asset_id)


async def save_asset_file(asset_id: str, staged: StreamedUpload) -> Asset:
    safe_name = sanitize_filename(staged.filename or "supporting-file")
    role = "prepared" if is_prepared_print_filename(safe_name) else "supporting"
    mime = mime_from_content_type(staged.content_type or "", safe_name)
    return await run_in_threadpool(_store_asset_file, asset_id, staged, safe_name, role, mime)


def _store_asset_file(asset_id: str, staged: StreamedUpload, safe_name: str, role: str, mime: str) -> Asset:
    """Store a staged upload: row, move, inspect, then the parent asset update."""
    staging = staged.path

    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        record = AssetFile(
            asset_id=asset.id,
            filename=safe_name,
            mime=mime,
            role=role,
            storage_path="pending",
        )
        record.storage_path = f"bundles/{asset.id}/{record.id}/{safe_name}"
        session.add(record)
        session.commit()
        session.refresh(record)

    destination = managed_asset_file_path(record)
    moved = False
    try:
        # A failed mkdir must delete the pending row, so it belongs inside the
        # guarded block; no destination bytes exist yet, so nothing is unlinked.
        destination.parent.mkdir(parents=True, exist_ok=True)
        # asset_service imports this module at load time; importing its mover
        # lazily keeps the dependency one-way inside this function.
        from asset_service import move_managed_file

        move_managed_file(staging, destination)
        moved = True
        size = staged.size

        metadata: Optional[dict] = None
        if role == "prepared" or safe_name.lower().endswith(".3mf"):
            try:
                metadata = inspect_prepared_print(destination, safe_name)
            except Exception as exc:
                # The bytes are already stored: a parser failure only costs the
                # metadata, and the filename keeps the row's prepared role.
                log.warning(
                    "Prepared-print inspection failed for %s: %s; keeping the stored file",
                    destination,
                    exc,
                    exc_info=True,
                )
                metadata = None
        if metadata:
            role = "prepared"
        old_prepared_path: Optional[Path] = None
        with Session(engine) as session:
            db_record = session.get(AssetFile, record.id)
            asset = session.get(Asset, asset_id)
            if not db_record or not asset:
                raise HTTPException(404)
            if role == "supporting":
                # The caps are checked in this write transaction, so two uploads
                # racing on the same model cannot both pass the last slot.
                _check_supporting_file_limits(session, asset, db_record.id, size)
                db_record.position = _next_supporting_position(session, asset.id, db_record.id)
            db_record.size = size
            db_record.role = role
            db_record.metadata_json = json.dumps(metadata) if metadata else None
            if role == "prepared":
                if asset.prepared_file_id and asset.prepared_file_id != db_record.id:
                    old_prepared = session.get(AssetFile, asset.prepared_file_id)
                    if old_prepared:
                        old_prepared_path = managed_asset_file_path(old_prepared)
                asset.prepared_file_id = db_record.id
                asset.prepared_metadata_json = db_record.metadata_json or json.dumps(prepared_print_stub(safe_name))
            else:
                asset.supporting_file_count = int(asset.supporting_file_count or 0) + 1
            session.add(db_record)
            session.add(asset)
            if old_prepared_path:
                session.delete(old_prepared)
            session.commit()
            session.refresh(asset)

        if old_prepared_path:
            try:
                old_prepared_path.unlink(missing_ok=True)
                _prune_bundle_dirs(old_prepared_path.parent)
            except OSError:
                pass
        return asset
    except Exception:
        # Only remove a destination this upload actually moved into place: a
        # move rejected with 409 means the existing bytes belong to someone else.
        if moved:
            destination.unlink(missing_ok=True)
            _prune_bundle_dirs(destination.parent)
        with Session(engine) as session:
            failed = session.get(AssetFile, record.id)
            if failed:
                session.delete(failed)
                session.commit()
        raise
    finally:
        staging.unlink(missing_ok=True)


def size_limit_label(limit: int) -> str:
    """A byte cap phrased the way the 413 messages and the UI read it."""
    if limit >= 1024 * 1024:
        return f"{limit // (1024 * 1024)} MB"
    return f"{limit} byte" if limit == 1 else f"{limit} bytes"


def _supporting_file_size_total(session: Session, asset_id: str, exclude_file_id: str) -> int:
    """Stored bytes across this asset's supporting rows, minus the row being written.

    The record is excluded because the caller compares the *existing* total
    against the cap before assigning the new size.
    """
    statement = select(func.coalesce(func.sum(AssetFile.size), 0)).where(
        AssetFile.asset_id == asset_id,
        AssetFile.role == "supporting",
        AssetFile.id != exclude_file_id,
    )
    return int(session.exec(statement).one() or 0)


def _check_supporting_file_limits(session: Session, asset: Asset, file_id: str, size: int) -> None:
    """Raise 413 when this upload would break the count or the total cap.

    Called inside the write transaction so the caps hold against concurrent
    uploads, and before `size`/`role` are assigned so a rejected upload leaves
    the row exactly as the first transaction created it - the caller's cleanup
    then deletes it and unlinks the staged bytes.
    """
    max_count = seams.asset_file_max_count()
    if max_count:
        existing_count = int(asset.supporting_file_count or 0)
        if existing_count >= max_count:
            raise HTTPException(
                status_code=413,
                detail=f"This model already has the maximum {max_count} supporting files",
            )
    total_limit = seams.asset_file_total_max_bytes()
    if total_limit:
        existing_total = _supporting_file_size_total(session, asset.id, file_id)
        if existing_total + size > total_limit:
            raise HTTPException(
                status_code=413,
                detail=(
                    "Supporting files for this model would exceed the "
                    f"{size_limit_label(total_limit)} total limit"
                ),
            )


def _next_supporting_position(session: Session, asset_id: str, exclude_file_id: str) -> int:
    """One past the last supporting row, so a new upload lands at the end."""
    current_max = session.exec(
        select(func.max(AssetFile.position)).where(
            AssetFile.asset_id == asset_id,
            AssetFile.role == "supporting",
            AssetFile.id != exclude_file_id,
        )
    ).one()
    return 0 if current_max is None else int(current_max) + 1


def _clean_supporting_filename(raw: str) -> str:
    """Trim and validate a display name; a rename never touches the bytes."""
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A supporting file name cannot be empty")
    if "/" in name or "\\" in name:
        raise HTTPException(
            status_code=400,
            detail="A supporting file name cannot contain a path separator",
        )
    if "\x00" in name:
        raise HTTPException(status_code=400, detail="A supporting file name cannot contain a NUL character")
    if name in {".", ".."}:
        raise HTTPException(status_code=400, detail="A supporting file name cannot be '.' or '..'")
    if len(name) > MAX_SUPPORTING_FILENAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"A supporting file name cannot be longer than {MAX_SUPPORTING_FILENAME_LENGTH} characters",
        )
    return name


def rename_supporting_file(
    asset_id: str,
    file_id: str,
    filename: str,
    *,
    audit_ctx: Optional[audit.AuditContext],
) -> AssetFile:
    """Change one supporting file's display name; the stored bytes never move.

    The name is display-only: `storage_path`, `mime` and the bytes on disk are
    untouched, so a rename is a metadata edit that can never lose a file. A
    duplicate (case-insensitive) name on the same asset is a 409 rather than a
    second file with the same label, and an unchanged name writes no audit row.
    """
    new_name = _clean_supporting_filename(filename)
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        record = session.get(AssetFile, file_id)
        if not asset or not record or record.asset_id != asset_id or record.role != "supporting":
            raise HTTPException(404)
        if record.filename == new_name:
            return record
        duplicate = session.exec(
            select(AssetFile).where(
                AssetFile.asset_id == asset_id,
                AssetFile.role == "supporting",
                AssetFile.id != file_id,
                func.lower(AssetFile.filename) == new_name.lower(),
            )
        ).first()
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="A supporting file with that name already exists on this model",
            )
        previous_name = record.filename
        record.filename = new_name
        audit.stage(
            session,
            audit_ctx,
            audit.Event(
                audit.ASSET_FILE_RENAME,
                asset_id,
                {"file_id": file_id, "from": previous_name, "to": new_name},
            ),
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def reorder_supporting_files(
    asset_id: str,
    file_ids: List[str],
    *,
    audit_ctx: Optional[audit.AuditContext],
) -> List[AssetFile]:
    """Rewrite the display order to `file_ids`; a stale list is a 409.

    The supplied ids must be exactly the asset's current supporting set: a
    shorter, longer or different list means the caller is looking at something
    that changed since it loaded, and guessing would silently drop a file from
    the order. An unchanged order writes no audit row, like every other no-op.
    """
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        ordered_ids = list(file_ids)
        if len(set(ordered_ids)) != len(ordered_ids):
            raise HTTPException(status_code=400, detail="A file appears more than once in the new order")
        rows = _supporting_rows(session, asset_id)
        if set(ordered_ids) != {row.id for row in rows}:
            raise HTTPException(
                status_code=409,
                detail="Supporting file list changed; reload and try again",
            )
        if ordered_ids == [row.id for row in rows]:
            return rows
        by_id = {row.id: row for row in rows}
        for position, row_id in enumerate(ordered_ids):
            by_id[row_id].position = position
            session.add(by_id[row_id])
        audit.stage(
            session,
            audit_ctx,
            audit.Event(audit.ASSET_FILE_REORDER, asset_id, {"order": ordered_ids}),
        )
        session.commit()
        # Re-read rather than returning the expired instances: commit expires
        # them, and the session is about to close.
        return _supporting_rows(session, asset_id)


def supporting_file_limits(asset_id: str) -> dict:
    """What this asset has, and the caps in force, for the upload UI.

    `max_* = 0` means that cap is disabled, so a client must read 0 as
    "unlimited" rather than "no files allowed".
    """
    with Session(engine) as session:
        if not session.get(Asset, asset_id):
            raise HTTPException(404)
        count, total = session.exec(
            select(
                func.count(AssetFile.id),
                func.coalesce(func.sum(AssetFile.size), 0),
            ).where(AssetFile.asset_id == asset_id, AssetFile.role == "supporting")
        ).one()
    return {
        "count": int(count or 0),
        "total_bytes": int(total or 0),
        "max_count": seams.asset_file_max_count(),
        # The route enforces the tighter of the import and supporting caps.
        "max_file_bytes": seams.asset_file_upload_max_bytes(),
        "max_total_bytes": seams.asset_file_total_max_bytes(),
    }


def preview_media_type(record: AssetFile) -> Optional[str]:
    """The media type to serve this record inline with, or None when it is not previewable.

    The decision keys off the stored `mime` first, because that is what the
    uploader declared and what the row will keep; the extension is only a
    fallback for a row stored as `application/octet-stream`. Everything outside
    the allow-list - SVG above all - is refused, and text-ish types are served
    as `text/plain` so a stored document cannot execute in this origin.
    """
    media_type = (record.mime or "").split(";")[0].strip().lower()
    if not media_type or media_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(record.filename or "")
        media_type = (guessed or "").split(";")[0].strip().lower()
    if media_type == "application/pdf":
        return media_type
    if media_type in PREVIEW_IMAGE_TYPES:
        return media_type
    if media_type.startswith("text/") or media_type in PREVIEW_TEXT_TYPES:
        return PREVIEW_TEXT_MEDIA_TYPE
    return None


def delete_supporting_file(asset_id: str, file_id: str, *, audit_ctx: Optional[audit.AuditContext]) -> Asset:
    path: Optional[Path] = None
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        record = session.get(AssetFile, file_id)
        if not asset or not record or record.asset_id != asset_id or record.role != "supporting":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        asset.supporting_file_count = max(0, int(asset.supporting_file_count or 0) - 1)
        audit.stage(
            session,
            audit_ctx,
            audit.Event(audit.ASSET_FILE_DELETE, asset_id, {"file_id": file_id, "filename": record.filename}),
        )
        session.add(asset)
        session.delete(record)
        session.commit()
        session.refresh(asset)
    if path:
        try:
            path.unlink(missing_ok=True)
            _prune_bundle_dirs(path.parent)
        except OSError:
            pass
    return asset


def delete_all_asset_files(asset_id: str) -> None:
    with Session(engine) as session:
        rows = list(session.exec(select(AssetFile).where(AssetFile.asset_id == asset_id)))
        paths = [managed_asset_file_path(row) for row in rows]
        for row in rows:
            session.delete(row)
        session.commit()
    for path in paths:
        try:
            path.unlink(missing_ok=True)
            _prune_bundle_dirs(path.parent)
        except OSError:
            pass


def delete_prepared_file(asset_id: str, *, audit_ctx: Optional[audit.AuditContext]) -> Asset:
    path: Optional[Path] = None
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset or not asset.prepared_file_id:
            raise HTTPException(404)
        record = session.get(AssetFile, asset.prepared_file_id)
        if not record or record.asset_id != asset_id or record.role != "prepared":
            raise HTTPException(404)
        path = managed_asset_file_path(record)

        from asset_service import inspect_asset_prepared_print

        embedded = inspect_asset_prepared_print(asset)
        audit.stage(session, audit_ctx, audit.Event(audit.ASSET_PREPARED_PRINT_DELETE, asset_id))
        asset.prepared_file_id = None
        asset.prepared_metadata_json = json.dumps(embedded) if embedded else None
        session.add(asset)
        session.delete(record)
        session.commit()
        session.refresh(asset)
    if path:
        try:
            path.unlink(missing_ok=True)
            _prune_bundle_dirs(path.parent)
        except OSError:
            pass
    return asset


def _prune_bundle_dirs(start: Path) -> None:
    root = (STORAGE / "bundles").resolve()
    current = start
    while current.exists() and current.resolve() != root and root in current.resolve().parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def backfill_prepared_print_metadata() -> None:
    with Session(engine) as session:
        assets = list(session.exec(
            select(Asset).where(
                or_(
                    Asset.filename.like("%.3mf"),
                    Asset.filename.like("%.gcode"),
                    Asset.filename.like("%.gco"),
                    Asset.filename.like("%.bgcode"),
                ),
                Asset.prepared_metadata_json == None,  # noqa: E711
            )
        ))
    for asset in assets:
        from asset_service import managed_asset_path

        source = managed_asset_path(asset)
        if not source.exists() and asset.source_path:
            source = Path(asset.source_path)
        metadata = inspect_prepared_print(source, asset.filename) if source.exists() else None
        if not metadata:
            continue
        with Session(engine) as session:
            current = session.get(Asset, asset.id)
            if current and not current.prepared_metadata_json:
                current.prepared_metadata_json = json.dumps(metadata)
                session.add(current)
                session.commit()
