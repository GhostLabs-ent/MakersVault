import os
import re
import stat
import json
import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

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
from models import Asset, MountScan
from settings_service import get_mount_import_copy
from zip_service import resolve_zip_folder_id
from resource_limits import digest_reader, reject_declared_size, stream_reader_to_file


MOUNT_SCAN_FAILURE_LIMIT = 50
MOUNT_SCAN_HISTORY_LIMIT = 100
MOUNT_SCAN_FAILURE_PATH_LIMIT = 500
MOUNT_SCAN_FAILURE_REASON_LIMIT = 240
@dataclass
class MountScanResult:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    failure_details: list[dict[str, str]] = field(default_factory=list)
    failure_details_omitted: int = 0
    fatal: bool = False

    def add_failure(self, path: str, reason: str) -> None:
        self.failed += 1
        detail = {
            "path": (path or ".")[:MOUNT_SCAN_FAILURE_PATH_LIMIT],
            "reason": (reason or "Import failed")[:MOUNT_SCAN_FAILURE_REASON_LIMIT],
        }
        if len(self.failure_details) < MOUNT_SCAN_FAILURE_LIMIT:
            self.failure_details.append(detail)
        else:
            self.failure_details_omitted += 1


_scan_coordinator_lock = threading.Lock()
_active_scan_id: Optional[str] = None


def mount_scan_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def mount_scan_failure_reason(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    message = str(exc).strip()
    if message:
        return message
    return f"{type(exc).__name__} while importing mounted file"


def relative_mount_scan_failure_reason(exc: Exception, root: Path) -> str:
    reason = mount_scan_failure_reason(exc)
    root_text = root.as_posix().rstrip("/")
    return reason.replace(root_text, ".") if root_text else reason


def mount_scan_failure_details(scan: MountScan) -> list[dict[str, str]]:
    try:
        raw = json.loads(scan.failure_details_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    details: list[dict[str, str]] = []
    for item in raw[:MOUNT_SCAN_FAILURE_LIMIT]:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        reason = item.get("reason")
        if isinstance(path, str) and isinstance(reason, str):
            details.append({
                "path": path[:MOUNT_SCAN_FAILURE_PATH_LIMIT],
                "reason": reason[:MOUNT_SCAN_FAILURE_REASON_LIMIT],
            })
    return details


def latest_mount_scan() -> Optional[MountScan]:
    with Session(engine) as session:
        return session.exec(
            select(MountScan).order_by(MountScan.started_at.desc(), MountScan.id.desc())
        ).first()


def get_mount_scan(scan_id: str) -> Optional[MountScan]:
    with Session(engine) as session:
        return session.get(MountScan, scan_id)


def recover_interrupted_mount_scans() -> int:
    recovered = 0
    now = mount_scan_timestamp()
    with Session(engine) as session:
        rows = list(session.exec(select(MountScan).where(MountScan.status == "running")).all())
        for row in rows:
            row.status = "interrupted"
            row.finished_at = now
            details = mount_scan_failure_details(row)
            detail = {
                "path": ".",
                "reason": "Scan interrupted by an API restart; run the scan again.",
            }
            if len(details) < MOUNT_SCAN_FAILURE_LIMIT:
                details.append(detail)
            else:
                row.failure_details_omitted += 1
            row.failure_details_json = json.dumps(details)
            session.add(row)
            recovered += 1
        if recovered:
            session.commit()
    return recovered


def _create_mount_scan(trigger: str, root_path: str, copy_files: bool) -> MountScan:
    row = MountScan(
        trigger=trigger,
        status="running",
        mode="copy" if copy_files else "index_in_place",
        root_path=root_path,
        started_at=mount_scan_timestamp(),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        older = list(
            session.exec(
                select(MountScan)
                .where(MountScan.status != "running")
                .order_by(MountScan.started_at.desc(), MountScan.id.desc())
                .offset(MOUNT_SCAN_HISTORY_LIMIT - 1)
            ).all()
        )
        for previous in older:
            session.delete(previous)
        if older:
            session.commit()
            session.refresh(row)
        return row


def _finish_mount_scan(scan_id: str, result: MountScanResult) -> None:
    with Session(engine) as session:
        row = session.get(MountScan, scan_id)
        if not row:
            return
        row.status = (
            "failed"
            if result.fatal
            else "completed_with_failures"
            if result.failed
            else "completed"
        )
        row.finished_at = mount_scan_timestamp()
        row.imported = result.imported
        row.skipped = result.skipped
        row.failed = result.failed
        row.failure_details_json = json.dumps(result.failure_details)
        row.failure_details_omitted = result.failure_details_omitted
        session.add(row)
        session.commit()


def _run_mount_scan(scan_id: str, root_path: str, copy_files: bool) -> None:
    global _active_scan_id
    try:
        try:
            result = scan_mount_imports(root_path=root_path, copy_files=copy_files)
        except Exception as exc:
            result = MountScanResult(fatal=True)
            result.add_failure(".", mount_scan_failure_reason(exc))
        _finish_mount_scan(scan_id, result)
    finally:
        with _scan_coordinator_lock:
            if _active_scan_id == scan_id:
                _active_scan_id = None


def start_mount_scan(trigger: str = "manual") -> Tuple[MountScan, bool]:
    global _active_scan_id
    root_path = (MOUNT_IMPORT_PATH or "").strip()
    if not root_path:
        raise ValueError("No mounted import path is configured")
    copy_files = get_mount_import_copy(MOUNT_IMPORT_COPY)
    with _scan_coordinator_lock:
        if _active_scan_id:
            active = get_mount_scan(_active_scan_id)
            if active and active.status == "running":
                return active, False
            _active_scan_id = None
        scan = _create_mount_scan(trigger, root_path, copy_files)
        _active_scan_id = scan.id
        threading.Thread(
            target=_run_mount_scan,
            args=(scan.id, root_path, copy_files),
            daemon=True,
            name=f"mount-scan-{scan.id[:8]}",
        ).start()
        return scan, True


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


def scan_mount_imports(
    root_path: Optional[str] = None,
    copy_files: Optional[bool] = None,
) -> MountScanResult:
    result = MountScanResult()
    root_raw = MOUNT_IMPORT_PATH if root_path is None else root_path
    if not root_raw:
        result.fatal = True
        result.add_failure(".", "No mounted import path is configured")
        return result
    root = Path(root_raw)
    if not root.exists() or not root.is_dir():
        result.fatal = True
        result.add_failure(".", "Mounted import path is unavailable or is not a directory")
        return result

    allowed_exts = parse_mount_import_exts(MOUNT_IMPORT_EXTS_RAW)
    if copy_files is None:
        copy_files = get_mount_import_copy(MOUNT_IMPORT_COPY)
    root_abs = root.resolve()
    root_prefix = root_abs.as_posix().rstrip("/")
    storage_abs = STORAGE.resolve()
    skip_storage_dirs = root_abs == storage_abs
    print(f"[mount-import] Scanning {root_abs}...")
    try:
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

            def record_walk_error(exc: OSError) -> None:
                error_path = Path(getattr(exc, "filename", "") or root_abs)
                try:
                    relative = error_path.resolve().relative_to(root_abs).as_posix()
                except (OSError, ValueError):
                    relative = "."
                result.add_failure(relative or ".", relative_mount_scan_failure_reason(exc, root_abs))

            for dirpath, dirnames, filenames in os.walk(root_abs, onerror=record_walk_error):
                rel_dir = Path(dirpath).relative_to(root_abs)
                dirnames[:] = [d for d in dirnames if not should_skip_mount_entry(d)]
                if skip_storage_dirs:
                    dirnames[:] = [d for d in dirnames if d != "thumbs" and d not in asset_ids]

                for filename in filenames:
                    if should_skip_mount_entry(filename):
                        continue
                    path = Path(dirpath) / filename
                    ext = path.suffix.lower()
                    if allowed_exts is not None and ext not in allowed_exts:
                        continue
                    rel_path = (rel_dir / filename).as_posix() if rel_dir != Path(".") else filename
                    asset: Optional[Asset] = None
                    try:
                        resolved_path = resolve_safe_mount_file(root_abs, path)
                        source_path = resolved_path.as_posix()
                        if source_path in existing_sources:
                            result.skipped += 1
                            continue
                        size = resolved_path.stat().st_size
                        reject_declared_size(size, "Mounted file", IMPORT_MAX_BYTES)
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
                        if copy_files:
                            dest = managed_asset_path(asset)
                            digest = hashlib.sha256()
                            with open_safe_mount_file(root_abs, path) as (source, opened_size, _):
                                reject_declared_size(opened_size, "Mounted file", IMPORT_MAX_BYTES)
                                copied_size = stream_reader_to_file(
                                    source,
                                    dest,
                                    "Mounted file",
                                    IMPORT_MAX_BYTES,
                                    digest=digest,
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
                                digested_size, content_sha256 = digest_reader(
                                    source,
                                    "Mounted file",
                                    IMPORT_MAX_BYTES,
                                )
                                if digested_size != opened_size:
                                    raise ValueError("Mounted source changed while it was hashed")
                                descriptor_path = Path(f"/proc/self/fd/{source.fileno()}")
                                preview_path = descriptor_path if descriptor_path.exists() else opened_path
                                if (mime or "").startswith("image/") and opened_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                                    save_thumb(asset.id, preview_path)
                                elif opened_path.suffix.lower() == ".3mf":
                                    ensure_model_thumbnail(asset.id, preview_path, opened_path.name)
                            if opened_size != size:
                                raise ValueError("Mounted source changed while it was indexed")
                        finalize_asset_record(
                            asset.id,
                            size,
                            mime,
                            digest.hexdigest() if copy_files else content_sha256,
                        )
                        result.imported += 1
                        existing_sources.add(source_path)
                    except Exception as exc:
                        if asset is not None:
                            cleanup_asset(asset.id)
                        result.add_failure(rel_path, relative_mount_scan_failure_reason(exc, root_abs))
    except Exception as exc:
        result.fatal = True
        result.add_failure(".", relative_mount_scan_failure_reason(exc, root_abs))

    print(
        f"[mount-import] Done. Imported {result.imported}, "
        f"skipped {result.skipped}, failed {result.failed}."
    )
    return result
