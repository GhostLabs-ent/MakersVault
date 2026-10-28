"""Project endpoints (Mf-bl86): rows, memberships and the cover reference.

A project is a database row plus a join table (`project`, `project_asset`,
migration 007). It owns no storage path and no bytes, so the contract these
tests pin is "rows only": deleting a project deletes its memberships and nothing
else, and no route on this surface creates, moves or removes a file.

The other half is the listing contract. `GET /project/{project_id}/assets` must
behave exactly like `GET /assets` - same `AssetOut` shape, same
`name, filename, id` ordering, same `X-Has-More`/`X-Next-Offset` headers only
when `limit` is given - because two listings that disagree are two bugs.

`cover_asset_id` is a free reference: it needs no membership, removing the
membership leaves it alone, and deleting the asset NULLs it through the schema's
`ON DELETE SET NULL` (pinned here at the API level).

Every test works in a temporary storage root (`db`, `main`, `library_scan`,
`asset_service` and `asset_file_service` all bind paths at import time). The
database is shared for the whole session, so the project, asset and folder rows a
test created are deleted again at teardown.
"""

import json
import re
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event
from sqlmodel import Session, select

import asset_file_service
import asset_service
import audit
import db
import library_scan
import main
import settings_service
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Folder, Project, ProjectAsset

REQUEST_ID_HEADER = "X-Request-ID"
STL_BYTES = b"solid cube\nendsolid cube\n"
# ISO-8601 UTC at microsecond precision, the format migration 007 stores.
ISO_MICROSECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")

# --- infrastructure ---------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage at a temp root, restore the template and undo every row made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    # main binds THUMBS at import time and its serializer builds the thumb URL.
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
    """Upload one model and return its AssetOut body."""
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


def remove_members(client: TestClient, headers: dict, project_id: str, asset_ids: list[str]) -> dict:
    # The only DELETE route with a JSON body: send it explicitly.
    response = client.request("DELETE", f"/project/{project_id}/assets", json={"asset_ids": asset_ids}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def project_listing(client: TestClient, headers: dict) -> dict[str, dict]:
    response = client.get("/projects", headers=headers)
    assert response.status_code == 200, response.text
    return {project["id"]: project for project in response.json()}


def project_asset_ids(client: TestClient, headers: dict, project_id: str, **params) -> list[str]:
    response = client.get(f"/project/{project_id}/assets", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return [asset["id"] for asset in response.json()]


def events_for(request_id: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.request_id == request_id)))


def project_asset_rows(project_id: str) -> list[ProjectAsset]:
    with Session(engine) as session:
        return list(session.exec(select(ProjectAsset).where(ProjectAsset.project_id == project_id)))


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (30, 120, 200)).save(buffer, "PNG")
    return buffer.getvalue()


# --- POST /projects ---------------------------------------------------------


def test_create_project_returns_the_row_without_the_internal_columns() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = client.post("/projects", json={"name": "  Chess Set  ", "description": "a set"}, headers=headers)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Chess Set", "the name is trimmed"
        assert body["description"] == "a set"
        assert body["origin"] == "own"
        assert body["asset_count"] == 0
        assert body["cover_asset_id"] is None
        assert body["cover_thumb_url"] is None
        assert body["creator"] is None
        assert body["source_url"] is None
        assert body["licence"] is None
        assert body["licence_url"] is None
        assert "owner_id" not in body, "owner_id is not exposed"
        assert "metadata_json" not in body, "metadata_json is not exposed"
        assert ISO_MICROSECONDS.match(body["created_at"]), body["created_at"]
        assert body["created_at"] == body["updated_at"], "a fresh project has one timestamp"


def test_create_project_rejects_a_name_that_differs_only_by_case() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        create_project(client, headers, name="PLA Parts")

        response = client.post("/projects", json={"name": "pla parts"}, headers=headers)

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "Project name already exists"


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_create_project_rejects_a_blank_name(name: str) -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = client.post("/projects", json={"name": name}, headers=headers)

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "name is required"


def test_create_project_rejects_an_unknown_cover_asset() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = client.post("/projects", json={"name": unique("cover"), "cover_asset_id": uuid4().hex}, headers=headers)

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Asset not found"
        assert project_listing(client, headers) == {}, "the failed create must not leave a row"


# --- GET /projects ---------------------------------------------------------


def test_list_projects_reports_the_member_count() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        empty = create_project(client, headers)
        one = create_project(client, headers)
        many = create_project(client, headers)
        first = upload(client, headers, "alpha.stl")
        second = upload(client, headers, "beta.stl")
        third = upload(client, headers, "gamma.stl")
        add_members(client, headers, one["id"], [first["id"]])
        add_members(client, headers, many["id"], [first["id"], second["id"], third["id"]])

        listing = project_listing(client, headers)

        assert listing[empty["id"]]["asset_count"] == 0
        assert listing[one["id"]]["asset_count"] == 1
        assert listing[many["id"]]["asset_count"] == 3


def test_list_projects_orders_names_case_insensitively() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        later = create_project(client, headers, name=f"banana-{uuid4().hex}")
        earlier = create_project(client, headers, name=f"Apple-{uuid4().hex}")

        response = client.get("/projects", headers=headers)

        assert response.status_code == 200, response.text
        ids = [project["id"] for project in response.json()]
        assert ids.index(earlier["id"]) < ids.index(later["id"]), ids


def test_list_projects_is_one_statement_for_many_projects() -> None:
    """The N+1 requirement: the member count comes from the same aggregate query."""
    with TestClient(main.app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "member.stl")
        for name in ("alpha", "beta", "gamma", "delta"):
            project = create_project(client, headers, name=f"{name}-{uuid4().hex}")
            add_members(client, headers, project["id"], [asset["id"]])

        statements: list[str] = []

        def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
            if "FROM project" in statement:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.get("/projects", headers=headers)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code == 200, response.text
        assert len(response.json()) >= 4
        assert len(statements) == 1, statements


def test_list_projects_starts_empty() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = client.get("/projects", headers=headers)

        assert response.status_code == 200
        assert response.json() == [], "a leaked project from another test would mean teardown broke"


def test_cover_thumb_url_is_versioned_only_once_the_thumbnail_exists() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "covered.stl")
        project = create_project(client, headers, cover_asset_id=asset["id"])

        assert project["cover_thumb_url"] is None, "no generated thumbnail yet"

        generated = client.post(
            f"/asset/{asset['id']}/thumbnail-generated",
            files={"file": ("thumb.png", png_bytes(), "image/png")},
            headers=headers,
        )
        assert generated.status_code == 200, generated.text

        listed = project_listing(client, headers)[project["id"]]
        assert re.fullmatch(rf"/thumb/{asset['id']}\.jpg\?v=\d+", listed["cover_thumb_url"] or ""), listed


# --- GET /project/{project_id}/assets ---------------------------------------


def test_project_assets_have_the_same_shape_as_get_assets() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        asset = upload(client, headers, "shaped.stl")
        add_members(client, headers, project["id"], [asset["id"]])

        response = client.get(f"/project/{project['id']}/assets", headers=headers)
        listed = {row["id"]: row for row in client.get("/assets", headers=headers).json()}

        assert response.status_code == 200, response.text
        assert response.json() == [listed[asset["id"]]], "one AssetOut, byte for byte identical to /assets"


def test_project_assets_page_like_get_assets() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        members = [upload(client, headers, f"{name}.stl") for name in ("alpha", "beta", "gamma")]
        add_members(client, headers, project["id"], [asset["id"] for asset in members])

        first = client.get(f"/project/{project['id']}/assets", params={"limit": 2}, headers=headers)
        assets_page = client.get("/assets", params={"limit": 2}, headers=headers)
        second = client.get(f"/project/{project['id']}/assets", params={"limit": 2, "offset": 2}, headers=headers)

        assert first.status_code == 200, first.text
        assert [row["id"] for row in first.json()] == [row["id"] for row in assets_page.json()]
        assert first.headers["X-Has-More"] == "true"
        assert first.headers["X-Next-Offset"] == "2"
        assert len(second.json()) == 1
        assert second.headers["X-Has-More"] == "false"
        assert second.headers["X-Next-Offset"] == "3"


def test_project_assets_send_no_pagination_header_without_a_limit() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        asset = upload(client, headers, "unlimited.stl")
        add_members(client, headers, project["id"], [asset["id"]])

        response = client.get(f"/project/{project['id']}/assets", headers=headers)

        assert response.status_code == 200, response.text
        assert "X-Has-More" not in response.headers
        assert "X-Next-Offset" not in response.headers


def test_project_assets_filter_by_q_and_tags() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        tagged = upload(client, headers, "tagged.stl")
        other = upload(client, headers, "other.stl")
        add_members(client, headers, project["id"], [tagged["id"], other["id"]])
        response = client.post(f"/asset/{tagged['id']}/tags", json={"tags": ["metal"]}, headers=headers)
        assert response.status_code == 200, response.text

        by_q = project_asset_ids(client, headers, project["id"], q="tagged")
        by_tags = project_asset_ids(client, headers, project["id"], tags="metal")
        miss = project_asset_ids(client, headers, project["id"], tags="nope")

        assert by_q == [tagged["id"]]
        assert by_tags == [tagged["id"]]
        assert miss == []


def test_project_assets_span_folders() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        shelf = create_folder(client, headers, unique("Shelf"))
        bench = create_folder(client, headers, unique("Bench"))
        in_shelf = upload(client, headers, "shelf.stl", shelf["id"])
        in_bench = upload(client, headers, "bench.stl", bench["id"])
        add_members(client, headers, project["id"], [in_shelf["id"], in_bench["id"]])

        ids = project_asset_ids(client, headers, project["id"])

        assert set(ids) == {in_shelf["id"], in_bench["id"]}, "membership, not folder, decides the listing"


def test_project_assets_404_for_an_unknown_project() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = client.get(f"/project/{uuid4().hex}/assets", headers=headers)

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Project not found"


# --- PATCH /project/{project_id} --------------------------------------------


def test_patch_renames_a_project() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers, name="Before")

        response = client.patch(f"/project/{project['id']}", json={"name": "  After  "}, headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["name"] == "After"
        assert project_listing(client, headers)[project["id"]]["name"] == "After"


def test_patch_sets_and_clears_description_and_cover() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "coverable.stl")
        project = create_project(client, headers)

        described = client.patch(
            f"/project/{project['id']}",
            json={"description": "notes", "cover_asset_id": asset["id"]},
            headers=headers,
        )
        assert described.status_code == 200, described.text
        assert described.json()["description"] == "notes"
        assert described.json()["cover_asset_id"] == asset["id"]

        cleared = client.patch(
            f"/project/{project['id']}",
            json={"description": None, "cover_asset_id": None},
            headers=headers,
        )

        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["description"] is None, "an explicit null clears the column"
        assert cleared.json()["cover_asset_id"] is None, "an explicit null clears the column"


def test_patch_rejects_an_empty_body() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)

        response = client.patch(f"/project/{project['id']}", json={}, headers=headers)

        assert response.status_code == 422, response.text


def test_patch_rejects_an_unknown_key() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)

        response = client.patch(f"/project/{project['id']}", json={"creator": "someone"}, headers=headers)

        assert response.status_code == 422, response.text


def test_patch_404_for_an_unknown_project() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = client.patch(f"/project/{uuid4().hex}", json={"name": unique("nothing")}, headers=headers)

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Project not found"


def test_patch_409_for_a_duplicate_name() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        taken = create_project(client, headers, name="Taken")
        project = create_project(client, headers)

        response = client.patch(f"/project/{project['id']}", json={"name": taken["name"].lower()}, headers=headers)

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "Project name already exists"


def test_patch_404_for_an_unknown_cover() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)

        response = client.patch(f"/project/{project['id']}", json={"cover_asset_id": uuid4().hex}, headers=headers)

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Asset not found"
        assert project_listing(client, headers)[project["id"]]["cover_asset_id"] is None


def test_patch_bumps_updated_at_and_keeps_created_at() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)

        response = client.patch(f"/project/{project['id']}", json={"description": "later"}, headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created_at"] == project["created_at"]
        assert body["updated_at"] != project["updated_at"]
        assert body["updated_at"] > project["updated_at"], "ISO-8601 UTC sorts lexicographically"


def test_a_description_only_patch_writes_no_audit_row() -> None:
    """Rename-only emission, pinned by counting the rows for one request id."""
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        request_id = f"project-describe-{uuid4().hex}"

        response = client.patch(
            f"/project/{project['id']}",
            json={"description": "only metadata"},
            headers={**headers, REQUEST_ID_HEADER: request_id},
        )

        assert response.status_code == 200, response.text
        assert response.headers[REQUEST_ID_HEADER] == request_id
        assert events_for(request_id) == [], "a metadata-only PATCH is not a rename"


# --- DELETE /project/{project_id} -------------------------------------------


def test_delete_project_removes_its_rows_and_leaves_every_byte_alone() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        keep = upload(client, headers, "keep.stl")
        supporting = client.post(
            f"/asset/{keep['id']}/files",
            files={"file": ("notes.txt", b"notes\n", "text/plain")},
            headers=headers,
        )
        assert supporting.status_code == 200, supporting.text
        add_members(client, headers, project["id"], [keep["id"]])
        with Session(engine) as session:
            asset = session.get(Asset, keep["id"])
            path = asset_service.managed_asset_path(asset)
            file_rows_before = {row.id for row in session.exec(select(AssetFile).where(AssetFile.asset_id == keep["id"]))}
        bytes_before = path.read_bytes()
        assert bytes_before and path.exists()

        response = client.delete(f"/project/{project['id']}", headers=headers)

        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True}
        with Session(engine) as session:
            assert session.get(Project, project["id"]) is None
            assert list(session.exec(select(ProjectAsset).where(ProjectAsset.project_id == project["id"]))) == []
            assert session.get(Asset, keep["id"]) is not None, "the asset row survives its project"
            file_rows_after = {row.id for row in session.exec(select(AssetFile).where(AssetFile.asset_id == keep["id"]))}
        assert file_rows_after == file_rows_before
        assert path.exists(), "no byte on disk may be deleted with a project"
        assert path.read_bytes() == bytes_before


def test_delete_project_404_for_an_unknown_project() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)

        response = client.delete(f"/project/{uuid4().hex}", headers=headers)

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Project not found"


# --- POST /project/{project_id}/assets --------------------------------------


def test_add_project_assets_is_idempotent() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        asset = upload(client, headers, "twice.stl")

        first = add_members(client, headers, project["id"], [asset["id"]])
        second = add_members(client, headers, project["id"], [asset["id"]])

        assert first == {"added": [asset["id"]], "skipped": [], "failed": []}
        assert second == {"added": [], "skipped": [asset["id"]], "failed": []}
        assert len(project_asset_rows(project["id"])) == 1, "no duplicate join row"


def test_add_project_assets_reports_unknown_ids_per_id() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        first = upload(client, headers, "one.stl")
        second = upload(client, headers, "two.stl")
        missing = uuid4().hex

        response = client.post(
            f"/project/{project['id']}/assets",
            json={"asset_ids": [first["id"], missing, second["id"]]},
            headers=headers,
        )

        assert response.status_code == 200, "a partial success is a 200"
        assert response.json() == {
            "added": [first["id"], second["id"]],
            "skipped": [],
            "failed": [{"id": missing, "code": "not_found", "status": 404, "error": "Asset not found"}],
        }
        assert set(project_asset_ids(client, headers, project["id"])) == {first["id"], second["id"]}


def test_add_project_assets_requires_asset_ids() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)

        response = client.post(f"/project/{project['id']}/assets", json={"asset_ids": []}, headers=headers)

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "asset_ids is required"


def test_add_project_assets_404_for_an_unknown_project() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "orphan.stl")

        response = client.post(f"/project/{uuid4().hex}/assets", json={"asset_ids": [asset["id"]]}, headers=headers)

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Project not found"


def test_one_asset_can_belong_to_two_projects() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        first = create_project(client, headers)
        second = create_project(client, headers)
        shared = upload(client, headers, "shared.stl")

        add_members(client, headers, first["id"], [shared["id"]])
        add_members(client, headers, second["id"], [shared["id"]])

        listing = project_listing(client, headers)
        assert listing[first["id"]]["asset_count"] == 1
        assert listing[second["id"]]["asset_count"] == 1
        assert project_asset_ids(client, headers, first["id"]) == [shared["id"]]
        assert project_asset_ids(client, headers, second["id"]) == [shared["id"]]


# --- DELETE /project/{project_id}/assets ------------------------------------


def test_remove_project_assets_removes_the_memberships_only() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        kept = upload(client, headers, "kept.stl")
        removed = upload(client, headers, "removed.stl")
        add_members(client, headers, project["id"], [kept["id"], removed["id"]])
        with Session(engine) as session:
            asset = session.get(Asset, removed["id"])
            path = asset_service.managed_asset_path(asset)
        assert path.exists()

        response = client.request(
            "DELETE",
            f"/project/{project['id']}/assets",
            json={"asset_ids": [removed["id"]]},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"removed": [removed["id"]], "skipped": [], "failed": []}
        assert project_asset_ids(client, headers, project["id"]) == [kept["id"]]
        with Session(engine) as session:
            assert session.get(Asset, removed["id"]) is not None, "membership is not deletion"
        assert path.exists() and path.read_bytes() == STL_BYTES


def test_remove_project_assets_skips_non_members() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        stranger = upload(client, headers, "stranger.stl")

        response = client.request(
            "DELETE",
            f"/project/{project['id']}/assets",
            json={"asset_ids": [stranger["id"]]},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"removed": [], "skipped": [stranger["id"]], "failed": []}


def test_remove_project_assets_reports_unknown_ids_per_id() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        member = upload(client, headers, "member.stl")
        add_members(client, headers, project["id"], [member["id"]])
        missing = uuid4().hex

        response = client.request(
            "DELETE",
            f"/project/{project['id']}/assets",
            json={"asset_ids": [member["id"], missing]},
            headers=headers,
        )

        assert response.status_code == 200, "the valid removal still applies"
        assert response.json() == {
            "removed": [member["id"]],
            "skipped": [],
            "failed": [{"id": missing, "code": "not_found", "status": 404, "error": "Asset not found"}],
        }
        assert project_asset_rows(project["id"]) == []


def test_remove_project_assets_requires_asset_ids() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)

        response = client.request("DELETE", f"/project/{project['id']}/assets", json={"asset_ids": []}, headers=headers)

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "asset_ids is required"


def test_remove_project_assets_404_for_an_unknown_project() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        asset = upload(client, headers, "lonely.stl")

        response = client.request(
            "DELETE",
            f"/project/{uuid4().hex}/assets",
            json={"asset_ids": [asset["id"]]},
            headers=headers,
        )

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == "Project not found"


def test_remove_project_assets_is_idempotent() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers)
        asset = upload(client, headers, "once.stl")
        add_members(client, headers, project["id"], [asset["id"]])

        first = remove_members(client, headers, project["id"], [asset["id"]])
        second = remove_members(client, headers, project["id"], [asset["id"]])

        assert first == {"removed": [asset["id"]], "skipped": [], "failed": []}
        assert second == {"removed": [], "skipped": [asset["id"]], "failed": []}


# --- the cover reference ----------------------------------------------------


def test_a_cover_needs_no_membership_and_survives_membership_removal() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        cover = upload(client, headers, "cover.stl")
        project = create_project(client, headers, cover_asset_id=cover["id"])

        assert project["asset_count"] == 0, "a cover is not a membership"

        add_members(client, headers, project["id"], [cover["id"]])
        remove_members(client, headers, project["id"], [cover["id"]])

        listed = project_listing(client, headers)[project["id"]]
        assert listed["cover_asset_id"] == cover["id"], "removing the membership leaves the cover alone"
        assert listed["asset_count"] == 0


def test_deleting_the_cover_asset_clears_the_cover_and_the_membership() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        cover = upload(client, headers, "doomed-cover.stl")
        project = create_project(client, headers, cover_asset_id=cover["id"])
        add_members(client, headers, project["id"], [cover["id"]])

        response = client.delete(f"/asset/{cover['id']}", headers=headers)

        assert response.status_code == 200, response.text
        with Session(engine) as session:
            row = session.get(Project, project["id"])
            assert row is not None
            assert row.cover_asset_id is None, "ON DELETE SET NULL reaches the cover"
            assert list(session.exec(select(ProjectAsset).where(ProjectAsset.project_id == project["id"]))) == []
        assert project_listing(client, headers)[project["id"]]["cover_asset_id"] is None


# --- audit rows -------------------------------------------------------------


def test_a_rename_writes_project_rename_with_from_and_to() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers, name="Old Name")
        request_id = f"project-rename-{uuid4().hex}"

        response = client.patch(
            f"/project/{project['id']}",
            json={"name": "New Name"},
            headers={**headers, REQUEST_ID_HEADER: request_id},
        )

        assert response.status_code == 200, response.text
        rows = events_for(request_id)
        assert [row.action for row in rows] == [audit.PROJECT_RENAME]
        assert rows[0].target == project["id"]
        assert json.loads(rows[0].detail_json) == {"from": "Old Name", "to": "New Name"}


def test_a_delete_writes_project_delete_with_the_name() -> None:
    with TestClient(main.app) as client:
        headers = auth_header(client)
        project = create_project(client, headers, name=unique("Doomed"))
        request_id = f"project-delete-{uuid4().hex}"

        response = client.delete(f"/project/{project['id']}", headers={**headers, REQUEST_ID_HEADER: request_id})

        assert response.status_code == 200, response.text
        rows = events_for(request_id)
        assert [row.action for row in rows] == [audit.PROJECT_DELETE]
        assert rows[0].target == project["id"]
        assert json.loads(rows[0].detail_json) == {"name": project["name"]}
