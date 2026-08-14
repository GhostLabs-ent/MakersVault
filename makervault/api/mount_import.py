import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from asset_service import cleanup_asset, create_asset_record, ensure_model_thumbnail, finalize_asset_record, managed_asset_path, save_thumb
from config import (
    DEFAULT_MOUNT_IMPORT_EXTS,
    IMPORT_MAX_BYTES,
    MOUNT_IMPORT_EXTS_RAW,
    MOUNT_IMPORT_INCLUDE_HIDDEN,
    MOUNT_IMPORT_PATH,
    MOUNT_IMPORT_COPY,
)
from db import STORAGE, engine
from file_utils import guess_mime_from_path, sanitize_filename
from models import Asset
from settings_service import get_mount_import_copy
from zip_service import resolve_zip_folder_id
from resource_limits import reject_declared_size, stream_reader_to_file


def resolve_safe_mount_file(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve(strict=True)
    candidate_absolute = candidate.absolute()
    try:
        relative = candidate_absolute.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Mounted source is outside the configured root") from exc

    current = root_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Mounted source contains a symbolic link")

    resolved = candidate.resolve(strict=True)
    if resolved == root_resolved or root_resolved not in resolved.parents:
        raise ValueError("Mounted source resolved outside the configured root")
    if not resolved.is_file():
        raise ValueError("Mounted source is not a regular file")
    return resolved


@contextmanager
def open_safe_mount_file(root: Path, candidate: Path):
    expected = resolve_safe_mount_file(root, candidate)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(candidate, flags)
    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ValueError("Mounted source is not a regular file")
        proc_path = Path(f"/proc/self/fd/{descriptor}")
        opened_path = proc_path.resolve() if proc_path.exists() else candidate.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
        if opened_path != expected or root_resolved not in opened_path.parents:
            raise ValueError("Mounted source changed while it was being opened")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            yield source, opened_stat.st_size, opened_path
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def parse_mount_import_exts(raw: str) -> Optional[set]:
    if not raw:
        return set(DEFAULT_MOUNT_IMPORT_EXTS)
    lowered = raw.strip().lower()
    if lowered == "*":
        return None
    parts = re.split(r"[,\s]+", lowered)
    exts = set()
    for part in parts:
        if not part:
            continue
        ext = part if part.startswith(".") else f".{part}"
        exts.add(ext)
    return exts or set(DEFAULT_MOUNT_IMPORT_EXTS)


def should_skip_mount_entry(name: str) -> bool:
    return not MOUNT_IMPORT_INCLUDE_HIDDEN and name.startswith(".")


def scan_mount_imports() -> None:
    root_raw = MOUNT_IMPORT_PATH
    if not root_raw:
        return
    root = Path(root_raw)
    if not root.exists() or not root.is_dir():
        print(f"[mount-import] Skipping: mount path not found: {root_raw}")
        return

    allowed_exts = parse_mount_import_exts(MOUNT_IMPORT_EXTS_RAW)
    copy_files = get_mount_import_copy(MOUNT_IMPORT_COPY)
    root_abs = root.resolve()
    root_prefix = root_abs.as_posix().rstrip("/")
    storage_abs = STORAGE.resolve()
    skip_storage_dirs = root_abs == storage_abs
    imported = 0
    skipped = 0
    failed = 0

    print(f"[mount-import] Scanning {root_abs}...")
    with Session(engine) as session:
        existing_sources: set = set()
        if root_prefix:
            existing_sources = set(
                session.exec(
                    select(Asset.source_path).where(Asset.source_path.like(f"{root_prefix}/%"))
                ).all()
            )
        else:
            existing_sources = set(
                session.exec(
                    select(Asset.source_path).where(Asset.source_path.is_not(None))
                ).all()
            )
        asset_ids = set()
        if skip_storage_dirs:
            asset_ids = set(session.exec(select(Asset.id)).all())

        folder_cache: dict = {}
        for dirpath, dirnames, filenames in os.walk(root_abs):
            rel_dir = Path(dirpath).relative_to(root_abs)
            dirnames[:] = [d for d in dirnames if not should_skip_mount_entry(d)]
            if skip_storage_dirs:
                dirnames[:] = [d for d in dirnames if d != "thumbs" and d not in asset_ids]

            for filename in filenames:
                if should_skip_mount_entry(filename):
                    continue
                path = Path(dirpath) / filename
                try:
                    resolved_path = resolve_safe_mount_file(root_abs, path)
                except (OSError, ValueError):
                    failed += 1
                    continue
                ext = path.suffix.lower()
                if allowed_exts is not None and ext not in allowed_exts:
                    continue

                rel_path = (rel_dir / filename).as_posix() if rel_dir != Path(".") else filename
                source_path = resolved_path.as_posix()
                if source_path in existing_sources:
                    skipped += 1
                    continue
                try:
                    size = resolved_path.stat().st_size
                except OSError:
                    failed += 1
                    continue
                try:
                    reject_declared_size(size, "Mounted file", IMPORT_MAX_BYTES)
                except Exception:
                    failed += 1
                    continue

                folder_id = resolve_zip_folder_id(session, None, rel_path, folder_cache)
                safe_name = sanitize_filename(filename)
                mime = guess_mime_from_path(path)
                asset = create_asset_record(
                    safe_name,
                    mime,
                    None,
                    None,
                    [],
                    folder_id,
                    source_path=source_path,
                )
                try:
                    if copy_files:
                        dest = managed_asset_path(asset)
                        with open_safe_mount_file(root_abs, path) as (source, opened_size, _):
                            reject_declared_size(opened_size, "Mounted file", IMPORT_MAX_BYTES)
                            copied_size = stream_reader_to_file(
                                source,
                                dest,
                                "Mounted file",
                                IMPORT_MAX_BYTES,
                            )
                        if copied_size != opened_size:
                            raise ValueError("Mounted source changed while it was copied")
                        if (mime or "").startswith("image/") and dest.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                            save_thumb(asset.id, dest)
                        elif dest.suffix.lower() == ".3mf":
                            ensure_model_thumbnail(asset.id, dest)
                    else:
                        with open_safe_mount_file(root_abs, path) as (source, opened_size, opened_path):
                            reject_declared_size(opened_size, "Mounted file", IMPORT_MAX_BYTES)
                            descriptor_path = Path(f"/proc/self/fd/{source.fileno()}")
                            preview_path = descriptor_path if descriptor_path.exists() else opened_path
                            if (mime or "").startswith("image/") and opened_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                                save_thumb(asset.id, preview_path)
                            elif opened_path.suffix.lower() == ".3mf":
                                ensure_model_thumbnail(asset.id, preview_path, opened_path.name)
                        if opened_size != size:
                            raise ValueError("Mounted source changed while it was indexed")
                    finalize_asset_record(asset.id, size, mime)
                    imported += 1
                    existing_sources.add(source_path)
                except Exception:
                    cleanup_asset(asset.id)
                    failed += 1

    print(f"[mount-import] Done. Imported {imported}, skipped {skipped}, failed {failed}.")
