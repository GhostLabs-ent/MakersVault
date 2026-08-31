import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from sqlmodel import Session, select

from asset_file_service import managed_asset_file_path
from db import LOCAL_CONTENT_STORE, engine
from file_utils import sanitize_filename
from models import (
    ArtifactMachine,
    ArtifactRevision,
    Asset,
    AssetFile,
    MachineProfile,
)
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


def _archive_path(prefix: str, path: str) -> str:
    return f"{prefix}/{path}" if prefix else path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def machine_profile_snapshot(machine: MachineProfile) -> dict:
    return {
        "id": machine.id,
        "name": machine.name,
        "category": machine.category,
        "manufacturer": machine.manufacturer,
        "model": machine.model,
        "location": machine.location,
        "notes": machine.notes,
        "created_at": machine.created_at,
        "updated_at": machine.updated_at,
        "archived_at": machine.archived_at,
    }


def artifact_history_snapshot(
    asset_id: str,
    *,
    include_trashed: bool = False,
) -> tuple[
    Asset,
    list[ArtifactRevision],
    list[AssetFile],
    list[ArtifactMachine],
    list[MachineProfile],
]:
    with Session(engine) as session:
        asset = session.get(Asset, asset_id)
        if not asset or (asset.deleted_at and not include_trashed):
            raise HTTPException(status_code=404, detail="Artifact not found")
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
        associations = list(session.exec(
            select(ArtifactMachine)
            .where(ArtifactMachine.asset_id == asset_id)
            .order_by(ArtifactMachine.machine_id)
        ))
        referenced_machine_ids = {
            machine_id
            for machine_id in [
                asset.prepared_machine_id,
                *(revision.prepared_machine_id for revision in revisions),
                *(association.machine_id for association in associations),
            ]
            if machine_id
        }
        machines = (
            list(session.exec(
                select(MachineProfile)
                .where(MachineProfile.id.in_(referenced_machine_ids))
                .order_by(MachineProfile.id)
            ))
            if referenced_machine_ids
            else []
        )
        return (
            asset.model_copy(deep=True),
            [row.model_copy(deep=True) for row in revisions],
            [row.model_copy(deep=True) for row in files],
            [row.model_copy(deep=True) for row in associations],
            [row.model_copy(deep=True) for row in machines],
        )


def write_artifact_history(
    archive: ZipFile,
    asset_id: str,
    *,
    prefix: str = "",
    include_trashed: bool = False,
) -> tuple[dict, str]:
    asset, revisions, files, associations, machines = artifact_history_snapshot(
        asset_id,
        include_trashed=include_trashed,
    )
    primary_paths = {
        revision.id: resolve_revision_content_path(revision)
        for revision in revisions
    }
    related_paths = {record.id: managed_asset_file_path(record) for record in files}
    manifest = {
        "format": "makersvault-artifact-history",
        "version": 2,
        "artifact": {
            "id": asset.id,
            "name": asset.name,
            "title": asset.title,
            "creator": asset.creator,
            "collection": asset.collection,
            "current_revision_id": asset.current_revision_id,
            "prepared_machine_id": asset.prepared_machine_id,
            "deleted_at": asset.deleted_at,
        },
        "machines": [machine_profile_snapshot(machine) for machine in machines],
        "machine_associations": [
            {
                "machine_id": association.machine_id,
                "created_at": association.created_at,
            }
            for association in associations
        ],
        "unresolved_machine_ids": [],
        "revisions": [],
        "artifact_files": [],
    }
    entries: dict[str, Path] = {}
    for revision in revisions:
        primary = primary_paths[revision.id]
        primary_entry = None
        if revision.content_state == "ready" and primary and primary.is_file():
            primary_entry = _archive_path(
                prefix,
                f"revisions/{revision.revision_number}/"
                f"{sanitize_filename(revision.filename)}",
            )
            entries[primary_entry] = primary
        manifest["revisions"].append({
            "id": revision.id,
            "number": revision.revision_number,
            "created_at": revision.created_at,
            "origin_revision_id": revision.origin_revision_id,
            "filename": revision.filename,
            "mime": revision.mime,
            "size": revision.size,
            "sha256": revision.sha256,
            "observed_sha256": revision.observed_sha256,
            "content_state": revision.content_state,
            "content_reason": revision.content_reason,
            "content_checked_at": revision.content_checked_at,
            "source_path": revision.source_path,
            "change_note": revision.change_note,
            "primary_entry": primary_entry,
            "prepared_metadata": _json_or_none(revision.prepared_metadata_json),
            "prepared_machine_id": revision.prepared_machine_id,
            "files": [],
        })

    referenced_machine_ids = {
        machine_id
        for machine_id in [
            asset.prepared_machine_id,
            *(revision.prepared_machine_id for revision in revisions),
            *(association.machine_id for association in associations),
        ]
        if machine_id
    }
    resolved_machine_ids = {machine.id for machine in machines}
    manifest["unresolved_machine_ids"] = sorted(
        referenced_machine_ids - resolved_machine_ids
    )

    revisions_by_id = {row["id"]: row for row in manifest["revisions"]}
    for record in files:
        source = related_paths[record.id]
        entry = None
        sha256 = None
        if source.is_file():
            if record.revision_id:
                revision = next(
                    (row for row in revisions if row.id == record.revision_id),
                    None,
                )
                relative_prefix = (
                    f"revisions/{revision.revision_number}/"
                    f"{'prepared' if record.role == 'prepared' else 'attachments'}"
                    if revision else "unscoped"
                )
            else:
                relative_prefix = "attachments/artifact"
            entry = _archive_path(
                prefix,
                _archive_name(relative_prefix, record.id, record.filename),
            )
            entries[entry] = source
            sha256 = _sha256_file(source)
        file_entry = {
            "id": record.id,
            "filename": record.filename,
            "mime": record.mime,
            "size": record.size,
            "role": record.role,
            "revision_id": record.revision_id,
            "entry": entry,
            "available": bool(entry),
            "content_state": "ready" if entry else "missing",
            "sha256": sha256,
        }
        if record.revision_id and record.revision_id in revisions_by_id:
            revisions_by_id[record.revision_id]["files"].append(file_entry)
        else:
            manifest["artifact_files"].append(file_entry)

    manifest_entry = _archive_path(prefix, "manifest.json")
    for name in sorted([*entries, manifest_entry]):
        if name == manifest_entry:
            archive.writestr(name, json.dumps(manifest, indent=2, sort_keys=True))
        else:
            archive.write(entries[name], name)

    primary_entries = [row["primary_entry"] for row in manifest["revisions"]]
    file_entries = [
        row["entry"]
        for row in manifest["artifact_files"]
    ] + [
        row["entry"]
        for revision in manifest["revisions"]
        for row in revision["files"]
    ]
    all_expected = primary_entries + file_entries
    available_count = sum(entry is not None for entry in all_expected)
    if all_expected and available_count == len(all_expected):
        status = "complete"
    elif available_count:
        status = "partial"
    else:
        status = "unavailable"
    return manifest, status


def build_history_export(asset_id: str) -> tuple[Path, str]:
    asset, revisions, files, _associations, _machines = artifact_history_snapshot(
        asset_id
    )
    expected_bytes = sum(int(row.size or 0) for row in revisions) + sum(
        int(row.size or 0) for row in files
    )
    export_dir = LOCAL_CONTENT_STORE.local_path(".exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    ensure_storage_reserve(export_dir, expected_bytes)
    handle, raw_path = tempfile.mkstemp(
        prefix=f"history-{asset_id}-",
        suffix=".zip",
        dir=export_dir,
    )
    os.close(handle)
    Path(raw_path).unlink(missing_ok=True)
    export_path = Path(raw_path)
    try:
        with ZipFile(
            export_path,
            "w",
            compression=ZIP_DEFLATED,
            allowZip64=True,
        ) as archive:
            write_artifact_history(archive, asset_id)
    except Exception:
        export_path.unlink(missing_ok=True)
        raise

    download_name = (
        f"{sanitize_filename(asset.name or asset.filename)}-history.zip"
    )
    return export_path, download_name
