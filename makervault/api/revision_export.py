import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from sqlmodel import Session, select

from asset_file_service import managed_asset_file_path
from db import STORAGE, engine
from file_utils import sanitize_filename
from models import ArtifactRevision, Asset, AssetFile
from resource_limits import ensure_storage_reserve
from revision_workflow import resolve_revision_content_path


def _archive_name(prefix: str, record_id: str, filename: str) -> str:
    return f"{prefix}/{record_id}-{sanitize_filename(filename)}"


def _json_or_none(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def build_history_export(asset_id: str) -> tuple[Path, str]:
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset:
            raise HTTPException(404)
        revisions = list(session.exec(
            select(ArtifactRevision)
            .where(ArtifactRevision.asset_id == asset_id)
            .order_by(ArtifactRevision.revision_number, ArtifactRevision.id)
        ))
        files = list(session.exec(
            select(AssetFile)
            .where(AssetFile.asset_id == asset_id)
            .order_by(AssetFile.filename, AssetFile.id)
        ))
        asset_snapshot = asset.model_copy(deep=True)
        revision_snapshots = [row.model_copy(deep=True) for row in revisions]
        file_snapshots = [row.model_copy(deep=True) for row in files]

    primary_paths = {
        revision.id: resolve_revision_content_path(revision)
        for revision in revision_snapshots
    }
    related_paths = {record.id: managed_asset_file_path(record) for record in file_snapshots}
    expected_bytes = sum(
        int(revision.size or 0)
        for revision in revision_snapshots
        if primary_paths[revision.id] and primary_paths[revision.id].is_file()
    ) + sum(
        int(record.size or 0)
        for record in file_snapshots
        if related_paths[record.id].is_file()
    )

    export_dir = (STORAGE / ".exports").resolve()
    export_dir.mkdir(parents=True, exist_ok=True)
    ensure_storage_reserve(export_dir, expected_bytes)
    handle, raw_path = tempfile.mkstemp(prefix=f"history-{asset_id}-", suffix=".zip", dir=export_dir)
    os.close(handle)
    Path(raw_path).unlink(missing_ok=True)
    export_path = Path(raw_path)

    manifest = {
        "format": "makersvault-artifact-history",
        "version": 1,
        "artifact": {
            "id": asset_snapshot.id,
            "name": asset_snapshot.name,
            "title": asset_snapshot.title,
            "creator": asset_snapshot.creator,
            "collection": asset_snapshot.collection,
            "current_revision_id": asset_snapshot.current_revision_id,
        },
        "revisions": [],
        "artifact_files": [],
    }
    try:
        with ZipFile(export_path, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for revision in revision_snapshots:
                primary = primary_paths[revision.id]
                primary_entry = None
                if revision.content_state == "ready" and primary and primary.is_file():
                    primary_entry = (
                        f"revisions/{revision.revision_number}/"
                        f"{sanitize_filename(revision.filename)}"
                    )
                    archive.write(primary, primary_entry)
                manifest["revisions"].append({
                    "id": revision.id,
                    "number": revision.revision_number,
                    "created_at": revision.created_at,
                    "origin_revision_id": revision.origin_revision_id,
                    "filename": revision.filename,
                    "mime": revision.mime,
                    "size": revision.size,
                    "sha256": revision.sha256,
                    "content_state": revision.content_state,
                    "content_reason": revision.content_reason,
                    "change_note": revision.change_note,
                    "primary_entry": primary_entry,
                    "prepared_metadata": _json_or_none(revision.prepared_metadata_json),
                    "files": [],
                })

            revisions_by_id = {row["id"]: row for row in manifest["revisions"]}
            for record in file_snapshots:
                source = related_paths[record.id]
                entry = None
                if source.is_file():
                    if record.revision_id:
                        revision = next(
                            (row for row in revision_snapshots if row.id == record.revision_id),
                            None,
                        )
                        prefix = (
                            f"revisions/{revision.revision_number}/"
                            f"{'prepared' if record.role == 'prepared' else 'attachments'}"
                            if revision else "unscoped"
                        )
                    else:
                        prefix = "attachments/artifact"
                    entry = _archive_name(prefix, record.id, record.filename)
                    archive.write(source, entry)
                file_entry = {
                    "id": record.id,
                    "filename": record.filename,
                    "mime": record.mime,
                    "size": record.size,
                    "role": record.role,
                    "revision_id": record.revision_id,
                    "entry": entry,
                }
                if record.revision_id and record.revision_id in revisions_by_id:
                    revisions_by_id[record.revision_id]["files"].append(file_entry)
                else:
                    manifest["artifact_files"].append(file_entry)

            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    except Exception:
        export_path.unlink(missing_ok=True)
        raise

    download_name = f"{sanitize_filename(asset_snapshot.name or asset_snapshot.filename)}-history.zip"
    return export_path, download_name
