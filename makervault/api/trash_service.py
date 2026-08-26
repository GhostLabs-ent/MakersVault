import json
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from db import STORAGE, engine
from models import (
    ArtifactRevision,
    Asset,
    AssetFile,
    ContentHashJobItem,
    Folder,
    ProjectMembership,
    ProjectRelationship,
    TrashPurgeOperation,
)
from project_service import project_mutation_lock
from settings_service import get_trash_retention


PERMANENT_DELETE_CONFIRMATION = "PERMANENTLY DELETE"
EMPTY_TRASH_CONFIRMATION = "EMPTY TRASH"
QUARANTINE_DIR = ".trash-quarantine"
RETENTION_SECONDS = {
    "day": 24 * 60 * 60,
    "week": 7 * 24 * 60 * 60,
    "month": 30 * 24 * 60 * 60,
}
trash_mutation_lock = threading.RLock()


def trash_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_active_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if not asset or asset.deleted_at:
        raise HTTPException(404)
    return asset


def require_trashed_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if not asset or not asset.deleted_at:
        raise HTTPException(404)
    return asset


def _folder_location(session: Session, folder: Optional[Folder]) -> Optional[str]:
    names: list[str] = []
    seen: set[str] = set()
    current = folder
    while current and current.id not in seen:
        seen.add(current.id)
        names.append(current.name)
        current = session.get(Folder, current.parent_id) if current.parent_id else None
    return " / ".join(reversed(names)) if names else None


def soft_delete_asset(asset_id: str) -> Asset:
    with trash_mutation_lock, project_mutation_lock, Session(engine) as session:
        asset = require_active_asset(session, asset_id)
        folder = session.get(Folder, asset.folder_id) if asset.folder_id else None
        asset.deleted_at = trash_timestamp()
        asset.trash_original_folder_id = asset.folder_id
        asset.trash_original_folder_name = _folder_location(session, folder)
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset


def restore_asset(asset_id: str, restore_unassigned: bool = False) -> Asset:
    with trash_mutation_lock, project_mutation_lock, Session(engine) as session:
        asset = require_trashed_asset(session, asset_id)
        target_folder_id = asset.trash_original_folder_id
        if target_folder_id and not session.get(Folder, target_folder_id):
            if not restore_unassigned:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "original_folder_missing",
                        "message": "The original folder no longer exists; confirm restore as Unassigned",
                    },
                )
            target_folder_id = None

        conflict = session.exec(
            select(Asset).where(
                Asset.id != asset.id,
                Asset.deleted_at == None,  # noqa: E711
                Asset.folder_id == target_folder_id,
                func.lower(Asset.name) == asset.name.lower(),
            )
        ).first()
        if conflict:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "name_conflict",
                    "message": "An active model with this name already exists in the restore folder",
                    "conflicting_asset_id": conflict.id,
                },
            )
        asset.folder_id = target_folder_id
        asset.deleted_at = None
        asset.trash_original_folder_id = None
        asset.trash_original_folder_name = None
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset


def _managed_path(relative: str) -> Path:
    root = STORAGE.resolve()
    candidate = (STORAGE / relative).resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Managed Trash path resolved outside storage")
    return candidate


def _asset_inventory(session: Session, asset: Asset) -> dict:
    revisions = list(session.exec(
        select(ArtifactRevision).where(ArtifactRevision.asset_id == asset.id)
    ))
    files = list(session.exec(select(AssetFile).where(AssetFile.asset_id == asset.id)))
    relative_paths: set[str] = set()
    if asset.storage_path:
        relative_paths.add(asset.storage_path)
    if asset.current_thumb_path:
        relative_paths.add(asset.current_thumb_path)
    for revision in revisions:
        if revision.storage_path:
            relative_paths.add(revision.storage_path)
        if revision.preview_thumb_path:
            relative_paths.add(revision.preview_thumb_path)
    for record in files:
        if record.storage_path:
            relative_paths.add(record.storage_path)

    managed_bytes = 0
    existing_paths: list[tuple[str, Path]] = []
    for relative in sorted(relative_paths):
        path = _managed_path(relative)
        if path.is_file():
            existing_paths.append((relative, path))
            try:
                managed_bytes += path.stat().st_size
            except OSError:
                pass
    return {
        "asset": asset,
        "revisions": revisions,
        "files": files,
        "paths": existing_paths,
        "managed_bytes": managed_bytes,
        "external_source": any(bool(row.source_path) for row in revisions),
    }


def list_trash() -> list[dict]:
    with Session(engine) as session:
        assets = list(session.exec(
            select(Asset)
            .where(Asset.deleted_at != None)  # noqa: E711
            .order_by(Asset.deleted_at, Asset.id)
        ))
        results = []
        for asset in assets:
            inventory = _asset_inventory(session, asset)
            results.append({
                "id": asset.id,
                "name": asset.name,
                "filename": asset.filename,
                "deleted_at": asset.deleted_at,
                "original_folder_id": asset.trash_original_folder_id,
                "original_folder_name": asset.trash_original_folder_name,
                "managed_bytes": inventory["managed_bytes"],
                "managed_file_count": len(inventory["paths"]),
                "revision_count": len(inventory["revisions"]),
                "supporting_file_count": len([
                    row for row in inventory["files"] if row.role == "supporting"
                ]),
                "external_source": inventory["external_source"],
            })
        return results


def _operation_quarantine_root(operation_id: str) -> Path:
    root = (STORAGE / QUARANTINE_DIR).resolve()
    candidate = (root / operation_id).resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Trash quarantine path is invalid")
    return candidate


def _set_operation(
    operation_id: str,
    *,
    status: str,
    paths: Optional[list[dict]] = None,
    results: Optional[list[dict]] = None,
    error: Optional[str] = None,
    completed: bool = False,
) -> None:
    with Session(engine) as session:
        operation = session.get(TrashPurgeOperation, operation_id)
        if not operation:
            return
        operation.status = status
        if paths is not None:
            operation.paths_json = json.dumps(paths)
        if results is not None:
            operation.results_json = json.dumps(results)
        operation.error = error
        operation.completed_at = trash_timestamp() if completed else None
        session.add(operation)
        session.commit()


def _restore_quarantine_paths(paths: list[dict]) -> None:
    for entry in reversed(paths):
        source = _managed_path(entry["source"])
        quarantine = _managed_path(entry["quarantine"])
        if quarantine.is_file():
            source.parent.mkdir(parents=True, exist_ok=True)
            quarantine.replace(source)


def _commit_purge_session(session: Session) -> None:
    session.commit()


def _purge_operation(asset_ids: list[str], trigger: str, requested_bytes: int = 0) -> list[dict]:
    operation_id = str(uuid.uuid4())
    quarantine_root = _operation_quarantine_root(operation_id)
    with Session(engine) as session:
        assets = [require_trashed_asset(session, asset_id) for asset_id in asset_ids]
        inventories = [_asset_inventory(session, asset) for asset in assets]
        paths: list[dict] = []
        for inventory in inventories:
            for index, (relative, _source) in enumerate(inventory["paths"]):
                quarantine_relative = (
                    f"{QUARANTINE_DIR}/{operation_id}/{inventory['asset'].id}/"
                    f"{index}-{Path(relative).name}"
                )
                paths.append({
                    "asset_id": inventory["asset"].id,
                    "source": relative,
                    "quarantine": quarantine_relative,
                })
        results = [
            {
                "asset_id": inventory["asset"].id,
                "name": inventory["asset"].name,
                "status": "pending",
                "managed_files": len(inventory["paths"]),
                "managed_bytes": inventory["managed_bytes"],
                "external_source_preserved": inventory["external_source"],
            }
            for inventory in inventories
        ]
        operation = TrashPurgeOperation(
            id=operation_id,
            trigger=trigger,
            status="planned",
            created_at=trash_timestamp(),
            asset_ids_json=json.dumps(asset_ids),
            paths_json=json.dumps(paths),
            results_json=json.dumps(results),
            quarantine_path=f"{QUARANTINE_DIR}/{operation_id}",
            requested_bytes=max(0, requested_bytes),
            managed_bytes=sum(row["managed_bytes"] for row in inventories),
        )
        session.add(operation)
        session.commit()

    moved: list[dict] = []
    try:
        _set_operation(operation_id, status="moving")
        for entry in paths:
            source = _managed_path(entry["source"])
            if not source.is_file():
                continue
            quarantine = _managed_path(entry["quarantine"])
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            source.replace(quarantine)
            moved.append(entry)
        _set_operation(operation_id, status="quarantined")
    except Exception as exc:
        try:
            _restore_quarantine_paths(moved)
        finally:
            _set_operation(
                operation_id,
                status="rolled_back",
                error=f"quarantine_move_failed:{type(exc).__name__}",
                completed=True,
            )
        raise

    try:
        with project_mutation_lock, Session(engine) as session:
            for asset_id in asset_ids:
                asset = require_trashed_asset(session, asset_id)
                revisions = list(session.exec(
                    select(ArtifactRevision).where(ArtifactRevision.asset_id == asset_id)
                ))
                revision_ids = [row.id for row in revisions]
                if revision_ids:
                    for item in session.exec(
                        select(ContentHashJobItem).where(
                            ContentHashJobItem.revision_id.in_(revision_ids)
                        )
                    ):
                        session.delete(item)
                for record in session.exec(
                    select(AssetFile).where(AssetFile.asset_id == asset_id)
                ):
                    session.delete(record)
                for membership in session.exec(
                    select(ProjectMembership).where(
                        ProjectMembership.asset_id == asset_id
                    )
                ):
                    session.delete(membership)
                for relationship in session.exec(
                    select(ProjectRelationship).where(
                        (ProjectRelationship.source_asset_id == asset_id)
                        | (ProjectRelationship.target_asset_id == asset_id)
                    )
                ):
                    session.delete(relationship)
                for revision in revisions:
                    session.delete(revision)
                session.delete(asset)
            operation = session.get(TrashPurgeOperation, operation_id)
            operation.status = "database_committed"
            operation.results_json = json.dumps([
                {**row, "status": "deleted"} for row in results
            ])
            session.add(operation)
            _commit_purge_session(session)
            results = json.loads(operation.results_json)
    except Exception as exc:
        _restore_quarantine_paths(moved)
        _set_operation(
            operation_id,
            status="rolled_back",
            error=f"database_delete_failed:{type(exc).__name__}",
            completed=True,
        )
        raise

    try:
        if quarantine_root.exists():
            shutil.rmtree(quarantine_root)
        _set_operation(operation_id, status="completed", results=results, completed=True)
    except OSError as exc:
        _set_operation(
            operation_id,
            status="cleanup_pending",
            results=results,
            error=f"quarantine_cleanup_failed:{type(exc).__name__}",
        )
    return results


def permanently_delete(
    asset_ids: list[str],
    *,
    trigger: str,
    confirmation: Optional[str] = None,
    requested_bytes: int = 0,
) -> list[dict]:
    unique_ids = list(dict.fromkeys(asset_ids))
    if trigger == "manual" and confirmation != PERMANENT_DELETE_CONFIRMATION:
        raise HTTPException(status_code=400, detail="Permanent deletion confirmation is required")
    if trigger == "empty" and confirmation != EMPTY_TRASH_CONFIRMATION:
        raise HTTPException(status_code=400, detail="Empty Trash confirmation is required")
    if not unique_ids:
        return []
    with trash_mutation_lock:
        return _purge_operation(unique_ids, trigger, requested_bytes)


def _retention_cutoff(policy: str) -> Optional[str]:
    seconds = RETENTION_SECONDS.get(policy)
    if seconds is None:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return cutoff.isoformat().replace("+00:00", "Z")


def eligible_trash(policy: str) -> list[str]:
    cutoff = _retention_cutoff(policy)
    with Session(engine) as session:
        statement = select(Asset).where(Asset.deleted_at != None)  # noqa: E711
        if cutoff:
            statement = statement.where(Asset.deleted_at <= cutoff)
        elif policy != "until_needed":
            return []
        return [row.id for row in session.exec(statement.order_by(Asset.deleted_at, Asset.id))]


def purge_expired_trash() -> list[dict]:
    policy = get_trash_retention()
    if policy not in RETENTION_SECONDS:
        return []
    results = []
    for asset_id in eligible_trash(policy):
        results.extend(permanently_delete([asset_id], trigger="retention"))
    return results


def reclaim_for_capacity(destination: Path, incoming_bytes: int, reserve_bytes: int) -> list[dict]:
    policy = get_trash_retention()
    if policy == "never":
        return []
    purge_expired_trash()
    usage_path = destination
    while not usage_path.exists() and usage_path != usage_path.parent:
        usage_path = usage_path.parent
    usage = shutil.disk_usage(usage_path)
    if usage.free - max(0, incoming_bytes) >= reserve_bytes:
        return []
    if policy != "until_needed":
        return []
    results = []
    for asset_id in eligible_trash(policy):
        results.extend(permanently_delete(
            [asset_id], trigger="capacity", requested_bytes=incoming_bytes
        ))
        usage = shutil.disk_usage(usage_path)
        if usage.free - max(0, incoming_bytes) >= reserve_bytes:
            break
    return results


def reconcile_trash_operations() -> dict:
    reconciled = 0
    with trash_mutation_lock, Session(engine) as session:
        operations = list(session.exec(
            select(TrashPurgeOperation).where(
                TrashPurgeOperation.status.in_([
                    "planned", "moving", "quarantined", "database_committed", "cleanup_pending"
                ])
            )
        ))
    for snapshot in [row.model_copy(deep=True) for row in operations]:
        paths = json.loads(snapshot.paths_json or "[]")
        asset_ids = json.loads(snapshot.asset_ids_json or "[]")
        with Session(engine) as session:
            existing = [session.get(Asset, asset_id) is not None for asset_id in asset_ids]
        try:
            if any(existing):
                _restore_quarantine_paths(paths)
                _set_operation(snapshot.id, status="rolled_back", completed=True)
            else:
                quarantine_root = _operation_quarantine_root(snapshot.id)
                if quarantine_root.exists():
                    shutil.rmtree(quarantine_root)
                _set_operation(snapshot.id, status="completed", completed=True)
            reconciled += 1
        except OSError as exc:
            _set_operation(
                snapshot.id,
                status="cleanup_pending",
                error=f"reconciliation_failed:{type(exc).__name__}",
            )
    known_ids = set()
    with Session(engine) as session:
        known_ids = {row.id for row in session.exec(select(TrashPurgeOperation))}
    root = (STORAGE / QUARANTINE_DIR).resolve()
    orphaned = sorted(
        path.name for path in root.iterdir()
        if path.is_dir() and path.name not in known_ids
    ) if root.is_dir() else []
    return {"reconciled": reconciled, "orphaned": orphaned}


def start_trash_maintenance(interval_seconds: int = 3600) -> threading.Event:
    stop = threading.Event()

    def worker() -> None:
        reconcile_trash_operations()
        while not stop.is_set():
            try:
                purge_expired_trash()
            except Exception:
                pass
            stop.wait(interval_seconds)

    threading.Thread(target=worker, name="trash-maintenance", daemon=True).start()
    return stop
