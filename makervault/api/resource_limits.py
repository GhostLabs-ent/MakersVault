import shutil
from pathlib import Path
from typing import Any, BinaryIO, Optional

from fastapi import HTTPException, UploadFile

from config import FILE_MAX_BYTES, STORAGE_RESERVE_BYTES


CHUNK_BYTES = 1024 * 1024


def _existing_parent(path: Path) -> Path:
    candidate = path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def ensure_storage_reserve(destination: Path, incoming_bytes: int = 0) -> None:
    if STORAGE_RESERVE_BYTES <= 0:
        return
    usage = shutil.disk_usage(_existing_parent(destination))
    if usage.free - max(0, incoming_bytes) < STORAGE_RESERVE_BYTES:
        try:
            from trash_service import reclaim_for_capacity

            reclaim_for_capacity(
                _existing_parent(destination),
                max(0, incoming_bytes),
                STORAGE_RESERVE_BYTES,
            )
        except Exception:
            # Capacity cleanup is opportunistic. A cleanup/database failure must
            # preserve the original safe write failure rather than admit the write.
            pass
        usage = shutil.disk_usage(_existing_parent(destination))
    if usage.free - max(0, incoming_bytes) < STORAGE_RESERVE_BYTES:
        raise HTTPException(
            status_code=507,
            detail="Storage free-space reserve would be exhausted",
        )


def reject_declared_size(size: int | None, label: str, max_bytes: int = FILE_MAX_BYTES) -> None:
    if size is not None and size > max_bytes:
        raise HTTPException(status_code=413, detail=f"{label} exceeds size limit")


async def stream_upload_to_file(
    upload: UploadFile,
    destination: Path,
    label: str,
    max_bytes: int = FILE_MAX_BYTES,
    digest: Optional[Any] = None,
) -> int:
    reject_declared_size(getattr(upload, "size", None), label, max_bytes)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ensure_storage_reserve(destination, getattr(upload, "size", None) or 0)
    size = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await upload.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                reject_declared_size(size, label, max_bytes)
                ensure_storage_reserve(destination, len(chunk))
                output.write(chunk)
                if digest is not None:
                    digest.update(chunk)
        return size
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def stream_reader_to_file(
    reader: BinaryIO,
    destination: Path,
    label: str,
    max_bytes: int = FILE_MAX_BYTES,
    digest: Optional[Any] = None,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    ensure_storage_reserve(destination)
    size = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = reader.read(CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                reject_declared_size(size, label, max_bytes)
                ensure_storage_reserve(destination, len(chunk))
                output.write(chunk)
                if digest is not None:
                    digest.update(chunk)
        return size
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def digest_reader(
    reader: BinaryIO,
    label: str,
    max_bytes: Optional[int] = FILE_MAX_BYTES,
) -> tuple[int, str]:
    import hashlib

    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = reader.read(CHUNK_BYTES)
        if not chunk:
            break
        size += len(chunk)
        if max_bytes is not None and max_bytes > 0:
            reject_declared_size(size, label, max_bytes)
        digest.update(chunk)
    return size, digest.hexdigest()
