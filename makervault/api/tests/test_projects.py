from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import main as main_module
from db import engine
from main import app
from models import Asset, Project, ProjectMembership
from schemas import ImportZipExtractRequest
from zip_service import extract_zip_entries_to_assets


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


def test_project_list_items_candidates_and_unassigned_views_are_bounded() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    with TestClient(app) as client:
        headers = _headers(client)
        projects = [
            _project(client, headers, f"Paged {suffix} {index:02d}")
            for index in range(4)
        ]
        project_ids.extend(project["id"] for project in projects)
        first, second = projects[:2]
        assets = [
            _asset(client, headers, f"scope-{suffix}-{index:02d}.scad")
            for index in range(4)
        ]
        asset_ids.extend(asset["id"] for asset in assets)
        try:
            page = client.get(
                f"/projects?q=Paged%20{suffix}&limit=2&offset=0",
                headers=headers,
            )
            assert page.status_code == 200
            assert [row["name"] for row in page.json()] == [
                f"Paged {suffix} 00",
                f"Paged {suffix} 01",
            ]
            assert page.headers["x-has-more"] == "true"
            assert page.headers["x-next-offset"] == "2"
            final_page = client.get(
                f"/projects?q=Paged%20{suffix}&limit=2&offset=2",
                headers=headers,
            )
            assert final_page.headers["x-has-more"] == "false"

            for asset in assets[:2]:
                assert client.post(
                    f"/project/{first['id']}/items/{asset['id']}", headers=headers
                ).status_code == 201
            assert client.post(
                f"/project/{second['id']}/items/{assets[2]['id']}", headers=headers
            ).status_code == 201
            for asset in assets[:2]:
                assert client.post(
                    f"/asset/{asset['id']}/tags",
                    headers=headers,
                    json={"tags": [f"project-{suffix}"]},
                ).status_code == 200

            items = client.get(
                f"/project/{first['id']}/items?q=scope-{suffix}&tags=project-{suffix}&limit=1&offset=0",
                headers=headers,
            )
            assert items.status_code == 200
            assert len(items.json()) == 1
            assert items.headers["x-has-more"] == "true"
            assert items.headers["x-next-offset"] == "1"
            assert client.get(
                f"/project/{first['id']}/tags", headers=headers
            ).json() == [f"project-{suffix}"]

            scoped = client.get(
                f"/assets?project_id={first['id']}&q=scope-{suffix}&limit=10",
                headers=headers,
            )
            assert [row["id"] for row in scoped.json()] == [
                assets[0]["id"],
                assets[1]["id"],
            ]

            candidates = client.get(
                f"/project/{first['id']}/candidates?q=scope-{suffix}&limit=10",
                headers=headers,
            )
            assert [row["id"] for row in candidates.json()] == [
                assets[2]["id"],
                assets[3]["id"],
            ]

            unassigned = client.get(
                f"/assets?project_unassigned=true&q=scope-{suffix}&limit=10",
                headers=headers,
            )
            assert [row["id"] for row in unassigned.json()] == [assets[3]["id"]]

            assert client.delete(f"/project/{second['id']}", headers=headers).status_code == 200
            after_project_trash = client.get(
                f"/assets?project_unassigned=true&q=scope-{suffix}&limit=10",
                headers=headers,
            )
            assert [row["id"] for row in after_project_trash.json()] == [
                assets[2]["id"],
                assets[3]["id"],
            ]

            invalid_scope = client.get(
                f"/assets?project_id={first['id']}&project_unassigned=true",
                headers=headers,
            )
            assert invalid_scope.status_code == 422
        finally:
            _remove_project_rows(project_ids)
            for asset_id in asset_ids:
                client.delete(f"/asset/{asset_id}", headers=headers)


def test_upload_may_join_one_project_without_changing_folder_semantics() -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    folder_id: str | None = None
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Upload Scope {suffix}")
        project_ids.append(project["id"])
        folder_response = client.post(
            "/folders",
            headers=headers,
            json={"name": f"Upload Folder {suffix}", "tags": [], "parent_id": None},
        )
        assert folder_response.status_code == 200
        folder_id = folder_response.json()["id"]
        try:
            upload = client.post(
                "/upload",
                headers=headers,
                data={"folder_id": folder_id, "project_id": project["id"]},
                files={
                    "file": (
                        f"project-upload-{suffix}.scad",
                        b"cube([4, 5, 6]);\n",
                        "text/plain",
                    )
                },
            )
            assert upload.status_code == 200
            asset = upload.json()
            asset_ids.append(asset["id"])
            assert asset["folder_id"] == folder_id
            assert asset["storage_path"]
            assert [
                row["id"]
                for row in client.get(
                    f"/project/{project['id']}/items", headers=headers
                ).json()
            ] == [asset["id"]]
            assert client.get(asset["url"], headers=headers).content == b"cube([4, 5, 6]);\n"

            legacy = _asset(client, headers, f"legacy-upload-{suffix}.scad")
            asset_ids.append(legacy["id"])
            assert client.get(
                f"/assets?project_unassigned=true&q=legacy-upload-{suffix}",
                headers=headers,
            ).json()[0]["id"] == legacy["id"]

            before = client.get(
                f"/assets?q=invalid-project-{suffix}", headers=headers
            ).json()
            invalid = client.post(
                "/upload",
                headers=headers,
                data={"project_id": str(uuid4())},
                files={
                    "file": (
                        f"invalid-project-{suffix}.scad",
                        b"cube([7, 8, 9]);\n",
                        "text/plain",
                    )
                },
            )
            assert invalid.status_code == 404
            assert client.get(
                f"/assets?q=invalid-project-{suffix}", headers=headers
            ).json() == before
        finally:
            _remove_project_rows(project_ids)
            for asset_id in asset_ids:
                client.delete(f"/asset/{asset_id}", headers=headers)
            if folder_id:
                client.delete(f"/folder/{folder_id}", headers=headers)


def test_link_import_may_join_project_and_validates_before_download(monkeypatch) -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    calls: list[tuple[str, str | None]] = []
    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Link Import {suffix}")
        project_ids.append(project["id"])
        asset = _asset(client, headers, f"link-import-{suffix}.scad")
        asset_ids.append(asset["id"])

        def fake_import(url, body):
            calls.append((url, body.project_id))
            with Session(engine) as session:
                return session.get(Asset, asset["id"])

        monkeypatch.setattr(main_module, "import_asset_from_url", fake_import)
        try:
            imported = client.post(
                "/import",
                headers=headers,
                json={
                    "url": "https://example.com/model.scad",
                    "project_id": project["id"],
                },
            )
            assert imported.status_code == 200
            assert imported.json()["id"] == asset["id"]
            assert calls == [("https://example.com/model.scad", project["id"])]
            assert [
                row["id"]
                for row in client.get(
                    f"/project/{project['id']}/items", headers=headers
                ).json()
            ] == [asset["id"]]

            invalid = client.post(
                "/import",
                headers=headers,
                json={
                    "url": "https://example.com/never-downloaded.scad",
                    "project_id": str(uuid4()),
                },
            )
            assert invalid.status_code == 404
            assert len(calls) == 1
        finally:
            _remove_project_rows(project_ids)
            for asset_id in asset_ids:
                client.delete(f"/asset/{asset_id}", headers=headers)


def test_selected_zip_import_joins_project(tmp_path) -> None:
    suffix = uuid4().hex[:8]
    project_ids: list[str] = []
    asset_ids: list[str] = []
    archive = tmp_path / f"project-{suffix}.zip"
    entry_name = f"selected-{suffix}.scad"
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr(entry_name, b"cube([10, 11, 12]);\n")

    with TestClient(app) as client:
        headers = _headers(client)
        project = _project(client, headers, f"Selected ZIP {suffix}")
        project_ids.append(project["id"])
        try:
            assets, failed = extract_zip_entries_to_assets(
                archive,
                [entry_name],
                ImportZipExtractRequest(
                    url="https://example.com/project.zip",
                    entries=[entry_name],
                    project_id=project["id"],
                ),
            )
            assert failed == []
            assert len(assets) == 1
            asset_ids.append(assets[0].id)
            assert [
                row["id"]
                for row in client.get(
                    f"/project/{project['id']}/items", headers=headers
                ).json()
            ] == asset_ids
            assert client.get(
                f"/file/{assets[0].id}/{entry_name}", headers=headers
            ).content == b"cube([10, 11, 12]);\n"
        finally:
            _remove_project_rows(project_ids)
            for asset_id in asset_ids:
                client.delete(f"/asset/{asset_id}", headers=headers)
