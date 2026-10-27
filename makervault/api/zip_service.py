import os
from pathlib import Path
from typing import List, Optional
from zipfile import ZipFile

from fastapi import HTTPException
from sqlmodel import Session, select

from asset_service import cleanup_asset, create_asset_record, ensure_model_thumbnail, finalize_asset_record, managed_asset_path, save_thumb
from config import IMPORT_MAX_BYTES, IMPORT_ZIP_MAX_BYTES
from db import engine
from file_utils import mime_from_content_type, sanitize_filename
from folder_service import validate_parent_folder
from models import Asset, Folder
from schemas import ImportZipExtractRequest


def normalize_zip_entry_path(name: str) -> Optional[str]:
    cleaned = (name or "").replace("\\", "/").lstrip("/")
    if not cleaned or cleaned.endswith("/"):
        return None
    parts = [part for part in cleaned.split("/") if part]
    if not parts or any(part == ".." for part in parts):
        return None
    parts = [part for part in parts if part != "."]
    return "/".join(parts)


def sanitize_folder_name(name: str) -> str:
    cleaned = (name or "").replace("\x00", "").strip()
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    return cleaned or "folder"


def list_zip_entries(zip_path: Path) -> List[dict]:
    entries: List[dict] = []
    with ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = normalize_zip_entry_path(info.filename)
            if not name:
                continue
            entries.append({"path": name, "size": int(info.file_size or 0)})
    entries.sort(key=lambda entry: entry["path"])
    return entries


def get_or_create_folder(session: Session, parent_id: Optional[str], parent_key: str, name: str, cache: dict) -> str:
    key = f"{parent_key}/{name}"
    cached = cache.get(key)
    if cached:
        return cached
    existing = session.exec(select(Folder).where(Folder.parent_id == parent_id, Folder.name == name)).first()
    if existing:
        cache[key] = existing.id
        return existing.id
    folder = Folder(name=name, tags_json="[]", parent_id=parent_id)
    session.add(folder)
    session.commit()
    session.refresh(folder)
    cache[key] = folder.id
    return folder.id


def resolve_zip_folder_id(session: Session, base_folder_id: Optional[str], entry_path: str, cache: dict) -> Optional[str]:
    segments = [segment for segment in entry_path.split("/")[:-1] if segment]
    if not segments:
        return base_folder_id
    target_id = base_folder_id
    parent_key = base_folder_id or "root"
    for segment in segments:
        safe = sanitize_folder_name(segment)
        if not safe:
            continue
        target_id = get_or_create_folder(session, target_id, parent_key, safe, cache)
        parent_key = f"{parent_key}/{safe}"
    return target_id


def extract_zip_entries_to_assets(zip_path: Path, selections: List[str], body: ImportZipExtractRequest) -> tuple[List[Asset], List[str]]:
    normalized = [normalize_zip_entry_path(name) for name in selections]
    ordered: List[str] = []
    seen = set()
    for name in normalized:
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    if not ordered:
        raise HTTPException(status_code=400, detail="No zip entries selected")
    assets: List[Asset] = []
    failed: List[str] = []
    created_ids: List[str] = []
    total_written = 0
    with ZipFile(zip_path) as zf, Session(engine) as session:
        entries = {}
        for info in zf.infolist():
            name = normalize_zip_entry_path(info.filename)
            if not name:
                continue
            entries[name] = info
        # Declared sizes come from the archive and are not trusted: this preflight
        # rejects an oversized selection before anything is written, and the write
        # loop below re-checks the bytes it actually streams.
        oversized: set[str] = set()
        declared_total = 0
        for entry_name in ordered:
            info = entries.get(entry_name)
            if not info or info.is_dir():
                continue
            declared = int(info.file_size or 0)
            if declared > IMPORT_MAX_BYTES:
                oversized.add(entry_name)
                continue
            declared_total += declared
        if declared_total > IMPORT_ZIP_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Selected zip entries expand to {declared_total} bytes; "
                    f"the limit is {IMPORT_ZIP_MAX_BYTES} bytes (IMPORT_ZIP_MAX_MB)"
                ),
            )
        if body.folder_id:
            validate_parent_folder(session, body.folder_id)
        folder_cache: dict = {}
        for entry_name in ordered:
            info = entries.get(entry_name)
            if not info or info.is_dir() or entry_name in oversized:
                failed.append(entry_name)
                continue
            target_folder_id = resolve_zip_folder_id(session, body.folder_id, entry_name, folder_cache)
            filename = sanitize_filename(os.path.basename(entry_name))
            mime = mime_from_content_type("", filename)
            asset: Optional[Asset] = None
            try:
                asset = create_asset_record(filename, mime, body.title, body.notes, body.tags, target_folder_id)
                created_ids.append(asset.id)
                dest = managed_asset_path(asset)
                dest.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with zf.open(info) as src, open(dest, "wb") as out:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > IMPORT_MAX_BYTES:
                            raise ValueError("Extracted file exceeds size limit")
                        total_written += len(chunk)
                        if total_written > IMPORT_ZIP_MAX_BYTES:
                            # The archive lied about its declared sizes; abandon the
                            # whole selection rather than keep filling the storage.
                            for created_id in created_ids:
                                cleanup_asset(created_id)
                            raise HTTPException(
                                status_code=413,
                                detail=(
                                    f"Selected zip entries expand beyond {total_written} bytes; "
                                    f"the limit is {IMPORT_ZIP_MAX_BYTES} bytes (IMPORT_ZIP_MAX_MB)"
                                ),
                            )
                        out.write(chunk)
                if (mime or "").startswith("image/") and dest.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                    save_thumb(asset.id, dest)
                elif dest.suffix.lower() == ".3mf":
                    ensure_model_thumbnail(asset.id, dest)
                refreshed = finalize_asset_record(asset.id, size, mime)
                assets.append(refreshed or asset)
            except HTTPException as exc:
                # A name or path conflict is one bad entry, not a bad zip: report it
                # in `failed` and keep extracting. Every other HTTPException (a bad
                # storage template, say) applies to the whole request.
                if asset is not None:
                    cleanup_asset(asset.id)
                if exc.status_code != 409:
                    raise
                failed.append(entry_name)
            except Exception:
                if asset is not None:
                    cleanup_asset(asset.id)
                failed.append(entry_name)
    return assets, failed
