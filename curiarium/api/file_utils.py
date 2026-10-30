import mimetypes
import os
import re
from typing import Optional
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from config import IMPORT_ALLOWED_EXTS


def sanitize_filename(name: str) -> str:
    name = (name or "").replace("\x00", "").strip()
    name = name.replace("/", "_").replace("\\", "_")
    name = os.path.basename(name)
    return name or "imported-file"


def sanitize_path_segment(value: str, fallback: str = "item") -> str:
    """Make a value safe to use as a single path component in a zip arcname.

    Folder and model names are user input; without this a name like ``../../x``
    produces a zip that escapes whatever directory it is extracted into.
    """
    value = (value or "").replace("\x00", "").replace("/", "_").replace("\\", "_")
    value = value.strip().strip(".").strip()
    return value or fallback


def parse_content_disposition(cd: str) -> Optional[str]:
    if not cd:
        return None
    match = re.search(r"filename\*=([^']*)''([^;]+)", cd, re.IGNORECASE)
    if match:
        return unquote(match.group(2))
    match = re.search(r'filename="?([^\";]+)"?', cd, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def build_import_filename(url: str, headers, override: Optional[str]) -> str:
    if override:
        name = sanitize_filename(override)
    else:
        dispo = headers.get("Content-Disposition", "")
        name = parse_content_disposition(dispo) or ""
        if not name:
            name = os.path.basename(urlparse(url).path)
        name = sanitize_filename(name)

    content_type = headers.get("Content-Type", "")
    base, ext = os.path.splitext(name)
    ext = ext.lower()
    if not ext:
        url_ext = os.path.splitext(urlparse(url).path)[1].lower()
        ext = url_ext or ""
    if not ext and content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        ext = guessed or ""
    if ext and not name.lower().endswith(ext):
        name = f"{base or 'imported-file'}{ext}"
    if not ext:
        raise HTTPException(status_code=415, detail="Unable to determine file extension")
    if ext not in IMPORT_ALLOWED_EXTS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {ext}")
    return name


def mime_from_content_type(content_type: str, filename: str) -> str:
    base = (content_type or "").split(";")[0].strip().lower()
    if not base or base in {"application/octet-stream", "binary/octet-stream"}:
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or base or "application/octet-stream"
    return base


def is_html_content_type(content_type: str) -> bool:
    base = (content_type or "").split(";")[0].strip().lower()
    return base in {"text/html", "application/xhtml+xml"}


def is_json_content_type(content_type: str) -> bool:
    base = (content_type or "").split(";")[0].strip().lower()
    return base in {"application/json", "text/json", "application/ld+json"}


def guess_mime_from_path(path: os.PathLike) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"
