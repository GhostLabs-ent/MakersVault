import json
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import func
from sqlmodel import Session, select

from db import STORAGE, engine
from file_utils import sanitize_filename
from models import (
    ArtifactRevision,
    Asset,
    AssetFile,
    ProjectMembership,
    ProjectRelationship,
)
from project_service import project_mutation_lock, require_active_project
from resource_limits import ensure_storage_reserve
from revision_export import write_artifact_history


def _project_tags(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [value for value in parsed if isinstance(value, str)] if isinstance(parsed, list) else []


def _snapshot_project(project_id: str):
    with project_mutation_lock, Session(engine) as session:
        project = require_active_project(session, project_id).model_copy(deep=True)
        def batched(statement):
            offset = 0
            while True:
                rows = list(session.exec(statement.offset(offset).limit(200)))
                if not rows:
                    break
                yield from rows
                offset += len(rows)

        memberships = [row.model_copy(deep=True) for row in batched(
            select(ProjectMembership)
            .where(ProjectMembership.project_id == project_id)
            .order_by(ProjectMembership.asset_id)
        )]
        relationships = [row.model_copy(deep=True) for row in batched(
            select(ProjectRelationship)
            .where(ProjectRelationship.project_id == project_id)
            .order_by(
                ProjectRelationship.source_asset_id,
                ProjectRelationship.target_asset_id,
                ProjectRelationship.kind,
                ProjectRelationship.id,
            )
        )]
        assets: dict[str, Asset | None] = {}
        for membership in memberships:
            asset = session.get(Asset, membership.asset_id)
            assets[membership.asset_id] = asset.model_copy(deep=True) if asset else None
        member_ids = [membership.asset_id for membership in memberships]
        expected_bytes = 0
        for start in range(0, len(member_ids), 200):
            batch = member_ids[start:start + 200]
            expected_bytes += int(session.exec(
                select(func.coalesce(func.sum(ArtifactRevision.size), 0)).where(
                    ArtifactRevision.asset_id.in_(batch)
                )
            ).one())
            expected_bytes += int(session.exec(
                select(func.coalesce(func.sum(AssetFile.size), 0)).where(
                    AssetFile.asset_id.in_(batch)
                )
            ).one())
    return project, memberships, relationships, assets, expected_bytes


def _build_project_export(project_id: str) -> tuple[Path, str]:
    project, memberships, relationships, assets, expected_bytes = _snapshot_project(
        project_id
    )
    export_dir = (STORAGE / ".exports").resolve()
    export_dir.mkdir(parents=True, exist_ok=True)
    ensure_storage_reserve(export_dir, expected_bytes)
    handle, raw_path = tempfile.mkstemp(
        prefix=f"project-{project_id}-",
        suffix=".zip",
        dir=export_dir,
    )
    os.close(handle)
    Path(raw_path).unlink(missing_ok=True)
    export_path = Path(raw_path)
    manifest = {
        "format": "makersvault-project-export",
        "version": 2,
        "project": {
            "id": project.id,
            "name": project.name,
            "notes": project.notes,
            "creator": project.creator,
            "source_url": project.source_url,
            "license": project.license,
            "tags": _project_tags(project.tags_json),
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        },
        "memberships": [],
        "relationships": [
            {
                "id": relationship.id,
                "source_asset_id": relationship.source_asset_id,
                "target_asset_id": relationship.target_asset_id,
                "kind": relationship.kind,
                "created_at": relationship.created_at,
            }
            for relationship in relationships
        ],
        "machines": [],
        "unresolved_machine_ids": [],
        "artifacts": [],
    }
    machine_snapshots: dict[str, dict] = {}
    unresolved_machine_ids: set[str] = set()
    try:
        with ZipFile(
            export_path,
            "w",
            compression=ZIP_DEFLATED,
            allowZip64=True,
        ) as archive:
            for membership in memberships:
                asset = assets.get(membership.asset_id)
                state = (
                    "missing"
                    if not asset
                    else "trashed"
                    if asset.deleted_at
                    else "active"
                )
                manifest["memberships"].append({
                    "artifact_id": membership.asset_id,
                    "created_at": membership.created_at,
                    "artifact_state": state,
                })
                if not asset:
                    manifest["artifacts"].append({
                        "id": membership.asset_id,
                        "name": None,
                        "filename": None,
                        "state": state,
                        "export_status": "unavailable",
                        "history_manifest_entry": None,
                        "machine_ids": [],
                        "unresolved_machine_ids": [],
                    })
                    continue
                prefix = f"artifacts/{asset.id}"
                artifact_manifest, status = write_artifact_history(
                    archive,
                    asset.id,
                    prefix=prefix,
                    include_trashed=True,
                )
                artifact_machine_ids = sorted({
                    machine_id
                    for machine_id in [
                        artifact_manifest["artifact"].get("prepared_machine_id"),
                        *(
                            row["machine_id"]
                            for row in artifact_manifest["machine_associations"]
                        ),
                        *(
                            row.get("prepared_machine_id")
                            for row in artifact_manifest["revisions"]
                        ),
                    ]
                    if machine_id
                })
                for snapshot in artifact_manifest["machines"]:
                    machine_snapshots[snapshot["id"]] = snapshot
                unresolved = artifact_manifest["unresolved_machine_ids"]
                unresolved_machine_ids.update(unresolved)
                manifest["artifacts"].append({
                    "id": asset.id,
                    "name": asset.name,
                    "filename": asset.filename,
                    "state": state,
                    "export_status": status,
                    "history_manifest_entry": f"{prefix}/manifest.json",
                    "machine_ids": artifact_machine_ids,
                    "unresolved_machine_ids": unresolved,
                })
            manifest["machines"] = [
                machine_snapshots[machine_id]
                for machine_id in sorted(machine_snapshots)
            ]
            manifest["unresolved_machine_ids"] = sorted(unresolved_machine_ids)
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True),
            )
    except Exception:
        export_path.unlink(missing_ok=True)
        raise

    download_name = f"{sanitize_filename(project.name)}-project.zip"
    return export_path, download_name


def build_project_export(project_id: str) -> tuple[Path, str]:
    with project_mutation_lock:
        return _build_project_export(project_id)
