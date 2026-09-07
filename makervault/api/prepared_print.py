import json
import re
from pathlib import Path
from typing import Optional
from zipfile import BadZipFile, ZipFile

from archive_limits import (
    ArchiveLimitError,
    UnsupportedArchiveCompression,
    bounded_archive_infos,
    validate_archive_compression,
    validate_archive_member,
)
from config import ARCHIVE_METADATA_MAX_BYTES


_TEXT_LIMIT = 2 * 1024 * 1024
_PREPARED_SUFFIXES = (".gcode.3mf", ".gcode", ".gco", ".bgcode")


def is_prepared_print_filename(filename: str) -> bool:
    lower = (filename or "").lower()
    return lower.endswith(_PREPARED_SUFFIXES)


def prepared_format(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".gcode.3mf"):
        return "gcode_3mf"
    if lower.endswith(".bgcode"):
        return "bgcode"
    return "gcode"


def _first_float(value: str) -> Optional[float]:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value or "")
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _duration_seconds(value: str) -> Optional[int]:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    total = 0.0
    found = False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(d|days?|h|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)\b", raw):
        found = True
        multiplier = 86400 if unit.startswith("d") else 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        total += float(amount) * multiplier
    return int(total) if found else None


def _clean_profile(value: str) -> Optional[str]:
    cleaned = re.sub(r"\s*@\s*[^;]+$", "", (value or "").strip())
    cleaned = cleaned.split(";")[0].strip()
    cleaned = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:mm\s*)?nozzle$", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return None
    aliases = {
        "p1s": "Bambu Lab P1S",
        "p1p": "Bambu Lab P1P",
        "x1c": "Bambu Lab X1 Carbon",
        "x1 carbon": "Bambu Lab X1 Carbon",
        "a1": "Bambu Lab A1",
        "a1 mini": "Bambu Lab A1 mini",
    }
    return aliases.get(cleaned.casefold(), cleaned)


def _merge_text_metadata(metadata: dict, text: str) -> None:
    attribute_values: dict[str, str] = {}
    for tag in re.findall(r"<[^>]+>", text):
        attrs = dict(re.findall(r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']", tag))
        key = (attrs.get("key") or attrs.get("name") or "").casefold()
        value = attrs.get("value")
        if key and value is not None:
            attribute_values[key] = value
        if metadata.get("material") is None and "filament" in tag.casefold() and attrs.get("type"):
            metadata["material"] = attrs["type"].split(";")[0].strip() or None

    for key, value in attribute_values.items():
        if metadata.get("printer") is None and key in {"printer_model", "printer_settings_id", "machine_name"}:
            metadata["printer"] = _clean_profile(value)
        elif metadata.get("material") is None and key in {"filament_type", "material_type"}:
            metadata["material"] = value.split(";")[0].strip() or None
        elif metadata.get("nozzle_mm") is None and key == "nozzle_diameter":
            metadata["nozzle_mm"] = _first_float(value)
        elif metadata.get("layer_height_mm") is None and key == "layer_height":
            metadata["layer_height_mm"] = _first_float(value)
        elif metadata.get("estimated_seconds") is None and key in {"prediction", "estimated_time", "print_time"}:
            metadata["estimated_seconds"] = _duration_seconds(value)

    patterns = {
        "printer": (
            r"(?im)^\s*;?\s*printer_settings_id\s*[:=]\s*([^\r\n]+)",
            r"(?im)^\s*;?\s*printer_model\s*[:=]\s*([^\r\n]+)",
            r"(?im)^\s*;?\s*machine_name\s*[:=]\s*([^\r\n]+)",
        ),
        "material": (
            r"(?im)^\s*;?\s*(?:filament_type|material_type)\s*[:=]\s*([^\r\n]+)",
        ),
        "nozzle_mm": (
            r"(?im)^\s*;?\s*nozzle_diameter\s*[:=]\s*([^\r\n]+)",
        ),
        "layer_height_mm": (
            r"(?im)^\s*;?\s*layer_height\s*[:=]\s*([^\r\n]+)",
        ),
        "estimated_seconds": (
            r"(?im)^\s*;?\s*(?:total estimated time|model printing time|estimated printing time[^:=]*|time)\s*[:=]\s*([^\r\n]+)",
        ),
    }
    for key, candidates in patterns.items():
        if metadata.get(key) is not None:
            continue
        for pattern in candidates:
            match = re.search(pattern, text)
            if not match:
                continue
            value = match.group(1).strip()
            if key == "printer":
                metadata[key] = _clean_profile(value)
            elif key == "material":
                metadata[key] = value.split(";")[0].strip() or None
            elif key in {"nozzle_mm", "layer_height_mm"}:
                metadata[key] = _first_float(value)
            else:
                metadata[key] = _duration_seconds(value)
            if metadata.get(key) is not None:
                break


def _merge_json_metadata(metadata: dict, raw: bytes) -> None:
    try:
        value = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return

    flattened: dict[str, object] = {}

    def visit(node, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                visit(child, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(node, list):
            for index, child in enumerate(node[:20]):
                visit(child, f"{prefix}.{index}")
        else:
            flattened[prefix.casefold()] = node

    visit(value)
    for key, value in flattened.items():
        text = str(value)
        if metadata.get("printer") is None and any(token in key for token in ("printer_model", "machine_name")):
            metadata["printer"] = _clean_profile(text)
        elif metadata.get("material") is None and any(token in key for token in ("filament_type", "material_type")):
            metadata["material"] = text.split(";")[0].strip() or None
        elif metadata.get("nozzle_mm") is None and "nozzle_diameter" in key:
            metadata["nozzle_mm"] = _first_float(text)
        elif metadata.get("layer_height_mm") is None and "layer_height" in key:
            metadata["layer_height_mm"] = _first_float(text)
        elif metadata.get("estimated_seconds") is None and any(token in key for token in ("prediction", "estimated_time", "print_time")):
            metadata["estimated_seconds"] = _duration_seconds(text)


def _read_text_sample(path: Path) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            first = handle.read(_TEXT_LIMIT // 2)
            last = b""
            if size > len(first):
                handle.seek(max(0, size - (_TEXT_LIMIT // 2)))
                last = handle.read(_TEXT_LIMIT // 2)
        return (first + b"\n" + last).decode("utf-8", errors="replace")
    except OSError:
        return ""


def inspect_prepared_print(path: Path, filename: Optional[str] = None) -> Optional[dict]:
    display_name = filename or path.name
    metadata = {
        "printer": None,
        "material": None,
        "nozzle_mm": None,
        "layer_height_mm": None,
        "estimated_seconds": None,
        "format": prepared_format(display_name),
    }

    is_3mf = display_name.lower().endswith(".3mf")
    if not is_3mf:
        if not is_prepared_print_filename(display_name):
            return None
        _merge_text_metadata(metadata, _read_text_sample(path))
        return metadata

    try:
        with ZipFile(path) as archive:
            infos = bounded_archive_infos(archive)
            names = [info.filename for info in infos]
            prepared_members = [
                name for name in names
                if name.lower().endswith((".gcode", ".gco", ".bgcode"))
            ]
            if not prepared_members and not display_name.lower().endswith(".gcode.3mf"):
                return None

            metadata["format"] = "gcode_3mf"
            # Identify the supplied payload from names, but do not decompress any
            # member of an unsupported package to infer print settings.
            for info in infos:
                validate_archive_compression(info)
            metadata_bytes = 0
            for info in infos:
                name = info.filename
                lower = name.lower()
                if info.file_size > _TEXT_LIMIT:
                    continue
                validate_archive_member(info, enforce_file_size=False)
                if metadata_bytes + info.file_size > ARCHIVE_METADATA_MAX_BYTES:
                    break
                if lower.endswith(".json") and ("metadata/" in lower or "slice" in lower or "plate" in lower):
                    metadata_bytes += info.file_size
                    _merge_json_metadata(metadata, archive.read(info))
                elif lower.endswith((".config", ".xml", ".txt")) and ("metadata/" in lower or "slice" in lower):
                    metadata_bytes += info.file_size
                    _merge_text_metadata(metadata, archive.read(info).decode("utf-8", errors="replace"))

            for name in prepared_members[:1]:
                info = archive.getinfo(name)
                validate_archive_member(info, enforce_file_size=False)
                remaining = max(0, ARCHIVE_METADATA_MAX_BYTES - metadata_bytes)
                if remaining:
                    with archive.open(info) as stream:
                        _merge_text_metadata(metadata, stream.read(min(_TEXT_LIMIT, remaining)).decode("utf-8", errors="replace"))
    except UnsupportedArchiveCompression:
        # Keep the prepared role/3MF handoff and original bytes, without asserting
        # printer/material settings we could not safely inspect.
        return {key: "gcode_3mf" if key == "format" else None for key in metadata}
    except (ArchiveLimitError, BadZipFile, KeyError, OSError):
        return None
    return metadata


def prepared_filename(model_name: str, metadata: Optional[dict]) -> str:
    fmt = (metadata or {}).get("format")
    suffix = ".gcode.3mf" if fmt == "gcode_3mf" else ".bgcode" if fmt == "bgcode" else ".gcode"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (model_name or "prepared-print").strip()).strip(" .")
    return f"{safe or 'prepared-print'}{suffix}"
