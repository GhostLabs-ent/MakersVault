"""Deleting an asset must work with foreign keys enforced (migration 007).

007 turns `PRAGMA foreign_keys` on for every connection of the API engine, so
the old "delete the parent row and let the children fend for themselves" delete
paths now fail unless they delete the dependent rows first. These tests run on
the real app engine and cover the three delete paths: `cleanup_asset`, which
owns the bytes; `delete_asset_row_only`, whose contract is that no bytes are
touched at all; and `delete_asset_permanently`, the user-facing path the single
and bulk delete routes share, which must take the dependents and the bytes while
leaving the project that referenced the asset standing.
"""

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import pytest
from fastapi import Request
from sqlmodel import Session, delete, select

import asset_service
import audit
import main
import request_id
from db import STORAGE, engine
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Project, ProjectAsset

STL_BYTES = b"solid cube\nendsolid cube\n"


@dataclass(frozen=True)
class DeletableAsset:
    asset_id: str
    project_id: str
    storage_dir: Path
    managed_path: Path


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def create_asset_with_dependents() -> DeletableAsset:
    """An asset with one related file and one project membership, plus its bytes."""
    suffix = uuid4().hex
    stamp = utc_stamp()
    storage_dir = STORAGE / f"delete-fk-{suffix}"
    with Session(engine) as session:
        project = Project(name=f"delete-fk-{suffix}", created_at=stamp, updated_at=stamp)
        asset = Asset(
            name=f"delete-fk-{suffix}",
            filename="model.stl",
            mime="model/stl",
            size=len(STL_BYTES),
            storage_path=f"delete-fk-{suffix}/model.stl",
        )
        session.add(project)
        session.add(asset)
        session.flush()
        session.add(
            AssetFile(
                asset_id=asset.id,
                filename="part.stl",
                mime="model/stl",
                role="supporting",
                storage_path=f"bundles/{asset.id}/part.stl",
            )
        )
        session.add(
            ProjectAsset(project_id=project.id, asset_id=asset.id, role="member", position=0, added_at=stamp)
        )
        session.commit()
        project_id = project.id
        asset_id = asset.id

    managed_path = storage_dir / "model.stl"
    storage_dir.mkdir(parents=True, exist_ok=True)
    managed_path.write_bytes(STL_BYTES)
    return DeletableAsset(asset_id=asset_id, project_id=project_id, storage_dir=storage_dir, managed_path=managed_path)


def remove_rows(asset_id: str, project_id: str) -> None:
    with Session(engine) as session:
        session.execute(delete(ProjectAsset).where(ProjectAsset.project_id == project_id))
        session.execute(delete(ProjectAsset).where(ProjectAsset.asset_id == asset_id))
        session.execute(delete(AssetFile).where(AssetFile.asset_id == asset_id))
        session.execute(delete(Asset).where(Asset.id == asset_id))
        session.execute(delete(Project).where(Project.id == project_id))
        session.commit()


@pytest.fixture()
def deletable_asset() -> Iterator[DeletableAsset]:
    run_migrations(engine)
    created = create_asset_with_dependents()
    try:
        yield created
    finally:
        remove_rows(created.asset_id, created.project_id)
        shutil.rmtree(created.storage_dir, ignore_errors=True)


def audit_context(path: str) -> audit.AuditContext:
    """The context a route would pass, built with the same seam the routes use.

    ``audit.context_for`` is the only constructor in the repo, so the direct
    service call below produces a real ``asset.delete`` row instead of running
    with auditing switched off (``audit_ctx=None``).
    """
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": path,
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
        "state": {request_id.STATE_KEY: uuid4().hex},
    }
    return audit.context_for(Request(scope), None)


def assert_rows_gone(asset_id: str) -> None:
    with Session(engine) as session:
        assert session.get(Asset, asset_id) is None
        assert session.exec(select(AssetFile).where(AssetFile.asset_id == asset_id)).all() == []
        assert session.exec(select(ProjectAsset).where(ProjectAsset.asset_id == asset_id)).all() == []


def test_cleanup_asset_deletes_dependents_and_bytes(deletable_asset: DeletableAsset) -> None:
    asset_service.cleanup_asset(deletable_asset.asset_id)

    assert_rows_gone(deletable_asset.asset_id)
    assert not deletable_asset.managed_path.exists()


def test_delete_asset_row_only_deletes_dependents_but_keeps_bytes(deletable_asset: DeletableAsset) -> None:
    main.delete_asset_row_only(deletable_asset.asset_id)

    assert_rows_gone(deletable_asset.asset_id)
    assert deletable_asset.managed_path.read_bytes() == STL_BYTES


def test_delete_asset_permanently_deletes_dependents_membership_and_bytes(
    deletable_asset: DeletableAsset,
) -> None:
    asset_id = deletable_asset.asset_id
    asset_service.delete_asset_permanently(asset_id, audit_ctx=audit_context(f"/asset/{asset_id}"))

    # The membership goes with the asset through project_asset's ON DELETE
    # CASCADE, which only fires because the pragma is on in this engine.
    assert_rows_gone(asset_id)
    assert not deletable_asset.managed_path.exists()
    with Session(engine) as session:
        assert session.get(Project, deletable_asset.project_id) is not None
        assert session.exec(
            select(AuditEvent).where(AuditEvent.action == audit.ASSET_DELETE, AuditEvent.target == asset_id)
        ).first() is not None
