import os
from pathlib import Path
from typing import List, Optional
from zipfile import ZipFile

from fastapi import HTTPException
from sqlmodel import Session, select

from asset_service import cleanup_asset, create_asset_record, ensure_model_thumbnail, finalize_asset_record, managed_asset_path, save_thumb
from archive_limits import (
    ArchiveLimitError,
    bounded_archive_infos,
    validate_archive_member,
    validate_selected_members,
)
from config import ARCHIVE_MAX_SELECTED
from db import engine
from file_utils import mime_from_content_type, sanitize_filename
from folder_service import validate_parent_folder
from models import Asset, Folder
from schemas import ImportZipExtractRequest
from resource_limits import stream_reader_to_file


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
        try:
            infos = bounded_archive_infos(zf)
        except ArchiveLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        seen = set()
        for info in infos:
            name = normalize_zip_entry_path(info.filename)
            if not name:
                continue
            try:
                validate_archive_member(info, enforce_file_size=False)
            except ArchiveLimitError as exc:
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            if name in seen:
                raise HTTPException(status_code=400, detail=f"Archive contains a duplicate path: {name}")
            seen.add(name)
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
    if len(ordered) > ARCHIVE_MAX_SELECTED:
        raise HTTPException(
            status_code=413,
            detail=f"Select no more than {ARCHIVE_MAX_SELECTED} archive entries at once",
        )
    assets: List[Asset] = []
    failed: List[str] = []
    with ZipFile(zip_path) as zf, Session(engine) as session:
        if body.folder_id:
            validate_parent_folder(session, body.folder_id)
        folder_cache: dict = {}
        try:
            infos = bounded_archive_infos(zf)
        except ArchiveLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        entries = {}
        for info in infos:
            name = normalize_zip_entry_path(info.filename)
            if not name:
                continue
            if name in entries:
                raise HTTPException(status_code=400, detail=f"Archive contains a duplicate path: {name}")
            entries[name] = info
        selected_infos = [entries[name] for name in ordered if name in entries and not entries[name].is_dir()]
        try:
            validate_selected_members(selected_infos)
        except ArchiveLimitError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        for entry_name in ordered:
            info = entries.get(entry_name)
            if not info or info.is_dir():
                failed.append(entry_name)
                continue
            target_folder_id = resolve_zip_folder_id(session, body.folder_id, entry_name, folder_cache)
            filename = sanitize_filename(os.path.basename(entry_name))
            mime = mime_from_content_type("", filename)
            asset = create_asset_record(filename, mime, body.title, body.notes, body.tags, target_folder_id)
            dest = managed_asset_path(asset)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                validate_archive_member(info)
                with zf.open(info) as src:
                    size = stream_reader_to_file(src, dest, "Extracted file")
                if (mime or "").startswith("image/") and dest.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                    save_thumb(asset.id, dest)
                elif dest.suffix.lower() == ".3mf":
                    ensure_model_thumbnail(asset.id, dest)
                refreshed = finalize_asset_record(asset.id, size, mime)
                assets.append(refreshed or asset)
            except Exception:
                cleanup_asset(asset.id)
                failed.append(entry_name)
    return assets, failed
