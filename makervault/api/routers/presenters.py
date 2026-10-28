"""Split from main.py in Mf-x9dx; behaviour-preserving move."""

import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import db
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


def thumb_url_for(asset_id: Optional[str]) -> Optional[str]:
    """The versioned thumbnail URL for an asset, or None when nothing was generated.

    One helper for every `thumb_url`/`cover_thumb_url` field, so the versioned form
    (`?v=<st_mtime_ns>`, which makes the URL change when the thumbnail does) cannot
    drift between the asset and project serializers.
    """
    if not asset_id:
        return None
    path = db.THUMBS / f"{asset_id}.jpg"
    if not path.exists():
        return None
    return f"/thumb/{asset_id}.jpg?v={path.stat().st_mtime_ns}"


def to_out(a: Asset) -> AssetOut:
    tags = json.loads(a.tags_json or "[]")
    safe_filename = quote(a.filename or "", safe="")
    try:
        prepared = json.loads(a.prepared_metadata_json) if a.prepared_metadata_json else None
    except (TypeError, ValueError):
        prepared = None
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
        thumb_url=thumb_url_for(a.id),
        folder_id=a.folder_id,
        storage_path=a.storage_path,
        missing_since=a.missing_since,
        supporting_file_count=int(a.supporting_file_count or 0),
        prepared_print=prepared,
        slicer_url=slicer_url,
        slicer_filename=(prepared_filename(a.name, prepared) if a.prepared_file_id else a.filename),
    )


def project_metadata(raw: Optional[str]) -> dict:
    """Parse the project's `metadata_json` TEXT column; anything but an object is {}."""
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def project_to_out(project: Project, asset_count: int, total_size: int) -> ProjectOut:
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
        cover_thumb_url=thumb_url_for(project.cover_asset_id),
        asset_count=asset_count,
        total_size=total_size,
        metadata_json=project_metadata(project.metadata_json),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def import_project_to_out(outcome: ImportOutcome) -> ImportProjectOut:
    """One import outcome as the route's response body.

    The project row is re-read through `project_service.project_with_stats`, so
    the response carries the member count and size *after* the import instead of
    a snapshot from before it.
    """
    project, asset_count, total_size = project_service.project_with_stats(outcome.project_id)
    return ImportProjectOut(
        project=project_to_out(project, asset_count, total_size),
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
        url=f"/asset/{asset_file.asset_id}/files/{asset_file.id}",
    )
