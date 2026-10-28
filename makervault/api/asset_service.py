import errno
import io
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import List, Optional
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

import audit
import folder_paths
from asset_file_service import delete_all_asset_files
from config import IMPORT_MAX_BYTES
from db import STORAGE, THUMBS, engine
from file_utils import build_import_filename, mime_from_content_type, sanitize_filename
from models import Asset, Folder
from prepared_print import inspect_prepared_print
from schemas import ImportRequest
from settings_service import get_storage_template

log = logging.getLogger(__name__)

# Serialises the no-hardlink fallback across this process's threads. Coarse on
# purpose: the fallback is rare and a per-destination dict would grow unbounded.
_FALLBACK_MOVE_LOCK = threading.Lock()
# Errnos meaning "this filesystem cannot create hardlinks": SMB/FAT and
# unprivileged Windows mounts refusing link() as a matter of policy (EPERM,
# EACCES); filesystems with no hardlink support at all (ENOTSUP, EOPNOTSUPP);
# the link count cap (EMLINK); and FUSE/SMB servers that report "not
# implemented" or "invalid argument" instead of a dedicated errno (ENOSYS,
# EINVAL). EXDEV is included for completeness even though a rename cannot cross
# filesystems either: falling back only re-raises the same EXDEV. Every other
# OSError propagates unchanged.
_HARDLINK_UNSUPPORTED_ERRNOS = frozenset(
    {errno.EXDEV, errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.ENOSYS, errno.EINVAL}
)

STORAGE_TEMPLATE_TOKENS = ("folder", "collection", "tags", "creator", "model", "name", "filename", "id")
_TOKEN_RE = re.compile(r"\{([a-z_]+)\}")
_INVALID_SEGMENT_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


def sanitize_path_segment(value: str, fallback: str) -> str:
    cleaned = _INVALID_SEGMENT_RE.sub("_", (value or "").strip())
    cleaned = cleaned.replace("/", "_").replace("\\", "_").strip(" .")
    if cleaned in {"", ".", ".."}:
        cleaned = fallback
    return cleaned[:120]


def validate_storage_template(template: str) -> str:
    normalized = (template or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        raise HTTPException(status_code=400, detail="Storage template cannot be empty")
    tokens = _TOKEN_RE.findall(normalized)
    unknown = sorted(set(tokens) - set(STORAGE_TEMPLATE_TOKENS))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown storage token: {{{unknown[0]}}}")
    if normalized.count("{filename}") != 1:
        raise HTTPException(status_code=400, detail="Storage template must contain {filename} exactly once")
    if "{filename}" not in normalized.split("/")[-1]:
        raise HTTPException(status_code=400, detail="{filename} must be in the final path segment")
    if "{" in _TOKEN_RE.sub("", normalized) or "}" in _TOKEN_RE.sub("", normalized):
        raise HTTPException(status_code=400, detail="Storage template contains an invalid token")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise HTTPException(status_code=400, detail="Storage template contains an unsafe path segment")
    return normalized


def sample_storage_path(template: str) -> str:
    safe_template = validate_storage_template(template)
    return safe_template.format(
        folder="Props/Workshop",
        collection="Tabletop",
        tags="Print in place + Useful",
        creator="Example creator",
        model="Cable clip",
        name="Cable clip",
        filename="Cable clip.3mf",
        id="a1b2c3d4",
    )


def folder_segments(session: Session, folder_id: Optional[str]) -> List[str]:
    if not folder_id:
        return ["Unassigned"]
    segments: List[str] = []
    current = session.get(Folder, folder_id)
    guard = set()
    while current and current.id not in guard:
        guard.add(current.id)
        segments.insert(0, sanitize_path_segment(current.name, "Folder"))
        current = session.get(Folder, current.parent_id) if current.parent_id else None
    return segments or ["Unassigned"]


def render_storage_path(asset: Asset, session: Session, template: Optional[str] = None) -> str:
    safe_template = validate_storage_template(template or get_storage_template())
    try:
        tags = json.loads(asset.tags_json or "[]")
    except Exception:
        tags = []
    tag_label = " + ".join(str(tag).strip() for tag in tags if str(tag).strip()) or "Untagged"
    values = {
        "folder": "/".join(folder_segments(session, asset.folder_id)),
        "collection": sanitize_path_segment(asset.collection or "Uncollected", "Uncollected"),
        "tags": sanitize_path_segment(tag_label, "Untagged"),
        "creator": sanitize_path_segment(asset.creator or "Unknown creator", "Unknown creator"),
        "model": sanitize_path_segment(asset.name or Path(asset.filename).stem, "Model"),
        "name": sanitize_path_segment(asset.name or Path(asset.filename).stem, "Model"),
        "filename": sanitize_filename(asset.filename),
        "id": asset.id,
    }
    rendered = safe_template.format(**values).replace("\\", "/")
    parts = [sanitize_path_segment(part, "item") for part in rendered.split("/") if part]
    if not parts:
        raise HTTPException(status_code=400, detail="Storage template produced an empty path")
    relative = Path(*parts)
    candidate = (STORAGE / relative).resolve()
    storage_root = STORAGE.resolve()
    if candidate == storage_root or storage_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Storage template resolved outside the storage directory")
    return relative.as_posix()


def model_name_from_filename(filename: str) -> str:
    return sanitize_path_segment(Path(filename or "model").stem, "Model")


def filename_for_model_name(name: str, current_filename: str) -> str:
    extension = Path(current_filename or "").suffix
    if not extension:
        raise HTTPException(status_code=400, detail="Asset filename must include an extension")
    return sanitize_filename(f"{sanitize_path_segment(name, 'Model')}{extension}")


def model_names_in_folder(session: Session, folder_id: Optional[str], exclude_id: Optional[str] = None) -> set[str]:
    """Case-folded model names in one folder, matching the unique index's scope.

    ``folder_id=None`` stays an ``IS NULL`` comparison because the index buckets
    unfiled rows under COALESCE(folder_id, '') and the comparison happens in
    Python so SQLite never has to agree about case folding.
    """
    statement = select(Asset).where(Asset.folder_id == folder_id)
    return {
        (row.name or model_name_from_filename(row.filename)).casefold()
        for row in session.exec(statement)
        if row.id != exclude_id
    }


def raise_asset_conflict(
    requested_name: str,
    folder_id: Optional[str],
    storage_path: Optional[str],
    exclude_id: Optional[str] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Map a unique-index collision to 409 using a fresh session.

    The failed insert is rolled back and gone, so the collision is re-identified
    from the database instead of parsed out of the IntegrityError text (SQLite
    words the expression index and the partial index differently and has changed
    that wording across versions).
    """
    with Session(engine) as session:
        name_taken = requested_name.casefold() in model_names_in_folder(session, folder_id, exclude_id)
    if name_taken:
        raise HTTPException(status_code=409, detail=f'A model named "{requested_name}" already exists in this folder') from None
    if storage_path:
        raise HTTPException(status_code=409, detail=f"Storage path already exists: {storage_path}") from None
    log.error(
        "Unclassified asset uniqueness conflict: name=%r folder_id=%r storage_path=%r",
        requested_name, folder_id, storage_path, exc_info=error,
    )
    raise HTTPException(status_code=409, detail="Asset conflicts with an existing record") from None


def unique_model_name(session: Session, requested: str, folder_id: Optional[str], exclude_id: Optional[str] = None) -> str:
    base = sanitize_path_segment(requested, "Model")
    existing = model_names_in_folder(session, folder_id, exclude_id)
    if base.casefold() in existing:
        raise HTTPException(status_code=409, detail=f'A model named "{base}" already exists in this folder')
    return base


def available_model_name(session: Session, requested: str, folder_id: Optional[str], exclude_id: Optional[str] = None) -> str:
    base = sanitize_path_segment(requested, "Model")
    existing = model_names_in_folder(session, folder_id, exclude_id)
    candidate = base
    suffix = 2
    while candidate.casefold() in existing:
        candidate = f"{base} ({suffix})"
        suffix += 1
    return candidate


def managed_asset_path(asset: Asset) -> Path:
    relative = asset.storage_path or f"{asset.id}/{asset.filename}"
    return STORAGE / relative


# Uploads stream into this app-owned directory before their rendered destination
# exists, because that path depends on form fields that may arrive after the file
# part. A move prunes the directory, so ``new_staging_path`` recreates it.
STAGING_DIRNAME = ".incoming"


def staging_dir() -> Path:
    return STORAGE / STAGING_DIRNAME


def new_staging_path() -> Path:
    directory = staging_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / uuid4().hex


def sweep_staging_dir() -> int:
    """Remove files a crashed or disconnected upload left behind."""
    directory = staging_dir()
    if not directory.is_dir():
        return 0
    removed = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        log.warning("Could not list staging directory %s", directory, exc_info=True)
        return 0
    for entry in entries:
        try:
            if entry.is_file() or entry.is_symlink():
                entry.unlink()
                removed += 1
        except OSError:
            log.warning("Could not remove stale staging entry %s", entry, exc_info=True)
    return removed


def prune_empty_storage_dirs(start: Path) -> None:
    storage_root = STORAGE.resolve()
    current = start
    while current.exists() and current.resolve() != storage_root and storage_root in current.resolve().parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _relative_storage_path(path: Path) -> str:
    """Express an absolute storage path relative to the library root."""
    try:
        return path.resolve().relative_to(STORAGE.resolve()).as_posix()
    except ValueError:
        raise HTTPException(status_code=400, detail="Asset path resolved outside the storage directory") from None


def _hardlink_move(old_path: Path, new_path: Path) -> None:
    """Move bytes by linking then unlinking, so new_path is either created by us or the move fails.

    ``os.link`` is atomic and refuses an existing destination (file or
    directory), so concurrent moves onto one target cannot overwrite committed
    bytes. It preserves the inode, so content and mtime are unchanged; the
    unlink then retires the old name. A failed unlink rolls the half-move back:
    after this function the bytes have exactly one name, never two and never zero.
    """
    os.link(old_path, new_path)
    try:
        old_path.unlink()
    except OSError:
        new_path.unlink(missing_ok=True)
        raise


def _locked_rename_move(old_path: Path, new_path: Path, relative: str) -> None:
    """Check-then-rename fallback for filesystems that cannot hardlink.

    The lock serialises this process's own moving threads, which is the only
    interleaving one worker can produce; it is NOT safe against a second worker
    process, which is why hardlinking is the default and this is the fallback.
    new_path is either created by us or the move fails.
    """
    with _FALLBACK_MOVE_LOCK:
        if new_path.exists():
            raise HTTPException(status_code=409, detail=f"Storage path already exists: {relative}")
        os.rename(old_path, new_path)


def move_managed_file(old_path: Path, new_path: Path) -> bool:
    """Move one managed file and prune the directory it vacated.

    Only an explicit rename (same directory) or a folder move reaches here; a
    metadata edit never does, which is what keeps the storage template from
    relocating files as a side effect. Whatever the interleaving, new_path is
    either created by us or the move fails: committed bytes are never overwritten.
    """
    if old_path.resolve() == new_path.resolve():
        return False
    relative = _relative_storage_path(new_path)
    # Friendly fast path with today's 409 precedence; exists() is a read, so it
    # decides nothing once two moves race - the link below is the arbiter.
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"Storage path already exists: {relative}")
    if not old_path.exists():
        # mount no-copy rows own no managed file: the row moves, the bytes do not.
        return False
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_parent = old_path.parent
    try:
        _hardlink_move(old_path, new_path)
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"Storage path already exists: {relative}") from None
    except OSError as error:
        if error.errno not in _HARDLINK_UNSUPPORTED_ERRNOS:
            raise
        _locked_rename_move(old_path, new_path, relative)
    prune_empty_storage_dirs(old_parent)
    return True


def restore_moved_file(moved: bool, old_path: Path, new_path: Path) -> None:
    """Best-effort undo of a file move whose row update did not commit."""
    if not moved:
        return
    try:
        old_path.parent.mkdir(parents=True, exist_ok=True)
        # Undoing our own no-clobber move: nobody else can have created old_path.
        new_path.rename(old_path)
        prune_empty_storage_dirs(new_path.parent)
    except OSError:
        log.exception("Failed to undo asset move %s -> %s", old_path, new_path)


def rename_asset_in_place(asset: Asset, old_path: Path, filename: str) -> bool:
    """Rename an asset's managed file inside its current directory.

    The storage template is never rendered here: only the basename changes, so a
    template containing {tags} or {creator} cannot move a file during a rename.
    """
    new_path = old_path.parent / filename
    moved = move_managed_file(old_path, new_path)
    asset.storage_path = _relative_storage_path(new_path)
    return moved


def _folder_member_directory(session: Session, folder_id: str, exclude_asset_id: Optional[str]) -> Optional[str]:
    """Directory of the first stored asset in the folder, "." for the root, None if none."""
    statement = (
        select(Asset)
        .where(Asset.folder_id == folder_id, Asset.storage_path.is_not(None))
        .order_by(Asset.id)
    )
    for row in session.exec(statement):
        if row.id == exclude_asset_id:
            continue
        return Path(row.storage_path).parent.as_posix()
    return None


def folder_storage_directory(session: Session, folder_id: Optional[str], exclude_asset_id: Optional[str] = None) -> Path:
    """Return the directory a folder owns, taking the disk as the source of truth.

    Order: the folder's own storage_path; else the directory of one of its
    already-stored assets (library-scan folders have storage_path NULL but their
    files live somewhere real); else a newly converged path derived from the
    folder names. Unfiled assets (folder_id None) belong at the storage root.
    """
    if not folder_id:
        return STORAGE
    folder = session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=400, detail="Folder not found")
    relative = folder.storage_path
    if relative is None:
        relative = _folder_member_directory(session, folder_id, exclude_asset_id)
    if relative is None:
        relative = folder_paths.converge_ancestor_paths(session, folder_id)
    return (STORAGE / relative) if relative else STORAGE


def move_asset_to_folder(asset: Asset, session: Session, old_path: Path, folder_id: Optional[str]) -> bool:
    """Move an asset's managed file into the directory its new folder owns."""
    new_path = folder_storage_directory(session, folder_id, exclude_asset_id=asset.id) / asset.filename
    moved = move_managed_file(old_path, new_path)
    asset.storage_path = _relative_storage_path(new_path)
    return moved


def move_asset_to_folder_by_id(asset_id: str, folder_id: Optional[str], *, audit_ctx: Optional[audit.AuditContext]) -> Asset:
    """Move one asset into a folder: the single-item and batch routes share this.

    Order matters and is why this is not inlined in the routes. The audit row is
    staged before the bytes move, so a failed audit insert can never leave the
    file relocated while the row still describes the old location. The no-clobber
    move must happen before ``folder_id`` is assigned, otherwise an autoflush
    exposes the moving asset as a witness for its own target directory, and a
    row update that loses a uniqueness race must put the moved bytes back.

    Staging only adds the row to this session, which the move's own queries then
    autoflush inside the same transaction: harmless, because a failure rolls the
    insert and the row update back together.

    A move to the folder the asset is already in changes nothing, so it writes
    no audit row: the log records what happened, not what was asked.
    """
    with Session(engine) as s:
        asset = s.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        previous_folder_id = asset.folder_id
        old_path = managed_asset_path(asset)
        folder_id = folder_id or None
        if folder_id:
            folder = s.get(Folder, folder_id)
            if not folder:
                raise HTTPException(status_code=400, detail="Folder not found")
            unique_model_name(s, asset.name, folder.id, exclude_id=asset.id)
        else:
            unique_model_name(s, asset.name, None, exclude_id=asset.id)
        if folder_id != previous_folder_id:
            audit.stage(s, audit_ctx, audit.Event(audit.ASSET_MOVE, asset_id, {"folder_id": folder_id}))
        # Move before assigning folder_id: an autoflush must not expose the moving
        # asset as a witness for its own target directory.
        moved = move_asset_to_folder(asset, s, old_path, folder_id)
        asset.folder_id = folder_id
        new_path = managed_asset_path(asset)
        # Rollback expires the row, so the conflict classifier gets locals.
        conflict_name = asset.name
        new_relative = asset.storage_path if moved else None
        s.add(asset)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            restore_moved_file(moved, old_path, new_path)
            raise_asset_conflict(conflict_name, folder_id, new_relative, exclude_id=asset_id)
        s.refresh(asset)
        return asset


def delete_asset_permanently(asset_id: str, *, audit_ctx: Optional[audit.AuditContext]) -> None:
    """Delete one asset and its files: the single-item and batch routes share this.

    Two sessions on purpose: the dependent ``AssetFile`` rows go first, and the
    row is re-read before deletion so a concurrent delete surfaces as a 404
    rather than deleting a row this call never saw. The unlink/prune is
    best-effort - bytes that cannot be removed must not stop the row from going.

    The audit row joins the asset-row transaction, so a failed audit insert
    rolls that delete back; the earlier ``AssetFile`` delete has already
    committed, which is the same residual window the unlink/prune has always
    had.
    """
    managed_path: Optional[Path] = None
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        managed_path = managed_asset_path(a)
    delete_all_asset_files(asset_id)
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if not a:
            raise HTTPException(404)
        audit.stage(s, audit_ctx, audit.Event(audit.ASSET_DELETE, asset_id, {"filename": a.filename}))
        s.delete(a)
        s.commit()
    # best-effort cleanup
    try:
        if managed_path and managed_path.exists():
            parent = managed_path.parent
            managed_path.unlink(missing_ok=True)
            prune_empty_storage_dirs(parent)
        (THUMBS / f"{asset_id}.jpg").unlink(missing_ok=True)
    except Exception:
        pass


def save_thumb_image(asset_id: str, image: Image.Image) -> Optional[str]:
    tmp_path: Optional[Path] = None
    try:
        thumb = THUMBS / f"{asset_id}.jpg"
        image.load()
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, (248, 250, 252, 255))
            canvas.alpha_composite(rgba)
            image = canvas.convert("RGB")
        else:
            image = image.convert("RGB")
        image.thumbnail((512, 512))
        with tempfile.NamedTemporaryFile(delete=False, dir=THUMBS, suffix=".jpg") as tmp:
            tmp_path = Path(tmp.name)
        image.save(tmp_path, format="JPEG", quality=88, optimize=True)
        tmp_path.replace(thumb)
        return f"/thumb/{asset_id}.jpg"
    except Exception:
        return None
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


def save_thumb(asset_id: str, src: Path) -> Optional[str]:
    try:
        with Image.open(src) as image:
            return save_thumb_image(asset_id, image)
    except Exception:
        return None


def save_thumb_bytes(asset_id: str, data: bytes) -> Optional[str]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            return save_thumb_image(asset_id, image)
    except Exception:
        return None


def extract_3mf_thumbnail(asset_id: str, src: Path) -> Optional[str]:
    if src.suffix.lower() != ".3mf" or not src.exists():
        return None
    try:
        with ZipFile(src) as archive:
            image_names = [
                name for name in archive.namelist()
                if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                and "thumbnail" in Path(name).name.lower()
            ]
            priorities = {
                "metadata/thumbnail.png": 0,
                "3d/thumbnail.png": 1,
                "thumbnail.png": 2,
            }
            image_names.sort(key=lambda name: (priorities.get(name.lower().lstrip("/"), 10), len(name)))
            for name in image_names:
                info = archive.getinfo(name)
                if info.file_size > 16 * 1024 * 1024:
                    continue
                saved = save_thumb_bytes(asset_id, archive.read(info))
                if saved:
                    return saved
    except (BadZipFile, KeyError, OSError):
        return None
    return None


def ensure_model_thumbnail(asset_id: str, src: Path) -> Optional[str]:
    existing = THUMBS / f"{asset_id}.jpg"
    if existing.exists():
        return f"/thumb/{asset_id}.jpg"
    return extract_3mf_thumbnail(asset_id, src)


def inspect_asset_prepared_print(asset: Asset, src: Optional[Path] = None) -> Optional[dict]:
    if not (asset.filename or "").lower().endswith(".3mf"):
        return None
    candidate = src or managed_asset_path(asset)
    if not candidate.exists() and asset.source_path:
        candidate = Path(asset.source_path)
    return inspect_prepared_print(candidate, asset.filename) if candidate.exists() else None


def backfill_embedded_thumbnails() -> None:
    with Session(engine) as session:
        assets = list(session.exec(select(Asset).where(Asset.filename.like("%.3mf"))))
    for asset in assets:
        if (THUMBS / f"{asset.id}.jpg").exists():
            continue
        src = managed_asset_path(asset)
        if not src.exists() and asset.source_path:
            src = Path(asset.source_path)
        ensure_model_thumbnail(asset.id, src)


def create_asset_record(
    filename: str,
    mime: str,
    title: Optional[str],
    notes: Optional[str],
    tags: List[str],
    folder_id: Optional[str],
    source_path: Optional[str] = None,
) -> Asset:
    with Session(engine) as s:
        name = unique_model_name(s, title or model_name_from_filename(filename), folder_id)
        asset = Asset(
            name=name,
            filename=filename_for_model_name(name, filename),
            mime=mime,
            size=0,
            title=name,
            notes=notes,
            tags_json=json.dumps([t.strip() for t in tags if t.strip()]),
            folder_id=folder_id,
            source_path=source_path,
        )
        asset.storage_path = render_storage_path(asset, s)
        # Rollback expires the instance, so every value the conflict classifier
        # needs is captured here.
        storage_path = asset.storage_path
        s.add(asset)
        try:
            s.commit()
        except IntegrityError:
            # two uploads can pass the pre-check together; the unique indexes are
            # the real arbiter, so the loser is a 409 and never a 500
            s.rollback()
            raise_asset_conflict(name, folder_id, storage_path)
        s.refresh(asset)
    return asset


def finalize_asset_record(asset_id: str, size: int, mime: Optional[str] = None) -> Optional[Asset]:
    with Session(engine) as s:
        db_a = s.get(Asset, asset_id)
        if not db_a:
            return None
        db_a.size = size
        if mime:
            db_a.mime = mime
        prepared = inspect_asset_prepared_print(db_a)
        if prepared:
            db_a.prepared_metadata_json = json.dumps(prepared)
        s.add(db_a)
        s.commit()
        s.refresh(db_a)
        return db_a


def cleanup_asset(asset_id: str) -> None:
    """Remove a row created by a failed upload and best-effort its bytes.

    The dependent ``AssetFile`` rows go first: migration 007 turns on
    ``PRAGMA foreign_keys``, so an asset row with remaining children would now
    fail the delete instead of orphaning them. The unlink/prune afterwards stays
    best-effort for the same reason as ``delete_asset_permanently`` - bytes that
    cannot be removed must not keep the row alive.
    """
    managed_path: Optional[Path] = None
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if a:
            managed_path = managed_asset_path(a)
    delete_all_asset_files(asset_id)
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if a:
            s.delete(a)
            s.commit()
    try:
        if managed_path and managed_path.exists():
            parent = managed_path.parent
            managed_path.unlink(missing_ok=True)
            prune_empty_storage_dirs(parent)
        (THUMBS / f"{asset_id}.jpg").unlink(missing_ok=True)
    except Exception:
        pass


def stream_response_to_file(resp, dest: Path) -> int:
    size = 0
    with open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > IMPORT_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Imported file exceeds size limit")
            f.write(chunk)
    return size


def persist_asset_from_response(resp, final_url: str, body: ImportRequest) -> Asset:
    content_length = resp.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > IMPORT_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Imported file exceeds size limit")
        except ValueError:
            pass

    filename = build_import_filename(final_url, resp.headers, body.filename)
    mime = mime_from_content_type(resp.headers.get("Content-Type", ""), filename)
    asset = create_asset_record(filename, mime, body.title, body.notes, body.tags, body.folder_id)
    dest = managed_asset_path(asset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = stream_response_to_file(resp, dest)
        if (mime or "").startswith("image/") and dest.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            save_thumb(asset.id, dest)
        elif dest.suffix.lower() == ".3mf":
            ensure_model_thumbnail(asset.id, dest)
        refreshed = finalize_asset_record(asset.id, size, mime)
        return refreshed or asset
    except HTTPException:
        cleanup_asset(asset.id)
        raise
    except Exception as exc:
        cleanup_asset(asset.id)
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc
