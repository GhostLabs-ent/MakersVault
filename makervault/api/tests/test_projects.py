from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from db import engine
from main import app
from models import Asset, Project, ProjectMembership


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _project(client: TestClient, headers: dict[str, str], name: str, **metadata) -> dict:
    response = client.post(
        "/projects",
        headers=headers,
        json={"name": name, **metadata},
    )
    assert response.status_code == 201
    return response.json()


def _asset(client: TestClient, headers: dict[str, str], filename: str) -> dict:
    response = client.post(
        "/upload",
        headers=headers,
        files={"file": (filename, b"cube([1, 2, 3]);\n", "text/plain")},
    )
    assert response.status_code == 200
    return response.json()


def _remove_project_rows(project_ids: list[str]) -> None:
    with Session(engine) as session:
        memberships = list(
            session.exec(
                select(ProjectMembership).where(
                    ProjectMembership.project_id.in_(project_ids)
                )
            )
        )
        for membership in memberships:
            session.delete(membership)
        for project_id in project_ids:
            project = session.get(Project, project_id)
            if project:
                session.delete(project)
        session.commit()


def test_project_routes_require_authentication() -> None:
    with TestClient(app) as client:
        assert client.get("/projects").status_code == 401
        assert client.post("/projects", json={"name": "Denied"}).status_code == 401
        assert client.get(f"/project/{uuid4()}").status_code == 401
        assert client.post(f"/project/{uuid4()}/items/{uuid4()}").status_code == 401


def test_project_crud_validates_metadata_and_active_name_uniqueness() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        created = _project(
            client,
            headers,
            f"  ATAK Relay {suffix}  ",
            notes="Field relay build",
            creator="MakersVault",
            source_url="https://example.com/relay",
            license="CERN-OHL-S-2.0",
            tags=["radio", " enclosure ", "radio"],
        )
        project_ids.append(created["id"])
        try:
            assert created["name"] == f"ATAK Relay {suffix}"
            assert created["notes"] == "Field relay build"
            assert created["tags"] == ["radio", "enclosure"]
            assert created["member_count"] == 0
            assert created["deleted_at"] is None

            fetched = client.get(f"/project/{created['id']}", headers=headers)
            assert fetched.status_code == 200
            assert fetched.json() == created

            listed = client.get(f"/projects?q={suffix}", headers=headers)
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()] == [created["id"]]

            duplicate = client.post(
                "/projects",
                headers=headers,
                json={"name": f"atak relay {suffix.upper()}"},
            )
            assert duplicate.status_code == 409

            updated = client.patch(
                f"/project/{created['id']}",
                headers=headers,
                json={"name": f"Relay Mk II {suffix}", "notes": None, "tags": ["tested"]},
            )
            assert updated.status_code == 200
            assert updated.json()["name"] == f"Relay Mk II {suffix}"
            assert updated.json()["notes"] is None
            assert updated.json()["tags"] == ["tested"]
            assert updated.json()["updated_at"] >= created["updated_at"]

            assert client.post("/projects", headers=headers, json={"name": "   "}).status_code == 422
            assert client.patch(
                f"/project/{created['id']}",
                headers=headers,
                json={"source_url": "file:///etc/passwd"},
            ).status_code == 422
        finally:
            _remove_project_rows(project_ids)


def test_membership_is_many_to_many_and_never_changes_artifact_storage() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        first = _project(client, headers, f"Reusable A {suffix}")
        second = _project(client, headers, f"Reusable B {suffix}")
        project_ids.extend([first["id"], second["id"]])
        asset = _asset(client, headers, f"reusable-{suffix}.scad")
        try:
            before = client.get(f"/assets?q=reusable-{suffix}", headers=headers).json()[0]
            for project in (first, second):
                added = client.post(
                    f"/project/{project['id']}/items/{asset['id']}",
                    headers=headers,
                )
                assert added.status_code == 201
                assert added.json()["project_id"] == project["id"]
                assert added.json()["asset_id"] == asset["id"]

            duplicate = client.post(
                f"/project/{first['id']}/items/{asset['id']}",
                headers=headers,
            )
            assert duplicate.status_code == 409

            first_items = client.get(
                f"/project/{first['id']}/items", headers=headers
            )
            second_items = client.get(
                f"/project/{second['id']}/items", headers=headers
            )
            assert [row["id"] for row in first_items.json()] == [asset["id"]]
            assert [row["id"] for row in second_items.json()] == [asset["id"]]

            after = client.get(f"/assets?q=reusable-{suffix}", headers=headers).json()[0]
            assert after["id"] == before["id"]
            assert after["folder_id"] == before["folder_id"]
            assert after["storage_path"] == before["storage_path"]
            assert after["current_revision_id"] == before["current_revision_id"]
            assert client.get(after["url"], headers=headers).content == b"cube([1, 2, 3]);\n"

            removed = client.delete(
                f"/project/{first['id']}/items/{asset['id']}", headers=headers
            )
            assert removed.status_code == 200
            assert removed.json() == {"ok": True}
            assert client.get(f"/project/{first['id']}/items", headers=headers).json() == []
            assert [
                row["id"]
                for row in client.get(
                    f"/project/{second['id']}/items", headers=headers
                ).json()
            ] == [asset["id"]]
            assert client.get(after["url"], headers=headers).status_code == 200
        finally:
            _remove_project_rows(project_ids)
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_project_delete_is_metadata_only_and_preserves_membership_and_artifact() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Metadata Delete {suffix}")
        project_ids.append(project["id"])
        asset = _asset(client, headers, f"delete-safe-{suffix}.scad")
        try:
            assert client.post(
                f"/project/{project['id']}/items/{asset['id']}", headers=headers
            ).status_code == 201

            deleted = client.delete(f"/project/{project['id']}", headers=headers)
            assert deleted.status_code == 200
            assert deleted.json() == {"ok": True}
            assert client.get(f"/project/{project['id']}", headers=headers).status_code == 404
            assert all(
                row["id"] != project["id"]
                for row in client.get("/projects", headers=headers).json()
            )

            with Session(engine) as session:
                stored_project = session.get(Project, project["id"])
                stored_asset = session.get(Asset, asset["id"])
                membership = session.get(ProjectMembership, (project["id"], asset["id"]))
                assert stored_project is not None and stored_project.deleted_at is not None
                assert stored_asset is not None and stored_asset.deleted_at is None
                assert membership is not None

            assert client.get(asset["url"], headers=headers).status_code == 200
        finally:
            _remove_project_rows(project_ids)
            client.delete(f"/asset/{asset['id']}", headers=headers)


def test_artifact_trash_restore_and_permanent_purge_preserve_membership_rules() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Trash Membership {suffix}")
        project_ids.append(project["id"])
        asset = _asset(client, headers, f"trash-member-{suffix}.scad")
        try:
            assert client.post(
                f"/project/{project['id']}/items/{asset['id']}", headers=headers
            ).status_code == 201

            assert client.delete(f"/asset/{asset['id']}", headers=headers).status_code == 200
            assert client.get(
                f"/project/{project['id']}/items", headers=headers
            ).json() == []
            with Session(engine) as session:
                assert session.get(
                    ProjectMembership, (project["id"], asset["id"])
                ) is not None

            restored = client.post(
                f"/trash/{asset['id']}/restore", headers=headers, json={}
            )
            assert restored.status_code == 200
            assert [
                row["id"]
                for row in client.get(
                    f"/project/{project['id']}/items", headers=headers
                ).json()
            ] == [asset["id"]]

            assert client.delete(f"/asset/{asset['id']}", headers=headers).status_code == 200
            purged = client.post(
                "/trash/permanent",
                headers=headers,
                json={
                    "asset_ids": [asset["id"]],
                    "confirmation": "PERMANENTLY DELETE",
                },
            )
            assert purged.status_code == 200
            assert purged.json()[0]["status"] == "deleted"
            with Session(engine) as session:
                assert session.get(Asset, asset["id"]) is None
                assert session.get(
                    ProjectMembership, (project["id"], asset["id"])
                ) is None
        finally:
            _remove_project_rows(project_ids)
