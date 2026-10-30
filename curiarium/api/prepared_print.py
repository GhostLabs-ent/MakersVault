import json
import re
from pathlib import Path
from typing import Optional
from zipfile import BadZipFile, ZipFile

_TEXT_LIMIT = 2 * 1024 * 1024
_PREPARED_SUFFIXES = (".gcode.3mf", ".gcode", ".gco", ".bgcode")
_PREPARED_MEMBER_SUFFIXES = (".gcode", ".gco", ".bgcode")

# Labels are checked in this order, so a fork wins over its upstream: Creality
# Print and OrcaSlicer before Bambu Studio, SuperSlicer before PrusaSlicer, and
# PrusaSlicer (including Slic3r PE) before Slic3r.
_SLICER_PATTERNS = (
    ("Creality Print", re.compile(r"creality[\s_-]*print", re.IGNORECASE)),
    ("OrcaSlicer", re.compile(r"orca\s*slicer", re.IGNORECASE)),
    ("Bambu Studio", re.compile(r"bambu[\s_-]*(?:lab[\s_-]*)?studio", re.IGNORECASE)),
    ("SuperSlicer", re.compile(r"super\s*slicer", re.IGNORECASE)),
    ("PrusaSlicer", re.compile(r"prusa\s*slicer|slic3r\s*pe", re.IGNORECASE)),
    ("Slic3r", re.compile(r"slic3r", re.IGNORECASE)),
    ("Cura", re.compile(r"(?<![a-z])cura(?![a-z])", re.IGNORECASE)),
    ("Simplify3D", re.compile(r"simplify[\s_-]*3d", re.IGNORECASE)),
    ("ideaMaker", re.compile(r"idea\s*maker", re.IGNORECASE)),
    ("KISSlicer", re.compile(r"kiss\s*slicer", re.IGNORECASE)),
    ("Anycubic Slicer", re.compile(r"anycubic\s*slicer", re.IGNORECASE)),
    ("Lychee Slicer", re.compile(r"lychee\s*slicer", re.IGNORECASE)),
    ("Chitubox", re.compile(r"chitubox", re.IGNORECASE)),
)
_GENERATED_BY = re.compile(r"generated\s+by\s+([^\r\n;]+)", re.IGNORECASE)

_PRINTER_KEYS = {"printersettingsid", "printermodel", "machinename"}
_PRINTER_JSON_TOKENS = ("printer_model", "machine_name", "printer_settings_id")
_MATERIAL_KEYS = {"filamenttype", "materialtype", "printmaterial"}
_NOZZLE_KEYS = {"nozzlediameter", "extruderdiameter"}
_LAYER_KEYS = {"layerheight"}
_TIME_KEYS = {"totalestimatedtime", "modelprintingtime", "time", "prediction", "estimatedtime", "printtime"}


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


def prepared_print_stub(filename: str) -> dict:
    """The complete metadata shape for a prepared file whose facts are unknown.

    A prepared-suffixed file that cannot be parsed still gets this stub, so the
    caller never has to invent a fallback (and a `.bgcode` stays labelled as
    such). Only ``slicer`` uses the literal ``"unknown"``; missing facts stay
    ``None`` because the API schema types require it.
    """
    return {
        "printer": None,
        "material": None,
        "nozzle_mm": None,
        "layer_height_mm": None,
        "estimated_seconds": None,
        "slicer": "unknown",
        "format": prepared_format(filename),
    }


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _canonical_fact_key(value: str) -> Optional[str]:
    normalised = _normalise_key(value)
    if normalised in _PRINTER_KEYS:
        return "printer"
    if normalised in _MATERIAL_KEYS:
        return "material"
    if normalised in _NOZZLE_KEYS:
        return "nozzle_mm"
    if normalised in _LAYER_KEYS:
        return "layer_height_mm"
    if normalised in _TIME_KEYS or normalised.startswith("estimatedprintingtime"):
        return "estimated_seconds"
    return None


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


def _printable_ascii_only(text: str) -> str:
    """Keep printable ASCII runs, so binary/compressed payloads cannot match."""
    return "".join(char for char in text if char in "\t\n\r" or " " <= char <= "~")


def _detect_slicer(text: str) -> str:
    """Return the canonical slicer label, preferring an explicit generator line."""
    for match in _GENERATED_BY.finditer(text):
        label = _match_slicer_label(match.group(1))
        if label:
            return label
    return _match_slicer_label(text) or "unknown"


def _match_slicer_label(text: str) -> Optional[str]:
    for label, pattern in _SLICER_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _set_fact(metadata: dict, fact: str, value: str) -> None:
    if metadata.get(fact) is not None or value is None:
        return
    if fact == "printer":
        metadata[fact] = _clean_profile(value)
    elif fact == "material":
        metadata[fact] = value.split(";")[0].strip() or None
    elif fact in {"nozzle_mm", "layer_height_mm"}:
        metadata[fact] = _first_float(value)
    else:
        metadata[fact] = _duration_seconds(value)


def _iter_key_values(text: str):
    """Yield ``(key, value)`` for comment/config lines using ``:``, ``=`` or ``,``.

    G-code headers and slicer config files are both line-oriented, and normalising
    the key (casefold, keep only alphanumerics) lets one parser accept
    ``Nozzle diameter``, ``nozzle_diameter`` and ``nozzleDiameter`` alike.
    """
    for line in text.splitlines():
        stripped = re.sub(r"^[\s;#/]+", "", line)
        match = re.match(r"([^:=,\r\n]{1,120}?)\s*[:=,]\s*(.+?)\s*$", stripped)
        if match:
            yield match.group(1).strip(), match.group(2).strip()


def _merge_text_metadata(metadata: dict, text: str) -> None:
    attribute_values: dict[str, str] = {}
    for tag in re.findall(r"<[^>]+>", text):
        attrs = dict(re.findall(r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']", tag))
        key = _normalise_key(attrs.get("key") or attrs.get("name") or "")
        value = attrs.get("value")
        if key and value is not None:
            attribute_values[key] = value
        if metadata.get("material") is None and "filament" in tag.casefold() and attrs.get("type"):
            metadata["material"] = attrs["type"].split(";")[0].strip() or None

    for key, value in attribute_values.items():
        fact = _canonical_fact_key(key)
        if fact:
            _set_fact(metadata, fact, value)

    for key, value in _iter_key_values(text):
        fact = _canonical_fact_key(key)
        if fact:
            _set_fact(metadata, fact, value)


def _merge_json_metadata(metadata: dict, raw: bytes) -> bool:
    try:
        value = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(value, (dict, list)):
        return False

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
        if metadata.get("printer") is None and any(token in key for token in _PRINTER_JSON_TOKENS):
            metadata["printer"] = _clean_profile(text)
        elif metadata.get("material") is None and any(token in key for token in ("filament_type", "material_type")):
            metadata["material"] = text.split(";")[0].strip() or None
        elif metadata.get("nozzle_mm") is None and "nozzle_diameter" in key:
            metadata["nozzle_mm"] = _first_float(text)
        elif metadata.get("layer_height_mm") is None and "layer_height" in key:
            metadata["layer_height_mm"] = _first_float(text)
        elif metadata.get("estimated_seconds") is None and any(token in key for token in ("prediction", "estimated_time", "print_time")):
            metadata["estimated_seconds"] = _duration_seconds(text)
    return True


def _merge_member_metadata(metadata: dict, lower_name: str, raw: bytes) -> str:
    """Merge one 3MF text member; JSON-shaped `.config` files are tried first."""
    text = raw.decode("utf-8", errors="replace")
    if lower_name.endswith((".json", ".config")) and _merge_json_metadata(metadata, raw):
        return text
    _merge_text_metadata(metadata, text)
    return text


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
    lower_name = display_name.lower()
    metadata = prepared_print_stub(display_name)
    prepared_suffix = is_prepared_print_filename(display_name)

    if not lower_name.endswith(".3mf"):
        if not prepared_suffix:
            return None
        text = _read_text_sample(path)
        if prepared_format(display_name) == "bgcode":
            text = _printable_ascii_only(text)
        _merge_text_metadata(metadata, text)
        metadata["slicer"] = _detect_slicer(text)
        return metadata

    haystack: list[str] = []
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            prepared_members = [
                name for name in names
                if name.lower().endswith(_PREPARED_MEMBER_SUFFIXES)
            ]
            if not prepared_suffix and not prepared_members:
                return None
            # An embedded payload keeps the container's format, so a slicer is
            # handed ``name.gcode.3mf`` rather than 3MF bytes named ``name.gcode``.
            metadata["format"] = "gcode_3mf"
            prepared_member = prepared_members[0] if prepared_members else None

            for name in names:
                lower = name.lower()
                try:
                    info = archive.getinfo(name)
                except KeyError:
                    continue
                if info.file_size > _TEXT_LIMIT:
                    continue
                if name == prepared_member:
                    text = archive.read(info).decode("utf-8", errors="replace")
                    if lower.endswith(".bgcode"):
                        text = _printable_ascii_only(text)
                    _merge_text_metadata(metadata, text)
                    haystack.append(text)
                elif lower == "[content_types].xml" or lower.endswith(".model"):
                    haystack.append(archive.read(info).decode("utf-8", errors="replace"))
                elif lower.endswith((".json", ".config", ".xml", ".txt")) and (
                    "metadata/" in lower or "slice" in lower or "plate" in lower
                ):
                    haystack.append(_merge_member_metadata(metadata, lower, archive.read(info)))

            metadata["slicer"] = _detect_slicer("\n".join(haystack))
    except (BadZipFile, KeyError, OSError, RuntimeError, ValueError, EOFError):
        # A prepared-suffixed file keeps a correct format label even when the
        # archive is corrupt; a plain model 3MF stays unclassified.
        return metadata if prepared_suffix else None
    return metadata


def prepared_filename(model_name: str, metadata: Optional[dict]) -> str:
    fmt = (metadata or {}).get("format")
    suffix = ".gcode.3mf" if fmt == "gcode_3mf" else ".bgcode" if fmt == "bgcode" else ".gcode"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (model_name or "prepared-print").strip()).strip(" .")
    return f"{safe or 'prepared-print'}{suffix}"
