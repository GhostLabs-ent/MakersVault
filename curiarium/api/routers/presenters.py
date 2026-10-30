"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import project_service
from models import Asset, AssetFile, Folder, Project
from prepared_print import prepared_filename
from project_import import ImportOutcome
from schemas import AssetFileOut, AssetOut, FolderOut, ImportProjectOut, ProjectOut


def folder_to_out(f: Folder) -> "FolderOut":
    return FolderOut(
        id=f.id,
        name=f.name,
        tags=json.loads(f.tags_json or "[]"),
        parent_id=f.parent_id,
        storage_path=f.storage_path,
    )


def thumb_url_for(asset_id: Optional[str], thumb_version: int) -> Optional[str]:
    """The versioned thumbnail URL for an asset, or None when nothing was generated.

    The `?v=` token is the row's `thumb_version` (opaque to clients, still `\\d+`,
    so `AssetOut`/`ProjectOut` are unchanged), bumped on every thumbnail write.
    Version 0 means "no thumbnail", so the absence is a row fact and this helper
    can never do I/O - the old version `exists()`ed and `stat()`ed the file,
    which is 1000 network-filesystem round trips for a 1000-asset page.

    One helper for every `thumb_url`/`cover_thumb_url` field, so the versioned
    form cannot drift between the asset and project serializers.
    """
    if not asset_id or thumb_version <= 0:
        return None
    return f"/thumb/{asset_id}.jpg?v={thumb_version}"


def prepared_print_payload(raw: Optional[str]) -> Optional[dict]:
    """Normalise stored prepared-print metadata into the seven-key API shape.

    The stored blob is JSON written by an earlier parser, so it may be missing
    keys or - in a legacy row - be just ``{"format": "gcode"}``. Anything that
    is not a JSON object is treated as no metadata instead of crashing the
    serializer on a list/string.
    """
    try:
        parsed = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    slicer = parsed.get("slicer")
    fmt = parsed.get("format")
    return {
        "printer": parsed.get("printer"),
        "material": parsed.get("material"),
        "nozzle_mm": parsed.get("nozzle_mm"),
        "layer_height_mm": parsed.get("layer_height_mm"),
        "estimated_seconds": parsed.get("estimated_seconds"),
        "slicer": slicer if isinstance(slicer, str) else "unknown",
        "format": fmt if isinstance(fmt, str) else None,
    }


def to_out(a: Asset) -> AssetOut:
    tags = json.loads(a.tags_json or "[]")
    safe_filename = quote(a.filename or "", safe="")
    prepared = prepared_print_payload(a.prepared_metadata_json)
    if prepared:
        prepared["removable"] = bool(a.prepared_file_id)
    primary_url = f"/file/{a.id}/{safe_filename}"
    slicer_url = f"/asset/{a.id}/prepared-print" if a.prepared_file_id else primary_url
    return AssetOut(
        id=a.id,
        name=a.name or Path(a.filename).stem,
        filename=a.filename,
        mime=a.mime,
        size=a.size,
        title=a.title,
        notes=a.notes,
        creator=a.creator,
        collection=a.collection,
        tags=tags,
        url=primary_url,
        # A None/absent column reads as 0 = no thumbnail.
        thumb_url=thumb_url_for(a.id, int(a.thumb_version or 0)),
        folder_id=a.folder_id,
        storage_path=a.storage_path,
        missing_since=a.missing_since,
        supporting_file_count=int(a.supporting_file_count or 0),
        is_reference=bool(a.is_reference),
        prepared_print=prepared,
        slicer_url=slicer_url,
        slicer_filename=(prepared_filename(a.name, prepared) if a.prepared_file_id else a.filename),
        created_by=a.created_by,
        created_via=a.created_via,
    )


def project_metadata(raw: Optional[str]) -> dict:
    """Parse the project's `metadata_json` TEXT column; anything but an object is {}."""
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def project_to_out(project: Project, asset_count: int, total_size: int, cover_thumb_version: int) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        creator=project.creator,
        source_url=project.source_url,
        licence=project.licence,
        licence_url=project.licence_url,
        origin=project.origin,
        cover_asset_id=project.cover_asset_id,
        cover_thumb_url=thumb_url_for(project.cover_asset_id, cover_thumb_version),
        asset_count=asset_count,
        total_size=total_size,
        metadata_json=project_metadata(project.metadata_json),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def import_project_to_out(outcome: ImportOutcome) -> ImportProjectOut:
    """One import outcome as the route's response body.

    The project row is re-read through `project_service.project_with_stats`, so
    the response carries the member count, size and cover version *after* the
    import instead of a snapshot from before it.
    """
    project, asset_count, total_size, cover_thumb_version = project_service.project_with_stats(outcome.project_id)
    return ImportProjectOut(
        project=project_to_out(project, asset_count, total_size, cover_thumb_version),
        created=outcome.created,
        assets=[to_out(asset) for asset in outcome.assets],
        added=outcome.added,
        skipped=outcome.skipped,
        failed=outcome.failed,
        gated=outcome.gated,
        message=outcome.message,
    )


def asset_file_to_out(asset_file: AssetFile) -> AssetFileOut:
    return AssetFileOut(
        id=asset_file.id,
        filename=asset_file.filename,
        mime=asset_file.mime,
        size=asset_file.size,
        position=asset_file.position,
        url=f"/asset/{asset_file.asset_id}/files/{asset_file.id}",
    )
