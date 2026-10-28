"""`POST /download/zip` restricted to a project's members (Mf-6cxs).

The project landing page's "Download all" button sends `project_id`, so the zip
must be exactly the membership set and nothing else - a same-folder asset that
is not a member must not leak in. `project_id` is one more AND filter beside
`asset_ids`/`tag`/`folder_id`, and the project name wins the download filename.

An unknown project is a 404, but an existing project with no resolvable files is
a 200 with a valid empty archive: the project exists, its file set is empty. That
is deliberately different from the tag/folder/asset_ids paths, which keep their
404.

Every test works in a temporary storage root (``db``, ``main``, ``library_scan``,
``asset_service`` and ``asset_file_service`` all bind paths at import time). The
database is shared for the whole session, so rows created by a test are deleted
again at teardown.
"""

from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, select

import asset_file_service
import asset_service
import db
import library_scan
import main
import settings_service
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, Folder, Project, ProjectAsset

STL_BYTES = b"solid cube\nendsolid cube\n"


# --- infrastructure ---------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage at a temp root, restore the template and undo every row made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    # The schema is created by the app lifespan; a single-file run needs it first.
    run_migrations(engine)
    template_before = settings_service.get_storage_template()
    with Session(engine) as session:
        projects_before = {project.id for project in session.exec(select(Project))}
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
    yield storage
    settings_service.set_storage_template(template_before)
    with Session(engine) as session:
        # Projects first: `idx_project_name_unique` is case-insensitive, so a
        # leaked row would 409 the next test's project.
        for membership in list(session.exec(select(ProjectAsset))):
            if membership.project_id not in projects_before:
                session.delete(membership)
        for project in list(session.exec(select(Project))):
            if project.id not in projects_before:
                session.delete(project)
        for asset_file in list(session.exec(select(AssetFile))):
            if asset_file.asset_id not in assets_before:
                session.delete(asset_file)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def unique(prefix: str) -> str:
    """A name no other test row can collide with (the project index is NOCASE)."""
    return f"{prefix}-{uuid4().hex}"


def create_project(client: TestClient, headers: dict, name: str | None = None, **fields) -> dict:
    response = client.post("/projects", json={"name": name or unique("project"), **fields}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def upload(client: TestClient, headers: dict, name: str, folder_id: str | None = None) -> dict:
    data = {"folder_id": folder_id} if folder_id else {}
    response = client.post("/upload", files={"file": (name, STL_BYTES, "model/stl")}, data=data, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def create_folder(client: TestClient, headers: dict, name: str) -> dict:
    response = client.post("/folders", json={"name": name, "tags": [], "parent_id": None}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def add_members(client: TestClient, headers: dict, project_id: str, asset_ids: list[str]) -> dict:
    response = client.post(f"/project/{project_id}/assets", json={"asset_ids": asset_ids}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def download(client: TestClient, headers: dict, **body) -> Response:
    return client.post("/download/zip", json=body, headers=headers)


def zip_entries(response: Response) -> list[str]:
    """The archive's entry names, from a successful 200 response."""
    with ZipFile(BytesIO(response.content)) as archive:
        return archive.namelist()


# --- project membership -----------------------------------------------------


def test_project_zip_contains_the_members_and_not_a_same_folder_sibling() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        shelf = create_folder(client, headers, unique("Shelf"))
        member = upload(client, headers, "member.stl", shelf["id"])
        upload(client, headers, "outsider.stl", shelf["id"])
        project = create_project(client, headers)
        add_members(client, headers, project["id"], [member["id"]])

        response = download(client, headers, project_id=project["id"])

        assert response.status_code == 200, response.text
        names = zip_entries(response)
        assert any(name.endswith("/member.stl") for name in names), names
        assert not any(name.endswith("/outsider.stl") for name in names), names
        assert len(names) == 1, names


def test_project_zip_and_asset_ids_compose_as_an_and_filter() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        first = upload(client, headers, "first.stl")
        second = upload(client, headers, "second.stl")
        project = create_project(client, headers)
        add_members(client, headers, project["id"], [first["id"], second["id"]])

        response = download(client, headers, project_id=project["id"], asset_ids=[first["id"]])

        assert response.status_code == 200, response.text
        names = zip_entries(response)
        assert any(name.endswith("/first.stl") for name in names), names
        assert not any(name.endswith("/second.stl") for name in names), names


def test_project_zip_404_for_an_unknown_project() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = download(client, headers, project_id=uuid4().hex)

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Project not found"


def test_empty_project_is_a_200_with_a_valid_empty_zip() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)

        response = download(client, headers, project_id=project["id"])

        assert response.status_code == 200, response.text
        assert zip_entries(response) == [], "an existing project is an empty archive, not a 404"


def test_project_with_no_resolvable_files_is_a_200_empty_zip() -> None:
    """Membership can outlive the bytes: a missing member file is not a 404."""
    with TestClient(main.app) as client:
        headers = auth_header(client)
        member = upload(client, headers, "vanished.stl")
        project = create_project(client, headers)
        add_members(client, headers, project["id"], [member["id"]])
        with Session(engine) as session:
            row = session.get(Asset, member["id"])
            assert row is not None
            asset_service.managed_asset_path(row).unlink()

        response = download(client, headers, project_id=project["id"])

        assert response.status_code == 200, response.text
        assert zip_entries(response) == []


def test_download_filename_derives_from_the_project_name() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers, name=unique("Robot Arm Kit"))

        response = download(client, headers, project_id=project["id"])

        assert response.status_code == 200, response.text
        disposition = response.headers["content-disposition"]
        safe_name = project["name"].replace(" ", "_")[:50]
        assert f'filename="{safe_name}.zip"' in disposition, disposition


def test_project_name_wins_the_filename_over_tag_and_folder() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        shelf = create_folder(client, headers, unique("Bench"))
        member = upload(client, headers, "tagged.stl", shelf["id"])
        tagged = client.post(f"/asset/{member['id']}/tags", json={"tags": ["metal"]}, headers=headers)
        assert tagged.status_code == 200, tagged.text
        project = create_project(client, headers, name=unique("Project Name"))
        add_members(client, headers, project["id"], [member["id"]])

        response = download(
            client,
            headers,
            project_id=project["id"],
            tag="metal",
            folder_id=shelf["id"],
            filename="ignored.zip",
        )

        assert response.status_code == 200, response.text
        disposition = response.headers["content-disposition"]
        safe_name = project["name"].replace(" ", "_")[:50]
        assert f'filename="{safe_name}.zip"' in disposition, disposition


def test_tag_without_a_project_still_404s_when_nothing_matches() -> None:
    """The empty-archive behaviour is the project branch only, not a global change."""
    with TestClient(main.app) as client:
        headers = auth_header(client)
        upload(client, headers, "untagged.stl")

        response = download(client, headers, tag=unique("missing-tag"))

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "No files available for download"
