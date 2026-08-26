from io import BytesIO
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from db import STORAGE, engine
from main import app
from models import (
    ArtifactRevision,
    Asset,
    Project,
    ProjectMembership,
    ProjectRelationship,
)
import project_export


PROJECT_DELETE_CONFIRMATION = "PERMANENTLY DELETE PROJECT"


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _project(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post(
        "/projects",
        headers=headers,
        json={
            "name": name,
            "notes": "Project lifecycle evidence",
            "creator": "MakersVault tests",
            "source_url": "https://example.com/project",
            "license": "CERN-OHL-S-2.0",
            "tags": ["relay", "evidence"],
        },
    )
    assert response.status_code == 201
    return response.json()


def _asset(
    client: TestClient,
    headers: dict[str, str],
    filename: str,
    content: bytes,
) -> dict:
    response = client.post(
        "/upload",
        headers=headers,
        files={"file": (filename, content, "model/stl")},
    )
    assert response.status_code == 200
    return response.json()


def _join(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    asset_id: str,
) -> dict:
    response = client.post(
        f"/project/{project_id}/items/{asset_id}", headers=headers
    )
    assert response.status_code == 201
    return response.json()


def _relationship(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    source_id: str,
    target_id: str,
) -> dict:
    response = client.post(
        f"/project/{project_id}/relationships",
        headers=headers,
        json={
            "source_asset_id": source_id,
            "target_asset_id": target_id,
            "kind": "documentation_for",
        },
    )
    assert response.status_code == 201
    return response.json()


def _remove_projects(project_ids: list[str]) -> None:
    with Session(engine) as session:
        for relationship in session.exec(
            select(ProjectRelationship).where(
                ProjectRelationship.project_id.in_(project_ids)
            )
        ):
            session.delete(relationship)
        for membership in session.exec(
            select(ProjectMembership).where(
                ProjectMembership.project_id.in_(project_ids)
            )
        ):
            session.delete(membership)
        for project_id in project_ids:
            project = session.get(Project, project_id)
            if project:
                session.delete(project)
        session.commit()


def _purge_assets(
    client: TestClient,
    headers: dict[str, str],
    asset_ids: list[str],
) -> None:
    for asset_id in asset_ids:
        with Session(engine) as session:
            asset = session.get(Asset, asset_id)
            if not asset:
                continue
            already_trashed = bool(asset.deleted_at)
        if not already_trashed:
            client.delete(f"/asset/{asset_id}", headers=headers)
        client.post(
            "/trash/permanent",
            headers=headers,
            json={
                "asset_ids": [asset_id],
                "confirmation": "PERMANENTLY DELETE",
            },
        )


def _exports() -> set[Path]:
    directory = STORAGE / ".exports"
    return set(directory.iterdir()) if directory.exists() else set()


def test_project_lifecycle_routes_require_authentication() -> None:
    project_id = str(uuid4())
    assert TestClient(app).get("/projects/trash").status_code == 401
    assert TestClient(app).post(f"/project/{project_id}/restore").status_code == 401
    assert TestClient(app).post(
        f"/project/{project_id}/permanent",
        json={"confirmation": PROJECT_DELETE_CONFIRMATION},
    ).status_code == 401
    assert TestClient(app).get(f"/project/{project_id}/export").status_code == 401


def test_project_restore_conflict_and_permanent_delete_are_metadata_only() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Lifecycle {suffix}")
        project_ids.append(project["id"])
        assets = [
            _asset(client, headers, f"lifecycle-{suffix}-{index}.stl", content)
            for index, content in enumerate((b"first lifecycle bytes", b"second lifecycle bytes"))
        ]
        asset_ids.extend(asset["id"] for asset in assets)
        memberships = [
            _join(client, headers, project["id"], asset["id"]) for asset in assets
        ]
        relationship = _relationship(
            client, headers, project["id"], assets[0]["id"], assets[1]["id"]
        )
        with Session(engine) as session:
            before_assets = {
                asset.id: (
                    asset.folder_id,
                    asset.storage_path,
                    asset.current_revision_id,
                    asset.deleted_at,
                )
                for asset in session.exec(
                    select(Asset).where(Asset.id.in_(asset_ids))
                )
            }
        try:
            active_delete = client.post(
                f"/project/{project['id']}/permanent",
                headers=headers,
                json={"confirmation": PROJECT_DELETE_CONFIRMATION},
            )
            assert active_delete.status_code == 404
            assert client.delete(
                f"/asset/{assets[1]['id']}", headers=headers
            ).status_code == 200
            assert client.delete(
                f"/project/{project['id']}", headers=headers
            ).status_code == 200
            assert client.get(
                f"/project/{project['id']}", headers=headers
            ).status_code == 404

            trash = client.get(
                "/projects/trash?limit=1&offset=0", headers=headers
            )
            assert trash.status_code == 200
            assert trash.headers["x-has-more"] == "false"
            assert trash.headers["x-next-offset"] == "1"
            assert trash.json() == [
                {
                    "id": project["id"],
                    "name": project["name"],
                    "deleted_at": trash.json()[0]["deleted_at"],
                    "member_count": 2,
                    "active_member_count": 1,
                    "trashed_member_count": 1,
                    "relationship_count": 1,
                }
            ]

            restored = client.post(
                f"/project/{project['id']}/restore", headers=headers
            )
            assert restored.status_code == 200
            assert restored.json()["id"] == project["id"]
            assert restored.json()["deleted_at"] is None
            with Session(engine) as session:
                assert [
                    (row.project_id, row.asset_id, row.created_at)
                    for row in session.exec(
                        select(ProjectMembership)
                        .where(ProjectMembership.project_id == project["id"])
                        .order_by(ProjectMembership.asset_id)
                    )
                ] == sorted(
                    [
                        (row["project_id"], row["asset_id"], row["created_at"])
                        for row in memberships
                    ]
                )
                assert session.get(ProjectRelationship, relationship["id"]) is not None
            assert client.post(
                f"/trash/{assets[1]['id']}/restore", headers=headers, json={}
            ).status_code == 200

            assert client.delete(
                f"/project/{project['id']}", headers=headers
            ).status_code == 200
            conflicting = _project(client, headers, project["name"])
            project_ids.append(conflicting["id"])
            conflict = client.post(
                f"/project/{project['id']}/restore", headers=headers
            )
            assert conflict.status_code == 409
            assert conflict.json()["detail"]["code"] == "project_name_conflict"

            wrong = client.post(
                f"/project/{project['id']}/permanent",
                headers=headers,
                json={"confirmation": "DELETE"},
            )
            assert wrong.status_code == 400
            with Session(engine) as session:
                assert session.get(Project, project["id"]) is not None

            deleted = client.post(
                f"/project/{project['id']}/permanent",
                headers=headers,
                json={"confirmation": PROJECT_DELETE_CONFIRMATION},
            )
            assert deleted.status_code == 200
            assert deleted.json() == {
                "project_id": project["id"],
                "name": project["name"],
                "memberships_deleted": 2,
                "relationships_deleted": 1,
            }
            project_ids.remove(project["id"])
            with Session(engine) as session:
                assert session.get(Project, project["id"]) is None
                assert session.get(ProjectRelationship, relationship["id"]) is None
                assert list(session.exec(
                    select(ProjectMembership).where(
                        ProjectMembership.project_id == project["id"]
                    )
                )) == []
                after_assets = {
                    asset.id: (
                        asset.folder_id,
                        asset.storage_path,
                        asset.current_revision_id,
                        asset.deleted_at,
                    )
                    for asset in session.exec(
                        select(Asset).where(Asset.id.in_(asset_ids))
                    )
                }
            assert after_assets == before_assets
            assert client.get(assets[0]["url"], headers=headers).content == b"first lifecycle bytes"
            assert client.get(assets[1]["url"], headers=headers).content == b"second lifecycle bytes"
        finally:
            _remove_projects(project_ids)
            _purge_assets(client, headers, asset_ids)


def test_project_export_failure_removes_temporary_archive(monkeypatch) -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Export Failure {suffix}")
        project_ids.append(project["id"])
        before = _exports()

        class BrokenZipFile:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                raise RuntimeError("simulated archive failure")

            def __exit__(self, exc_type, exc, traceback):
                return False

        monkeypatch.setattr(project_export, "ZipFile", BrokenZipFile)
        try:
            with pytest.raises(RuntimeError, match="simulated archive failure"):
                project_export.build_project_export(project["id"])
            assert _exports() == before
        finally:
            _remove_projects(project_ids)


def test_project_export_preserves_history_roles_relationships_and_unavailable_truth(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    changed_storage_path: str | None = None
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Export {suffix}")
        project_ids.append(project["id"])
        managed = _asset(client, headers, f"managed-{suffix}.stl", b"revision one")
        changed = _asset(client, headers, f"external-{suffix}.stl", b"external fixture")
        asset_ids.extend([managed["id"], changed["id"]])
        managed_membership = _join(client, headers, project["id"], managed["id"])
        changed_membership = _join(client, headers, project["id"], changed["id"])
        relationship = _relationship(
            client, headers, project["id"], changed["id"], managed["id"]
        )
        try:
            supporting = client.post(
                f"/asset/{managed['id']}/files",
                headers=headers,
                files={"file": ("assembly.pdf", b"assembly notes", "application/pdf")},
            )
            assert supporting.status_code == 200
            replacement = client.post(
                f"/asset/{managed['id']}/revisions",
                headers=headers,
                data={"change_note": "Second edition"},
                files={"file": ("replacement.stl", b"revision two", "model/stl")},
            )
            assert replacement.status_code == 200
            current_revision_id = replacement.json()["revision"]["id"]
            scoped = client.post(
                f"/asset/{managed['id']}/files",
                headers=headers,
                data={"revision_id": current_revision_id},
                files={"file": ("plate-notes.txt", b"revision notes", "text/plain")},
            )
            assert scoped.status_code == 200
            prepared = client.post(
                f"/asset/{managed['id']}/files",
                headers=headers,
                data={"revision_id": current_revision_id},
                files={"file": ("prepared.gcode", b"G28\nG1 X10\n", "text/plain")},
            )
            assert prepared.status_code == 200

            with Session(engine) as session:
                changed_asset = session.get(Asset, changed["id"])
                changed_revision = session.get(
                    ArtifactRevision, changed_asset.current_revision_id
                )
                changed_storage_path = changed_revision.storage_path
                changed_revision.content_state = "changed"
                changed_revision.content_reason = "external source sha256 changed"
                changed_revision.observed_sha256 = "observed-external-sha256"
                changed_revision.source_path = "/external/library/missing-source.stl"
                session.add(changed_revision)
                session.commit()
            assert client.delete(
                f"/asset/{changed['id']}", headers=headers
            ).status_code == 200

            before_exports = _exports()
            zip64_calls: list[bool] = []
            reserve_calls: list[tuple[Path, int]] = []
            real_zipfile = project_export.ZipFile
            real_reserve = project_export.ensure_storage_reserve

            def observed_zipfile(*args, **kwargs):
                zip64_calls.append(kwargs.get("allowZip64"))
                return real_zipfile(*args, **kwargs)

            def observed_reserve(path: Path, expected_bytes: int):
                reserve_calls.append((path, expected_bytes))
                return real_reserve(path, expected_bytes)

            monkeypatch.setattr(project_export, "ZipFile", observed_zipfile)
            monkeypatch.setattr(project_export, "ensure_storage_reserve", observed_reserve)
            exported = client.get(
                f"/project/{project['id']}/export", headers=headers
            )
            assert exported.status_code == 200
            assert exported.headers["cache-control"] == "private, no-store"
            assert "attachment" in exported.headers["content-disposition"].lower()
            assert zip64_calls == [True]
            assert len(reserve_calls) == 1
            assert reserve_calls[0][0] == (STORAGE / ".exports").resolve()
            assert reserve_calls[0][1] >= len(b"revision one") + len(b"revision two")
            assert _exports() == before_exports

            with ZipFile(BytesIO(exported.content)) as archive:
                names = archive.namelist()
                assert names == sorted(names)
                manifest = json.loads(archive.read("manifest.json"))
                assert manifest["format"] == "makersvault-project-export"
                assert manifest["version"] == 1
                assert manifest["project"] == {
                    "id": project["id"],
                    "name": project["name"],
                    "notes": "Project lifecycle evidence",
                    "creator": "MakersVault tests",
                    "source_url": "https://example.com/project",
                    "license": "CERN-OHL-S-2.0",
                    "tags": ["relay", "evidence"],
                    "created_at": project["created_at"],
                    "updated_at": project["updated_at"],
                }
                assert manifest["memberships"] == sorted(
                    [
                        {
                            "artifact_id": managed["id"],
                            "created_at": managed_membership["created_at"],
                            "artifact_state": "active",
                        },
                        {
                            "artifact_id": changed["id"],
                            "created_at": changed_membership["created_at"],
                            "artifact_state": "trashed",
                        },
                    ],
                    key=lambda row: row["artifact_id"],
                )
                assert manifest["relationships"] == [
                    {
                        "id": relationship["id"],
                        "source_asset_id": changed["id"],
                        "target_asset_id": managed["id"],
                        "kind": "documentation_for",
                        "created_at": relationship["created_at"],
                    }
                ]
                artifacts = {row["id"]: row for row in manifest["artifacts"]}
                assert artifacts[managed["id"]]["export_status"] == "complete"
                assert artifacts[changed["id"]]["export_status"] == "unavailable"
                assert artifacts[changed["id"]]["state"] == "trashed"

                managed_prefix = f"artifacts/{managed['id']}"
                changed_prefix = f"artifacts/{changed['id']}"
                managed_history = json.loads(
                    archive.read(f"{managed_prefix}/manifest.json")
                )
                changed_history = json.loads(
                    archive.read(f"{changed_prefix}/manifest.json")
                )
                assert managed_history["format"] == "makersvault-artifact-history"
                assert len(managed_history["revisions"]) == 2
                assert all(
                    revision["primary_entry"].startswith(f"{managed_prefix}/revisions/")
                    for revision in managed_history["revisions"]
                )
                assert any(
                    name.startswith(f"{managed_prefix}/attachments/artifact/")
                    for name in names
                )
                assert any(
                    f"{managed_prefix}/revisions/2/attachments/" in name
                    for name in names
                )
                assert any(
                    f"{managed_prefix}/revisions/2/prepared/" in name
                    for name in names
                )
                related_files = managed_history["artifact_files"] + [
                    record
                    for revision in managed_history["revisions"]
                    for record in revision["files"]
                ]
                assert {record["sha256"] for record in related_files} == {
                    hashlib.sha256(payload).hexdigest()
                    for payload in (
                        b"assembly notes",
                        b"revision notes",
                        b"G28\nG1 X10\n",
                    )
                }
                assert all(
                    record["available"] and record["content_state"] == "ready"
                    for record in related_files
                )
                assert changed_history["revisions"][0]["content_state"] == "changed"
                assert changed_history["revisions"][0]["content_reason"] == (
                    "external source sha256 changed"
                )
                assert changed_history["revisions"][0]["observed_sha256"] == (
                    "observed-external-sha256"
                )
                assert changed_history["revisions"][0]["primary_entry"] is None
                assert not any(
                    name.startswith(f"{changed_prefix}/revisions/")
                    and not name.endswith("manifest.json")
                    for name in names
                )
                assert not any("external/library" in name for name in names)
        finally:
            if changed_storage_path:
                with Session(engine) as session:
                    changed_asset = session.get(Asset, changed["id"])
                    if changed_asset:
                        changed_revision = session.get(
                            ArtifactRevision, changed_asset.current_revision_id
                        )
                        changed_revision.storage_path = changed_storage_path
                        session.add(changed_revision)
                        session.commit()
            _remove_projects(project_ids)
            _purge_assets(client, headers, asset_ids)
