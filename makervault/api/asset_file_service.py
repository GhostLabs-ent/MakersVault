import json
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, select

from db import STORAGE, engine
from file_utils import mime_from_content_type, sanitize_filename
from models import Asset, AssetFile
from prepared_print import inspect_prepared_print, is_prepared_print_filename
from resource_limits import stream_upload_to_file


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


async def save_asset_file(asset_id: str, upload: UploadFile) -> Asset:
    safe_name = sanitize_filename(upload.filename or "supporting-file")
    role = "prepared" if is_prepared_print_filename(safe_name) else "supporting"
    mime = mime_from_content_type(upload.content_type or "", safe_name)

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
    try:
        size = await stream_upload_to_file(upload, destination, "Related file")

        metadata = inspect_prepared_print(destination, safe_name) if role == "prepared" or safe_name.lower().endswith(".3mf") else None
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
        destination.unlink(missing_ok=True)
        _prune_bundle_dirs(destination.parent)
        with Session(engine) as session:
            failed = session.get(AssetFile, record.id)
            if failed:
                session.delete(failed)
                session.commit()
        raise


def delete_supporting_file(asset_id: str, file_id: str) -> Asset:
    path: Optional[Path] = None
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        record = session.get(AssetFile, file_id)
        if not asset or not record or record.asset_id != asset_id or record.role != "supporting":
            raise HTTPException(404)
        path = managed_asset_file_path(record)
        asset.supporting_file_count = max(0, int(asset.supporting_file_count or 0) - 1)
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


def delete_prepared_file(asset_id: str) -> Asset:
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
