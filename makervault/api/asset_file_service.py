import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

import audit
from db import STORAGE, engine
from file_utils import mime_from_content_type, sanitize_filename
from models import Asset, AssetFile
from multipart_stream import StreamedUpload
from prepared_print import inspect_prepared_print, is_prepared_print_filename

log = logging.getLogger(__name__)


def managed_asset_file_path(asset_file: AssetFile) -> Path:
    candidate = (STORAGE / asset_file.storage_path).resolve()
    root = STORAGE.resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Related file resolved outside storage")
    return candidate


def list_supporting_files(asset_id: str) -> List[AssetFile]:
    with Session(engine) as session:
        return list(session.exec(
            select(AssetFile)
            .where(AssetFile.asset_id == asset_id, AssetFile.role == "supporting")
            .order_by(AssetFile.filename, AssetFile.id)
        ))


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
            db_record.size = size
            db_record.role = role
            db_record.metadata_json = json.dumps(metadata) if metadata else None
            if role == "prepared":
                if asset.prepared_file_id and asset.prepared_file_id != db_record.id:
                    old_prepared = session.get(AssetFile, asset.prepared_file_id)
                    if old_prepared:
                        old_prepared_path = managed_asset_file_path(old_prepared)
                asset.prepared_file_id = db_record.id
                asset.prepared_metadata_json = db_record.metadata_json or json.dumps({"format": "gcode"})
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
            select(Asset).where(Asset.filename.like("%.3mf"), Asset.prepared_metadata_json == None)  # noqa: E711
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
