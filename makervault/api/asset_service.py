import json
import io
import re
import tempfile
import warnings
from pathlib import Path
from typing import List, Optional
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from PIL import Image
from sqlmodel import Session, select

from archive_limits import ArchiveLimitError, bounded_archive_infos, validate_archive_member
from config import ARCHIVE_METADATA_MAX_BYTES, FILE_MAX_BYTES, IMAGE_MAX_PIXELS, PREVIEW_POLICY_VERSION
from db import STORAGE, THUMBS, engine
from file_utils import build_import_filename, mime_from_content_type, sanitize_filename
from models import Asset, Folder
from prepared_print import inspect_prepared_print
from preview_policy import apply_automatic_preview_disposition
from resource_limits import reject_declared_size, stream_reader_to_file
from schemas import ImportRequest
from settings_service import DEFAULT_STORAGE_TEMPLATE, get_storage_template


STORAGE_TEMPLATE_TOKENS = ("folder", "collection", "tags", "creator", "model", "name", "filename", "id")
THUMBNAIL_IMAGE_FORMATS = ["PNG", "JPEG", "WEBP", "BMP"]
Image.MAX_IMAGE_PIXELS = IMAGE_MAX_PIXELS
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


def unique_model_name(session: Session, requested: str, folder_id: Optional[str], exclude_id: Optional[str] = None) -> str:
    base = sanitize_path_segment(requested, "Model")
    stmt = select(Asset).where(Asset.folder_id == folder_id)
    existing = {
        (row.name or model_name_from_filename(row.filename)).casefold()
        for row in session.exec(stmt)
        if row.id != exclude_id
    }
    if base.casefold() in existing:
        raise HTTPException(status_code=409, detail=f'A model named "{base}" already exists in this folder')
    return base


def available_model_name(session: Session, requested: str, folder_id: Optional[str], exclude_id: Optional[str] = None) -> str:
    base = sanitize_path_segment(requested, "Model")
    stmt = select(Asset).where(Asset.folder_id == folder_id)
    existing = {
        (row.name or model_name_from_filename(row.filename)).casefold()
        for row in session.exec(stmt)
        if row.id != exclude_id
    }
    candidate = base
    suffix = 2
    while candidate.casefold() in existing:
        candidate = f"{base} ({suffix})"
        suffix += 1
    return candidate


def managed_asset_path(asset: Asset) -> Path:
    relative = asset.storage_path or f"{asset.id}/{asset.filename}"
    return STORAGE / relative


def prune_empty_storage_dirs(start: Path) -> None:
    storage_root = STORAGE.resolve()
    current = start
    while current.exists() and current.resolve() != storage_root and storage_root in current.resolve().parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def relocate_asset(asset: Asset, session: Session, old_path: Path, template: Optional[str] = None) -> bool:
    new_relative = render_storage_path(asset, session, template)
    new_path = STORAGE / new_relative
    if old_path.resolve() == new_path.resolve():
        asset.storage_path = new_relative
        return False
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"Storage path already exists: {new_relative}")
    if old_path.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_parent = old_path.parent
        old_path.rename(new_path)
        prune_empty_storage_dirs(old_parent)
    asset.storage_path = new_relative
    return True


def reorganize_managed_assets(template: Optional[str] = None) -> tuple[int, int]:
    moved = 0
    skipped = 0
    with Session(engine) as session:
        assets = list(session.exec(select(Asset).order_by(Asset.id)))
        for asset in assets:
            old_path = managed_asset_path(asset)
            if not old_path.exists() and asset.source_path:
                skipped += 1
                continue
            try:
                changed = relocate_asset(asset, session, old_path, template)
                session.add(asset)
                session.commit()
                moved += 1 if changed else 0
            except HTTPException:
                session.rollback()
                skipped += 1
    return moved, skipped


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
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(src, formats=THUMBNAIL_IMAGE_FORMATS) as image:
                return save_thumb_image(asset_id, image)
    except Exception:
        return None


def save_thumb_bytes(asset_id: str, data: bytes) -> Optional[str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=THUMBNAIL_IMAGE_FORMATS) as image:
                return save_thumb_image(asset_id, image)
    except Exception:
        return None


def extract_3mf_thumbnail(asset_id: str, src: Path, filename: Optional[str] = None) -> Optional[str]:
    display_name = filename or src.name
    if not display_name.lower().endswith(".3mf") or not src.exists():
        return None
    try:
        with ZipFile(src) as archive:
            infos = bounded_archive_infos(archive)
            image_names = [
                info.filename for info in infos
                if Path(info.filename).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
                and "thumbnail" in Path(info.filename).name.lower()
            ]
            priorities = {
                "metadata/thumbnail.png": 0,
                "3d/thumbnail.png": 1,
                "thumbnail.png": 2,
            }
            image_names.sort(key=lambda name: (priorities.get(name.lower().lstrip("/"), 10), len(name)))
            bytes_read = 0
            for name in image_names:
                info = archive.getinfo(name)
                if info.file_size > ARCHIVE_METADATA_MAX_BYTES:
                    continue
                validate_archive_member(info, enforce_file_size=False)
                if bytes_read + info.file_size > ARCHIVE_METADATA_MAX_BYTES:
                    break
                bytes_read += info.file_size
                saved = save_thumb_bytes(asset_id, archive.read(info))
                if saved:
                    return saved
    except (ArchiveLimitError, BadZipFile, KeyError, OSError):
        return None
    return None


def ensure_model_thumbnail(asset_id: str, src: Path, filename: Optional[str] = None) -> Optional[str]:
    existing = THUMBS / f"{asset_id}.jpg"
    if existing.exists():
        return f"/thumb/{asset_id}.jpg"
    return extract_3mf_thumbnail(asset_id, src, filename)


def inspect_asset_prepared_print(asset: Asset, src: Optional[Path] = None) -> Optional[dict]:
    if not (asset.filename or "").lower().endswith(".3mf"):
        return None
    candidate = src or managed_asset_path(asset)
    if not candidate.exists() and asset.source_path:
        candidate = Path(asset.source_path)
    return inspect_prepared_print(candidate, asset.filename) if candidate.exists() else None


def backfill_embedded_thumbnails() -> None:
    with Session(engine) as session:
        assets = list(session.exec(select(Asset)))
    for asset in assets:
        thumb = THUMBS / f"{asset.id}.jpg"
        if not thumb.exists() and (asset.filename or "").lower().endswith(".3mf"):
            src = managed_asset_path(asset)
            if not src.exists() and asset.source_path:
                src = Path(asset.source_path)
            ensure_model_thumbnail(asset.id, src)
        with Session(engine) as session:
            current = session.get(Asset, asset.id)
            if current:
                should_refresh = (
                    thumb.exists()
                    or not current.preview_updated_at
                    or current.preview_policy_version != PREVIEW_POLICY_VERSION
                    or current.preview_status == "ready"
                )
                if should_refresh:
                    apply_automatic_preview_disposition(current, thumb.exists())
                    session.add(current)
                    session.commit()


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
        s.add(asset)
        s.commit()
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
        apply_automatic_preview_disposition(
            db_a,
            (THUMBS / f"{asset_id}.jpg").exists(),
        )
        s.add(db_a)
        s.commit()
        s.refresh(db_a)
        return db_a


def cleanup_asset(asset_id: str) -> None:
    managed_path: Optional[Path] = None
    with Session(engine) as s:
        a = s.get(Asset, asset_id)
        if a:
            managed_path = managed_asset_path(a)
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
    return stream_reader_to_file(resp, dest, "Imported file")


def persist_asset_from_response(resp, final_url: str, body: ImportRequest) -> Asset:
    content_length = resp.headers.get("Content-Length")
    if content_length:
        try:
            reject_declared_size(int(content_length), "Imported file", FILE_MAX_BYTES)
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
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")
