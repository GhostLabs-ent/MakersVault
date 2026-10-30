"""Creator filtering, sorting and faceting for asset listings (Mf-pnc2).

The listing contract stays limit+1 / X-Has-More / X-Next-Offset; these tests pin
the new `creator`, `sort` and `order` parameters, the deterministic tiebreaker
chain that keeps paging honest, and the `GET /creators` facet in folder and
project modes.

Rows are inserted directly because uploads cannot set a creator, and every
listing is scoped by a folder or project so a shared-session fixture cannot leak
rows from another test.
"""

from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import asset_file_service
import asset_service
import db
import library_scan
import settings_service
from db import engine
from main import app
from migrations import run_migrations
from models import Asset, Folder, Project, ProjectAsset

# --- infrastructure ---------------------------------------------------------


def auth_header(client: TestClient) -> dict:
    """Bearer token, or empty when the app is running with auth disabled."""
    health = client.get("/health").json()
    if not health.get("auth_required"):
        return {}
    token = client.post("/login", json={"username": "admin", "password": "super-secret"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def insert_asset(
    name: str,
    folder_id: str,
    *,
    creator: Optional[str] = None,
    created_by: Optional[str] = None,
    filename: Optional[str] = None,
    size: int = 10,
) -> str:
    unique = uuid4().hex
    asset = Asset(
        filename=filename or f"{name}.stl",
        mime="model/stl",
        size=size,
        name=name,
        creator=creator,
        created_by=created_by,
        folder_id=folder_id,
        storage_path=f"Sorts/{unique}/{filename or f'{name}.stl'}",
    )
    with Session(engine) as session:
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset.id


def create_folder(client: TestClient, headers: dict, name: str) -> str:
    response = client.post("/folders", json={"name": name, "tags": [], "parent_id": None}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def create_project(client: TestClient, headers: dict, name: str, asset_ids: list[str]) -> str:
    response = client.post("/projects", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    response = client.post(f"/project/{project_id}/assets", json={"asset_ids": asset_ids}, headers=headers)
    assert response.status_code == 200, response.text
    return project_id


def listed(client: TestClient, headers: dict, **params) -> list[dict]:
    response = client.get("/assets", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def creators(client: TestClient, headers: dict, **params) -> list[str]:
    response = client.get("/creators", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point storage at a temp root, restore settings and undo every row made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    run_migrations(engine)
    template_before = settings_service.get_storage_template()
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        projects_before = {project.id for project in session.exec(select(Project))}
    yield storage
    settings_service.set_storage_template(template_before)
    with Session(engine) as session:
        for membership in list(session.exec(select(ProjectAsset))):
            if membership.project_id not in projects_before:
                session.delete(membership)
        for project in list(session.exec(select(Project))):
            if project.id not in projects_before:
                session.delete(project)
        for asset in list(session.exec(select(Asset))):
            if asset.id not in assets_before:
                session.delete(asset)
        for folder in list(session.exec(select(Folder))):
            if folder.id not in folders_before:
                session.delete(folder)
        session.commit()


# --- creator filter ---------------------------------------------------------


def test_creator_filter_is_exact_and_case_insensitive(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Filter shelf")
        ada = insert_asset("Ada model", folder_id, creator="Ada")
        ada_lower = insert_asset("Ada lower model", folder_id, creator="ada")
        bob = insert_asset("Bob model", folder_id, creator="Bob")
        uncredited = insert_asset("Uncredited model", folder_id, creator=None)

        found = listed(client, headers, folder_id=folder_id, creator="ADA")

        # The filter is exact, not a prefix/substring: only the two Ada spellings.
        assert {asset["id"] for asset in found} == {ada, ada_lower}
        assert bob not in {asset["id"] for asset in found}
        assert uncredited not in {asset["id"] for asset in found}

        # Surrounding whitespace from a chip is trimmed, like the facet's values.
        found = listed(client, headers, folder_id=folder_id, creator="  Ada  ")
        assert {asset["id"] for asset in found} == {ada, ada_lower}


def test_blank_creator_filter_is_ignored(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Blank filter shelf")
        ids = {
            insert_asset("First", folder_id, creator="Ada"),
            insert_asset("Second", folder_id, creator=None),
        }

        found = listed(client, headers, folder_id=folder_id, creator="   ")

        assert {asset["id"] for asset in found} == ids


def test_added_by_filter_is_exact_and_case_insensitive(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Added-by shelf")
        ada = insert_asset("Ada uploaded", folder_id, created_by="Ada")
        ada_lower = insert_asset("Ada lower uploaded", folder_id, created_by="ada")
        bob = insert_asset("Bob uploaded", folder_id, created_by="Bob")
        anonymous = insert_asset("Anonymous uploaded", folder_id, created_by=None)

        found = listed(client, headers, folder_id=folder_id, added_by="ADA")

        # Exact, not a prefix/substring, and case-insensitive like `creator`.
        assert {asset["id"] for asset in found} == {ada, ada_lower}
        assert bob not in {asset["id"] for asset in found}
        # NULL never equals a string: an anonymous row is never matched by a name.
        assert anonymous not in {asset["id"] for asset in found}
        assert all(asset["created_by"] is not None for asset in found)

        # Surrounding whitespace from a chip is trimmed, like the facet's values.
        found = listed(client, headers, folder_id=folder_id, added_by="  Ada  ")
        assert {asset["id"] for asset in found} == {ada, ada_lower}


def test_blank_added_by_filter_is_ignored(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Blank added-by shelf")
        ids = {
            insert_asset("First uploaded", folder_id, created_by="Ada"),
            insert_asset("Second uploaded", folder_id, created_by=None),
        }

        for blank in ("", "   "):
            found = listed(client, headers, folder_id=folder_id, added_by=blank)
            assert {asset["id"] for asset in found} == ids, repr(blank)


# --- sorting ----------------------------------------------------------------


def test_default_order_is_unchanged_when_sort_is_absent(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Default order shelf")
        insert_asset("zeta", folder_id)
        insert_asset("alpha", folder_id)
        insert_asset("middle", folder_id)

        found = listed(client, headers, folder_id=folder_id)

        assert [asset["name"] for asset in found] == ["alpha", "middle", "zeta"]


def test_creator_sort_is_case_insensitive_with_nulls_last_both_ways(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Creator sort shelf")
        insert_asset("Beta model", folder_id, creator="beta")
        insert_asset("No creator", folder_id, creator=None)
        insert_asset("Alpha model", folder_id, creator="Alpha")

        ascending = listed(client, headers, folder_id=folder_id, sort="creator", order="asc")
        assert [asset["creator"] for asset in ascending] == ["Alpha", "beta", None]

        descending = listed(client, headers, folder_id=folder_id, sort="creator", order="desc")
        assert [asset["creator"] for asset in descending] == ["beta", "Alpha", None]


def test_size_sort_pages_without_duplicates_or_skips(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Paging shelf")
        # Same size for every row: without the filename/id tiebreakers SQLite is
        # free to reorder them between two limit/offset queries.
        ids = {
            insert_asset(f"model {index}", folder_id, creator="Same", size=42)
            for index in range(5)
        }

        seen: list[str] = []
        offset = 0
        while True:
            response = client.get(
                "/assets",
                params={"folder_id": folder_id, "sort": "size", "order": "asc", "limit": 2, "offset": offset},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            seen.extend(asset["id"] for asset in response.json())
            if response.headers["X-Has-More"] != "true":
                break
            offset = int(response.headers["X-Next-Offset"])

        assert len(seen) == len(ids)
        assert len(seen) == len(set(seen))
        assert set(seen) == ids


def test_creator_sort_pages_without_duplicates_or_skips(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Creator paging shelf")
        ids = {
            insert_asset(f"tied {index}", folder_id, creator="Ada", filename=f"tied-{index}.stl")
            for index in range(5)
        }

        seen: list[str] = []
        offset = 0
        while True:
            response = client.get(
                "/assets",
                params={"folder_id": folder_id, "sort": "creator", "order": "desc", "limit": 2, "offset": offset},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            seen.extend(asset["id"] for asset in response.json())
            if response.headers["X-Has-More"] != "true":
                break
            offset = int(response.headers["X-Next-Offset"])

        assert len(seen) == len(ids)
        assert len(seen) == len(set(seen))
        assert set(seen) == ids


# --- creator facet ----------------------------------------------------------


def test_creators_facet_dedupes_case_insensitively_and_sorts(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Facet shelf")
        insert_asset("Ada one", folder_id, creator="Ada")
        insert_asset("Ada two", folder_id, creator="ada")
        insert_asset("Bob", folder_id, creator="Bob")
        insert_asset("Nobody", folder_id, creator=None)
        insert_asset("Blank creator", folder_id, creator="   ")

        assert creators(client, headers, folder_id=folder_id) == ["Ada", "Bob"]


def test_creators_facet_scopes_by_folder_and_query(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        first = create_folder(client, headers, "Facet first")
        second = create_folder(client, headers, "Facet second")
        insert_asset("Searchable model", first, creator="Nia")
        insert_asset("Unrelated model", first, creator="Other")
        insert_asset("Elsewhere model", second, creator="Zed")

        assert creators(client, headers, folder_id=first) == ["Nia", "Other"]
        assert creators(client, headers, folder_id=second) == ["Zed"]
        assert creators(client, headers, folder_id=first, q="Searchable") == ["Nia"]


def test_creators_facet_scopes_by_project_and_not_in_project(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Facet project shelf")
        ada = insert_asset("Ada model", folder_id, creator="Ada")
        bob = insert_asset("Bob model", folder_id, creator="Bob")
        uncredited = insert_asset("Uncredited model", folder_id, creator=None)
        project_id = create_project(client, headers, "Facet project", [ada, bob])

        assert creators(client, headers, project_id=project_id) == ["Ada", "Bob"]
        loose = creators(client, headers, folder_id=folder_id, not_in_project=True)
        # Every row is in the project or has no creator, so no loose creator here.
        assert loose == []
        assert uncredited  # the row exists; it simply has no creator value

        response = client.get("/creators", params={"project_id": "no-such-project"}, headers=headers)
        assert response.status_code == 404, response.text


# --- project listing parity -------------------------------------------------


def test_project_listing_supports_creator_filter_and_sort(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Project parity shelf")
        ada = insert_asset("Ada model", folder_id, creator="Ada")
        bob = insert_asset("Bob model", folder_id, creator="Bob")
        uncredited = insert_asset("Uncredited model", folder_id, creator=None)
        project_id = create_project(client, headers, "Parity project", [ada, bob, uncredited])

        filtered = client.get(
            f"/project/{project_id}/assets", params={"creator": "ada"}, headers=headers
        )
        assert filtered.status_code == 200, filtered.text
        assert [asset["id"] for asset in filtered.json()] == [ada]

        descending = client.get(
            f"/project/{project_id}/assets", params={"sort": "creator", "order": "desc"}, headers=headers
        )
        assert descending.status_code == 200, descending.text
        assert [asset["creator"] for asset in descending.json()] == ["Bob", "Ada", None]

        # Blank creator is ignored here too, so the whole membership is listed.
        everything = client.get(
            f"/project/{project_id}/assets", params={"creator": "  "}, headers=headers
        )
        assert everything.status_code == 200, everything.text
        assert {asset["id"] for asset in everything.json()} == {ada, bob, uncredited}


def test_project_listing_default_order_matches_the_library(isolated_storage: Path) -> None:
    with TestClient(app) as client:
        headers = auth_header(client)
        folder_id = create_folder(client, headers, "Project default shelf")
        zeta = insert_asset("zeta", folder_id)
        alpha = insert_asset("alpha", folder_id)
        project_id = create_project(client, headers, "Default project", [zeta, alpha])

        response = client.get(f"/project/{project_id}/assets", headers=headers)

        assert response.status_code == 200, response.text
        assert [asset["id"] for asset in response.json()] == [alpha, zeta]
