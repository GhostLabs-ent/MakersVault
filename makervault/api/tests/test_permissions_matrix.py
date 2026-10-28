"""Per-route permission sweeps driven by `permissions.ROUTE_PERMISSIONS`.

Why this file exists: Mf-2nbc enforces a level with a *per-route dependency*, and
the only thing that keeps 55 hand-written declarations honest is a test that
visits every route at every role. The sweeps below are parametrised from
`permissions.ROUTE_PERMISSIONS`, so that table is both the documentation and the
test plan: add a route without classifying it and
`test_every_api_route_has_a_level` fails; add a mutating route to the matrix
without a call spec and `test_every_guarded_route_has_a_call_spec` fails. No
route list is hand-written here.

`CALLS` is the one place a request body is spelled out: one callable per matrix
key, each building exactly one request. Nothing leaves the process - the import
routes have their outbound fetch stubbed - and every row a request needs comes
from `ids`, which is seeded per test and deleted at teardown, so no sweep depends
on test ordering or on leftovers from another file.

Four routes are pinned at "not 403" instead of a concrete 2xx: the `/import*`
routes. `authorize()` runs before their handlers, so 403 is the only permission
outcome they can have; what happens after the guard depends on an outbound HTTP
fetch, which these tests refuse to perform. Their stubs answer 400, and their
declared level is pinned by `test_every_api_route_has_a_level` and by the editor
sweep below (which asserts 400-with-stub rather than 403 for an editor, i.e. the
guard let an editor through).
"""

from dataclasses import dataclass, replace
from functools import lru_cache
from io import BytesIO
from typing import Callable
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image
from sqlmodel import Session, delete, select

import accounts
import asset_file_service
import asset_service
import auth
import db
import library_scan
import login_throttle as login_throttle_module
import main
import permissions
import settings_service
from config import MOUNT_IMPORT_COPY, MOUNT_IMPORT_ENABLED
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, Folder, Project, ProjectAsset, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
EDITOR_USERNAME = "editor"
EDITOR_PASSWORD = "editor-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}

# Smallest valid STL body: the upload route only stores bytes, it never parses them.
STL_BYTES = b"solid cube\nendsolid cube\n"
# Never fetched: every import route has its outbound layer stubbed below.
IMPORT_URL = "https://example.invalid/cube.stl"

AUTH_NOT_CONFIGURED = "Authentication is not configured on the server"

# The seeds without accounts have no user to name; the sweeps that use them are
# refused (401) or answer 503 before the id is looked up, so a placeholder keeps
# the path well-formed without pretending a row exists.
PLACEHOLDER_USER_ID = "00000000-0000-0000-0000-000000000000"

# The routes that answer 503 while auth is off: the token endpoints plus the two
# endpoints that would otherwise have to invent a principal (`/me`, `/users`).
DISABLED_503_KEYS = {
    ("POST", "/login"),
    ("POST", "/refresh"),
    ("POST", "/logout"),
    ("GET", "/me"),
    ("GET", "/users"),
    ("POST", "/users"),
    ("PATCH", "/users/{user_id}"),
}


@dataclass(frozen=True)
class Ids:
    """Everything a call spec may need to name a real row, seeded per test.

    Optional fields default to empty so a seed can fill only what it has: the
    disabled-auth and no-token sweeps never create accounts, and the routes that
    would use a token are the ones answering 401/503 before touching it.
    """

    admin_token: str = ""
    editor_token: str = ""
    viewer_token: str = ""
    admin_refresh_token: str = ""
    viewer_refresh_token: str = ""
    admin_id: str = ""
    editor_id: str = ""
    viewer_id: str = ""
    folder_id: str = ""
    trash_folder_id: str = ""
    project_id: str = ""
    asset_id: str = ""
    asset_filename: str = ""
    file_id: str = ""
    spare_asset_id: str = ""
    batch_asset_id: str = ""
    storage_template: str = ""
    mount_enabled: bool = False
    mount_copy: bool = False


# --- harness ----------------------------------------------------------------


def truncate_accounts() -> None:
    with Session(engine) as db:
        db.execute(delete(UserSession))
        db.execute(delete(User))
        db.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    """Migrate once, then start and finish every test without accounts."""
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use argon2's floor parameters, in this file only.

    Every sweep seeds three accounts; at the library defaults each hash or verify
    costs ~50 ms, which would make these tests slower than the code they guard.
    Nothing here asserts anything about hashing - strength and rehash-on-login
    are covered by test_auth_users.py - so a cheap hasher only makes the matrix
    sweeps affordable.
    """
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point every storage binding at a temp root and undo the rows a test made.

    `db`, `library_scan`, `asset_service`, `asset_file_service` and `main` all
    bind their paths at import time, so each module global is patched. Rows are
    deleted afterwards because the database is shared for the whole session and
    later files assume an empty library.
    """
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    run_migrations(engine)

    template_before = settings_service.get_storage_template()
    enabled_before = settings_service.get_mount_import_enabled(MOUNT_IMPORT_ENABLED)
    copy_before = settings_service.get_mount_import_copy(MOUNT_IMPORT_COPY)
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        projects_before = {project.id for project in session.exec(select(Project))}

    yield storage

    settings_service.set_storage_template(template_before)
    settings_service.set_mount_import_enabled(enabled_before)
    settings_service.set_mount_import_copy(copy_before)
    with Session(engine) as session:
        # Projects first: the tables are new and the name index is case-
        # insensitive, so a leaked row would 409 the next test's seed.
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


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def create_user(client: TestClient, token: str, username: str, password: str, role: str) -> dict:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def ok(response: Response) -> Response:
    """Seed requests are infrastructure: anything but 200 means the harness broke."""
    assert response.status_code == 200, response.text
    return response


def seed_library(client: TestClient, headers: dict[str, str]) -> Ids:
    """A folder with an asset, supporting and prepared files, plus throwaways."""
    shelf = ok(client.post("/folders", json={"name": "Shelf"}, headers=headers)).json()
    doomed = ok(client.post("/folders", json={"name": "Doomed"}, headers=headers)).json()
    cube = ok(
        client.post(
            "/upload",
            files={"file": ("cube.stl", STL_BYTES, "model/stl")},
            data={"folder_id": shelf["id"]},
            headers=headers,
        )
    ).json()
    spare = ok(client.post("/upload", files={"file": ("spare.stl", STL_BYTES, "model/stl")}, headers=headers)).json()
    batch = ok(client.post("/upload", files={"file": ("batch.stl", STL_BYTES, "model/stl")}, headers=headers)).json()
    ok(
        client.post(
            f"/asset/{cube['id']}/files",
            files={"file": ("notes.txt", b"layer notes\n", "text/plain")},
            headers=headers,
        )
    )
    # A `.gcode` name makes the record the asset's prepared print, so the
    # prepared-print download and delete routes have something real to act on.
    ok(
        client.post(
            f"/asset/{cube['id']}/files",
            files={"file": ("cube.gcode", b"; cube\nG28\n", "text/plain")},
            headers=headers,
        )
    )
    supporting = ok(client.get(f"/asset/{cube['id']}/files", headers=headers)).json()
    ok(
        client.post(
            f"/asset/{cube['id']}/thumbnail-generated",
            files={"file": ("thumb.png", png_bytes(), "image/png")},
            headers=headers,
        )
    )
    project = client.post("/projects", json={"name": "Seed Project"}, headers=headers)
    assert project.status_code == 201, project.text
    ok(
        client.post(
            f"/project/{project.json()['id']}/assets",
            json={"asset_ids": [cube["id"]]},
            headers=headers,
        )
    )
    storage = ok(client.get("/settings/storage", headers=headers)).json()
    mount = ok(client.get("/settings/mount-import", headers=headers)).json()
    return Ids(
        folder_id=shelf["id"],
        trash_folder_id=doomed["id"],
        project_id=project.json()["id"],
        asset_id=cube["id"],
        asset_filename=cube["filename"],
        file_id=supporting[0]["id"],
        spare_asset_id=spare["id"],
        batch_asset_id=batch["id"],
        storage_template=storage["template"],
        mount_enabled=mount["enabled"],
        mount_copy=mount["copy_files"],
    )


@pytest.fixture()
def ids(client: TestClient) -> Ids:
    """An admin, an editor, a viewer and a seeded library, all per test.

    Break-glass creates the first admin; that insert revokes the break-glass
    session in the same transaction, so everything after it signs in as the real
    admin account.
    """
    glass = login(client, **BREAK_GLASS)
    admin = create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, "admin")
    admin_session = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    editor = create_user(client, admin_session["token"], EDITOR_USERNAME, EDITOR_PASSWORD, "editor")
    viewer = create_user(client, admin_session["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    editor_session = login(client, EDITOR_USERNAME, EDITOR_PASSWORD)
    viewer_session = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    return replace(
        seed_library(client, bearer(admin_session["token"])),
        admin_token=admin_session["token"],
        editor_token=editor_session["token"],
        viewer_token=viewer_session["token"],
        admin_refresh_token=admin_session["refresh_token"],
        viewer_refresh_token=viewer_session["refresh_token"],
        admin_id=admin["id"],
        editor_id=editor["id"],
        viewer_id=viewer["id"],
    )


@pytest.fixture()
def guest_ids(client: TestClient) -> Ids:
    """A seeded library and no accounts: for the anonymous sweep.

    Break-glass is enough to seed (it needs no user row) and its refresh token
    doubles as the throwaway the `/logout` and `/refresh` specs rotate.
    """
    glass = login(client, **BREAK_GLASS)
    return replace(
        seed_library(client, bearer(glass["token"])),
        admin_refresh_token=glass["refresh_token"],
        viewer_refresh_token=glass["refresh_token"],
    )


@pytest.fixture()
def disabled_ids(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Ids:
    """A seeded library while auth is off: every request is anonymous anyway."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    return seed_library(client, {})


@pytest.fixture()
def admin_headers(ids: Ids) -> dict[str, str]:
    return bearer(ids.admin_token)


@pytest.fixture()
def editor_headers(ids: Ids) -> dict[str, str]:
    return bearer(ids.editor_token)


@pytest.fixture()
def viewer_headers(ids: Ids) -> dict[str, str]:
    return bearer(ids.viewer_token)


# --- call table -------------------------------------------------------------
# One callable per matrix key. The signature is fixed so a sweep can call any of
# them the same way: (client, headers, ids, monkeypatch) -> Response, and the
# sweep only checks the status. Unused parameters are part of that contract.


CallSpec = Callable[..., Response]


@lru_cache(maxsize=1)
def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (200, 30, 30)).save(buffer, "PNG")
    return buffer.getvalue()


def stub_normalize(raw: str) -> str:
    """Skip URL validation, which resolves DNS - a network call."""
    return raw


def stub_outbound(url: str, *_args, **_kwargs):
    """Stand in for the outbound fetch so an import sweep never opens a socket."""
    raise HTTPException(status_code=400, detail=f"outbound fetch is stubbed in tests ({url})")


def call_health(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/health", headers=headers)


def call_login(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # The real admin account, not break-glass: after the first user exists the env
    # credentials are refused, which is a 401 rather than a permission decision.
    return client.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}, headers=headers)


def call_refresh(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/refresh", json={"refresh_token": ids.admin_refresh_token}, headers=headers)


def call_logout(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/logout", json={"refresh_token": ids.viewer_refresh_token}, headers=headers)


def call_me(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/me", headers=headers)


def call_scan_status(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/library/scan", headers=headers)


def call_file(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/file/{ids.asset_id}/{ids.asset_filename}", headers=headers)


def call_supporting_files(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/asset/{ids.asset_id}/files", headers=headers)


def call_supporting_file(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/asset/{ids.asset_id}/files/{ids.file_id}", headers=headers)


def call_prepared_print(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/asset/{ids.asset_id}/prepared-print", headers=headers)


def call_thumb(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/thumb/{ids.asset_id}.jpg", headers=headers)


def call_assets(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/assets", headers=headers)


def call_tags(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/tags", headers=headers)


def call_download_zip(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/download/zip", json={"asset_ids": [ids.asset_id]}, headers=headers)


def call_folders(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/folders", headers=headers)


def call_folder_delete_preview(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/folder/{ids.folder_id}/delete-preview", headers=headers)


def call_folder_download(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/folder/{ids.folder_id}/download", headers=headers)


def call_trash(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/trash", headers=headers)


def call_upload(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/upload", files={"file": ("probe.stl", STL_BYTES, "model/stl")}, headers=headers)


def call_import(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    monkeypatch.setattr(main, "normalize_import_url", stub_normalize)
    monkeypatch.setattr(main, "import_asset_from_url", stub_outbound)
    return client.post("/import", json={"url": IMPORT_URL}, headers=headers)


def call_import_inspect(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    monkeypatch.setattr(main, "normalize_import_url", stub_normalize)
    monkeypatch.setattr(main, "open_import_response", stub_outbound)
    return client.post("/import/inspect", json={"url": IMPORT_URL}, headers=headers)


def call_import_zip_entries(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    monkeypatch.setattr(main, "normalize_import_url", stub_normalize)
    monkeypatch.setattr(main, "download_import_to_temp", stub_outbound)
    return client.post("/import/zip/entries", json={"url": IMPORT_URL}, headers=headers)


def call_import_zip(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    monkeypatch.setattr(main, "normalize_import_url", stub_normalize)
    monkeypatch.setattr(main, "download_import_to_temp", stub_outbound)
    return client.post("/import/zip", json={"url": IMPORT_URL, "entries": ["cube.stl"]}, headers=headers)


def call_upload_supporting_file(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post(
        f"/asset/{ids.asset_id}/files",
        files={"file": ("probe.txt", b"probe\n", "text/plain")},
        headers=headers,
    )


def call_delete_supporting_file(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.delete(f"/asset/{ids.asset_id}/files/{ids.file_id}", headers=headers)


def call_delete_prepared_print(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.delete(f"/asset/{ids.asset_id}/prepared-print", headers=headers)


def call_thumbnail_generated(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post(
        f"/asset/{ids.asset_id}/thumbnail-generated",
        files={"file": ("thumb.png", png_bytes(), "image/png")},
        headers=headers,
    )


def call_batch_tags(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/assets/batch/tags", json={"asset_ids": [ids.asset_id], "add_tags": ["probe"]}, headers=headers)


def call_batch_folder(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post(
        "/assets/batch/folder",
        json={"asset_ids": [ids.asset_id], "folder_id": ids.folder_id},
        headers=headers,
    )


def call_batch_delete(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/assets/batch/delete", json={"asset_ids": [ids.batch_asset_id]}, headers=headers)


def call_set_tags(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post(f"/asset/{ids.asset_id}/tags", json={"tags": ["probe"]}, headers=headers)


def call_update_meta(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post(f"/asset/{ids.asset_id}/meta", json={"notes": "probe notes"}, headers=headers)


def call_rename_asset(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post(f"/asset/{ids.asset_id}/rename", json={"filename": "renamed.stl"}, headers=headers)


def call_delete_asset(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.delete(f"/asset/{ids.spare_asset_id}", headers=headers)


def call_create_folder(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/folders", json={"name": "Probe"}, headers=headers)


def call_update_folder(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.patch(f"/folder/{ids.folder_id}", json={"name": "Renamed Shelf"}, headers=headers)


def call_delete_folder(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.delete("/folder/" + ids.trash_folder_id, params={"confirm_name": "Doomed"}, headers=headers)


def call_move_asset_to_folder(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post(f"/asset/{ids.asset_id}/folder", json={"folder_id": ids.folder_id}, headers=headers)


def call_get_mount_import(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/settings/mount-import", headers=headers)


def call_update_mount_import(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    body = {"enabled": ids.mount_enabled, "copy_files": ids.mount_copy}
    return client.post("/settings/mount-import", json=body, headers=headers)


def call_get_storage_settings(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/settings/storage", headers=headers)


def call_update_storage_settings(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # Post back the template the deployment already has: a 200 with nothing moved.
    return client.post("/settings/storage", json={"template": ids.storage_template}, headers=headers)


def call_start_scan(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # A real scan would make a later folder delete a 409 while it runs.
    monkeypatch.setattr(main, "start_scan", lambda: True)
    return client.post("/library/scan", headers=headers)


def call_create_user(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/users", json={"username": "probe", "password": VIEWER_PASSWORD}, headers=headers)


def call_list_users(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/users", headers=headers)


def call_list_audit(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/audit", headers=headers)


def call_update_user(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # Disabling a viewer is always allowed: it is not the last enabled admin.
    return client.patch(f"/users/{ids.viewer_id or PLACEHOLDER_USER_ID}", json={"disabled": True}, headers=headers)


def call_purge_trash(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.post("/trash/purge", headers=headers)


def call_list_projects(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get("/projects", headers=headers)


def call_create_project(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # A unique name per call: the name index is case-insensitive and these sweeps
    # run the same spec under several roles.
    return client.post("/projects", json={"name": f"Probe {uuid4().hex}"}, headers=headers)


def call_update_project(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # A real rename every call, never a 409 and never a no-op.
    return client.patch(f"/project/{ids.project_id}", json={"name": f"Renamed {uuid4().hex}"}, headers=headers)


def call_delete_project(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # Its own throwaway project: a shared victim would be a 404 on the next pass.
    # A denied create means the delete is denied too, and the seeded project is
    # then refused by the same guard without being touched.
    created = client.post("/projects", json={"name": f"Doomed {uuid4().hex}"}, headers=headers)
    if created.status_code != 201:
        return client.delete(f"/project/{ids.project_id}", headers=headers)
    return client.delete(f"/project/{created.json()['id']}", headers=headers)


def call_project_assets(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    return client.get(f"/project/{ids.project_id}/assets", headers=headers)


def call_add_project_assets(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # Idempotent either way: the first pass adds, a repeat skips, both are a 200.
    return client.post(
        f"/project/{ids.project_id}/assets",
        json={"asset_ids": [ids.asset_id, ids.spare_asset_id]},
        headers=headers,
    )


def call_remove_project_assets(client: TestClient, headers: dict[str, str], ids: Ids, monkeypatch: pytest.MonkeyPatch) -> Response:
    # A DELETE with a JSON body: send it through request() explicitly.
    return client.request(
        "DELETE",
        f"/project/{ids.project_id}/assets",
        json={"asset_ids": [ids.asset_id, ids.spare_asset_id]},
        headers=headers,
    )


CALLS: dict[tuple[str, str], CallSpec] = {
    ("GET", "/health"): call_health,
    ("POST", "/login"): call_login,
    ("POST", "/refresh"): call_refresh,
    ("POST", "/logout"): call_logout,
    ("GET", "/me"): call_me,
    ("GET", "/library/scan"): call_scan_status,
    ("GET", "/file/{asset_id}/{name}"): call_file,
    ("GET", "/asset/{asset_id}/files"): call_supporting_files,
    ("GET", "/asset/{asset_id}/files/{file_id}"): call_supporting_file,
    ("GET", "/asset/{asset_id}/prepared-print"): call_prepared_print,
    ("GET", "/thumb/{asset_id}.jpg"): call_thumb,
    ("GET", "/assets"): call_assets,
    ("GET", "/tags"): call_tags,
    ("POST", "/download/zip"): call_download_zip,
    ("GET", "/folders"): call_folders,
    ("GET", "/folder/{folder_id}/delete-preview"): call_folder_delete_preview,
    ("GET", "/folder/{folder_id}/download"): call_folder_download,
    ("GET", "/trash"): call_trash,
    ("POST", "/upload"): call_upload,
    ("POST", "/import"): call_import,
    ("POST", "/import/inspect"): call_import_inspect,
    ("POST", "/import/zip/entries"): call_import_zip_entries,
    ("POST", "/import/zip"): call_import_zip,
    ("POST", "/asset/{asset_id}/files"): call_upload_supporting_file,
    ("DELETE", "/asset/{asset_id}/files/{file_id}"): call_delete_supporting_file,
    ("DELETE", "/asset/{asset_id}/prepared-print"): call_delete_prepared_print,
    ("POST", "/asset/{asset_id}/thumbnail-generated"): call_thumbnail_generated,
    ("POST", "/assets/batch/tags"): call_batch_tags,
    ("POST", "/assets/batch/folder"): call_batch_folder,
    ("POST", "/assets/batch/delete"): call_batch_delete,
    ("POST", "/asset/{asset_id}/tags"): call_set_tags,
    ("POST", "/asset/{asset_id}/meta"): call_update_meta,
    ("POST", "/asset/{asset_id}/rename"): call_rename_asset,
    ("DELETE", "/asset/{asset_id}"): call_delete_asset,
    ("POST", "/folders"): call_create_folder,
    ("PATCH", "/folder/{folder_id}"): call_update_folder,
    ("DELETE", "/folder/{folder_id}"): call_delete_folder,
    ("POST", "/asset/{asset_id}/folder"): call_move_asset_to_folder,
    ("GET", "/settings/mount-import"): call_get_mount_import,
    ("POST", "/settings/mount-import"): call_update_mount_import,
    ("GET", "/settings/storage"): call_get_storage_settings,
    ("POST", "/settings/storage"): call_update_storage_settings,
    ("POST", "/library/scan"): call_start_scan,
    ("POST", "/users"): call_create_user,
    ("GET", "/users"): call_list_users,
    ("PATCH", "/users/{user_id}"): call_update_user,
    ("GET", "/audit"): call_list_audit,
    ("POST", "/trash/purge"): call_purge_trash,
    ("GET", "/projects"): call_list_projects,
    ("POST", "/projects"): call_create_project,
    ("PATCH", "/project/{project_id}"): call_update_project,
    ("DELETE", "/project/{project_id}"): call_delete_project,
    ("GET", "/project/{project_id}/assets"): call_project_assets,
    ("POST", "/project/{project_id}/assets"): call_add_project_assets,
    ("DELETE", "/project/{project_id}/assets"): call_remove_project_assets,
}

# What a permitted caller must get back. The four `/import*` routes are absent on
# purpose: their handlers reach the network, which the stubs above refuse, so
# they are pinned at "not 403" instead (see the module docstring).
EXPECTED_STATUS: dict[tuple[str, str], int] = {
    ("GET", "/health"): 200,
    ("POST", "/login"): 200,
    ("POST", "/refresh"): 200,
    ("POST", "/logout"): 204,
    ("GET", "/me"): 200,
    ("GET", "/library/scan"): 200,
    ("GET", "/file/{asset_id}/{name}"): 200,
    ("GET", "/asset/{asset_id}/files"): 200,
    ("GET", "/asset/{asset_id}/files/{file_id}"): 200,
    ("GET", "/asset/{asset_id}/prepared-print"): 200,
    ("GET", "/thumb/{asset_id}.jpg"): 200,
    ("GET", "/assets"): 200,
    ("GET", "/tags"): 200,
    ("POST", "/download/zip"): 200,
    ("GET", "/folders"): 200,
    ("GET", "/folder/{folder_id}/delete-preview"): 200,
    ("GET", "/folder/{folder_id}/download"): 200,
    ("GET", "/trash"): 200,
    ("POST", "/upload"): 200,
    ("POST", "/asset/{asset_id}/files"): 200,
    ("DELETE", "/asset/{asset_id}/files/{file_id}"): 200,
    ("DELETE", "/asset/{asset_id}/prepared-print"): 200,
    ("POST", "/asset/{asset_id}/thumbnail-generated"): 200,
    ("POST", "/assets/batch/tags"): 200,
    ("POST", "/assets/batch/folder"): 200,
    ("POST", "/assets/batch/delete"): 200,
    ("POST", "/asset/{asset_id}/tags"): 200,
    ("POST", "/asset/{asset_id}/meta"): 200,
    ("POST", "/asset/{asset_id}/rename"): 200,
    ("DELETE", "/asset/{asset_id}"): 200,
    ("POST", "/folders"): 200,
    ("PATCH", "/folder/{folder_id}"): 200,
    ("DELETE", "/folder/{folder_id}"): 200,
    ("POST", "/asset/{asset_id}/folder"): 200,
    ("GET", "/settings/mount-import"): 200,
    ("POST", "/settings/mount-import"): 200,
    ("GET", "/settings/storage"): 200,
    ("POST", "/settings/storage"): 200,
    ("POST", "/library/scan"): 202,
    ("POST", "/users"): 201,
    ("GET", "/users"): 200,
    ("PATCH", "/users/{user_id}"): 200,
    ("GET", "/audit"): 200,
    ("POST", "/trash/purge"): 200,
    ("GET", "/projects"): 200,
    ("POST", "/projects"): 201,
    ("PATCH", "/project/{project_id}"): 200,
    ("DELETE", "/project/{project_id}"): 200,
    ("GET", "/project/{project_id}/assets"): 200,
    ("POST", "/project/{project_id}/assets"): 200,
    ("DELETE", "/project/{project_id}/assets"): 200,
}


def keys_at(*levels: str) -> list[tuple[str, str]]:
    """The matrix keys for these levels, sorted so the parametrised ids are stable."""
    return sorted(key for key, level in permissions.ROUTE_PERMISSIONS.items() if level in levels)


def route_id(key: tuple[str, str]) -> str:
    return f"{key[0]} {key[1]}"


NON_PUBLIC_KEYS = keys_at(permissions.READ, permissions.WRITE, permissions.ADMIN)


def call(key: tuple[str, str], client, headers, ids, monkeypatch) -> Response:
    return CALLS[key](client=client, headers=headers, ids=ids, monkeypatch=monkeypatch)


# --- the matrix matches the routes -----------------------------------------


def test_every_api_route_has_a_level() -> None:
    """The three-way rule, asserted twice: through the checker and independently.

    `assert_routes_classified` is the production guard (it also runs at startup),
    so a test that only called it would be testing itself. The walk below states
    the same facts directly off `declared_levels()`, which is what a reviewer
    needs to see.
    """
    matrix = permissions.assert_routes_classified(main.app)
    assert matrix == permissions.ROUTE_PERMISSIONS, "the checker must return the audited matrix"

    api_routes = [route for route in main.app.routes if isinstance(route, APIRoute)]
    seen: set[tuple[str, str]] = set()
    for route in api_routes:
        levels = permissions.declared_levels(route)
        assert len(levels) <= 1, f"{route.path} declares {len(levels)} permission levels ({levels}); declare exactly one"
        for method in route.methods:
            key = (method, route.path)
            if method in {"HEAD", "OPTIONS"} and key not in permissions.ROUTE_PERMISSIONS:
                continue
            seen.add(key)
            assert key in matrix, f"{method} {route.path} is not classified in ROUTE_PERMISSIONS"
            if levels:
                assert levels[0] == matrix[key], f"{method} {route.path} declares {levels[0]!r} but the matrix says {matrix[key]!r}"
            else:
                assert matrix[key] == permissions.PUBLIC, (
                    f"{method} {route.path} declares no level but the matrix says {matrix[key]!r}"
                )

    assert set(matrix) == seen, "every matrix key must be a real route, and every route a matrix key"


def test_the_matrix_is_the_documented_size() -> None:
    """The matrix is pinned at 55 routes; a new route means updating this and docs/PERMISSIONS.md."""
    counts = {level: len(keys_at(level)) for level in (permissions.PUBLIC, permissions.READ, permissions.WRITE, permissions.ADMIN)}
    assert len(permissions.ROUTE_PERMISSIONS) == 55, counts
    assert counts == {permissions.PUBLIC: 4, permissions.READ: 16, permissions.WRITE: 26, permissions.ADMIN: 9}, counts


def test_every_guarded_route_has_a_call_spec() -> None:
    """A new mutating route cannot escape the sweeps.

    The equality is over the WRITE/ADMIN half of the matrix, so adding a guarded
    route without a call spec fails here rather than silently skipping the
    viewer/editor sweeps for it.
    """
    matrix = permissions.ROUTE_PERMISSIONS

    unknown = set(CALLS) - set(matrix)
    assert unknown == set(), f"call specs for routes that are not in the matrix: {sorted(unknown)}"

    guarded_in_matrix = {key for key, level in matrix.items() if level in (permissions.WRITE, permissions.ADMIN)}
    guarded_in_table = {key for key in CALLS if matrix[key] in (permissions.WRITE, permissions.ADMIN)}
    assert guarded_in_table == guarded_in_matrix, (
        "the call table must cover exactly the guarded routes; "
        f"missing {sorted(guarded_in_matrix - guarded_in_table)}, "
        f"extra {sorted(guarded_in_table - guarded_in_matrix)}"
    )
    # Every route (public and read included) has a spec, which is what lets the
    # admin sweep assert "never 403" over the whole matrix.
    assert set(CALLS) == set(matrix)


def test_the_level_dependencies_and_deny_details_agree() -> None:
    """The three factories, the rank ladder and the one-detail-per-level table."""
    for level, dependency in (
        (permissions.READ, permissions.require_read),
        (permissions.WRITE, permissions.require_write),
        (permissions.ADMIN, permissions.require_admin),
    ):
        assert dependency.permission_level == level
        assert level in permissions.DENY_DETAIL

    assert permissions.LEVEL_RANK[permissions.PUBLIC] < permissions.LEVEL_RANK[permissions.READ]
    assert permissions.LEVEL_RANK[permissions.READ] < permissions.LEVEL_RANK[permissions.WRITE]
    assert permissions.LEVEL_RANK[permissions.WRITE] < permissions.LEVEL_RANK[permissions.ADMIN]
    assert permissions.level_for_role("admin") == permissions.ADMIN
    assert permissions.level_for_role("editor") == permissions.WRITE
    assert permissions.level_for_role("viewer") == permissions.READ
    assert permissions.level_for_role("owner") == permissions.PUBLIC
    assert permissions.level_for_role(None) == permissions.PUBLIC


# --- denials ----------------------------------------------------------------


@pytest.mark.parametrize("key", keys_at(permissions.WRITE), ids=route_id)
def test_viewer_is_denied_every_write_route(client, ids, viewer_headers, key, monkeypatch) -> None:
    response = call(key, client, viewer_headers, ids, monkeypatch)

    assert response.status_code == 403, f"{route_id(key)} let a viewer through: {response.status_code} {response.text}"
    assert response.json()["detail"] == permissions.DENY_DETAIL[permissions.WRITE]


@pytest.mark.parametrize("key", keys_at(permissions.ADMIN), ids=route_id)
def test_viewer_is_denied_every_admin_route(client, ids, viewer_headers, key, monkeypatch) -> None:
    response = call(key, client, viewer_headers, ids, monkeypatch)

    assert response.status_code == 403, f"{route_id(key)} let a viewer through: {response.status_code} {response.text}"
    assert response.json()["detail"] == permissions.DENY_DETAIL[permissions.ADMIN]


@pytest.mark.parametrize("key", keys_at(permissions.ADMIN), ids=route_id)
def test_editor_is_denied_every_admin_route(client, ids, editor_headers, key, monkeypatch) -> None:
    response = call(key, client, editor_headers, ids, monkeypatch)

    assert response.status_code == 403, f"{route_id(key)} let an editor through: {response.status_code} {response.text}"
    assert response.json()["detail"] == permissions.DENY_DETAIL[permissions.ADMIN]


@pytest.mark.parametrize("key", NON_PUBLIC_KEYS, ids=route_id)
def test_anonymous_caller_is_refused_every_non_public_route(client, guest_ids, key, monkeypatch) -> None:
    response = call(key, client, {}, guest_ids, monkeypatch)

    assert response.status_code == 401, f"{route_id(key)} answered an anonymous caller with {response.status_code}"


# --- permits ----------------------------------------------------------------


@pytest.mark.parametrize("key", keys_at(permissions.READ), ids=route_id)
def test_viewer_is_allowed_every_read_route(client, ids, viewer_headers, key, monkeypatch) -> None:
    response = call(key, client, viewer_headers, ids, monkeypatch)

    assert response.status_code != 403, f"{route_id(key)} refused a viewer: {response.text}"
    assert response.status_code == EXPECTED_STATUS[key], f"{route_id(key)} answered {response.status_code}: {response.text}"


@pytest.mark.parametrize("key", keys_at(permissions.WRITE), ids=route_id)
def test_editor_is_allowed_every_write_route(client, ids, editor_headers, key, monkeypatch) -> None:
    response = call(key, client, editor_headers, ids, monkeypatch)

    assert response.status_code != 403, f"{route_id(key)} refused an editor: {response.text}"
    expected = EXPECTED_STATUS.get(key)
    if expected is not None:
        assert response.status_code == expected, f"{route_id(key)} answered {response.status_code}: {response.text}"


@pytest.mark.parametrize("key", list(permissions.ROUTE_PERMISSIONS), ids=route_id)
def test_admin_is_never_denied(client, ids, admin_headers, key, monkeypatch) -> None:
    response = call(key, client, admin_headers, ids, monkeypatch)

    assert response.status_code not in (401, 403), f"{route_id(key)} refused an admin: {response.status_code} {response.text}"
    expected = EXPECTED_STATUS.get(key)
    if expected is not None:
        assert response.status_code == expected, f"{route_id(key)} answered {response.status_code}: {response.text}"


def test_starting_a_scan_is_editor_work(client, ids, editor_headers, viewer_headers, monkeypatch) -> None:
    """`POST /library/scan` is write, not admin: the missing-file banner offers it.

    This guards the re-scan affordance: the asset grid's "Re-scan" button calls
    the POST, so classifying it as admin turns an offered action into a 403 for
    every editor. The GET stays read because every client polls the status. The
    audit event on the POST is covered by `test_audit_log.py`.
    """
    key = ("POST", "/library/scan")
    assert permissions.ROUTE_PERMISSIONS[key] == permissions.WRITE
    assert permissions.ROUTE_PERMISSIONS[("GET", "/library/scan")] == permissions.READ

    from_editor = call(key, client, editor_headers, ids, monkeypatch)
    assert from_editor.status_code != 403, f"an editor was refused the scan they are offered: {from_editor.text}"
    assert from_editor.status_code == EXPECTED_STATUS[key], f"{route_id(key)} answered {from_editor.status_code}: {from_editor.text}"

    from_viewer = call(key, client, viewer_headers, ids, monkeypatch)
    assert from_viewer.status_code == 403, f"a viewer started a scan: {from_viewer.status_code} {from_viewer.text}"
    assert from_viewer.json()["detail"] == permissions.DENY_DETAIL[permissions.WRITE]


def test_every_route_has_an_expectation_or_a_documented_reason() -> None:
    """Keeps `EXPECTED_STATUS` honest: only the four import routes may be absent."""
    unpinned = set(CALLS) - set(EXPECTED_STATUS)
    assert unpinned == {
        ("POST", "/import"),
        ("POST", "/import/inspect"),
        ("POST", "/import/zip/entries"),
        ("POST", "/import/zip"),
    }, sorted(unpinned)


# --- auth disabled ----------------------------------------------------------


@pytest.mark.parametrize("key", list(permissions.ROUTE_PERMISSIONS), ids=route_id)
def test_disabled_auth_leaves_every_route_open(client, disabled_ids, key, monkeypatch) -> None:
    response = call(key, client, {}, disabled_ids, monkeypatch)

    assert response.status_code not in (401, 403), (
        f"{route_id(key)} demanded credentials while authentication is disabled: {response.status_code}"
    )


@pytest.mark.parametrize("key", list(permissions.ROUTE_PERMISSIONS), ids=route_id)
def test_disabled_auth_answers_503_only_on_the_auth_endpoints(client, disabled_ids, key, monkeypatch) -> None:
    response = call(key, client, {}, disabled_ids, monkeypatch)

    if key in DISABLED_503_KEYS:
        assert response.status_code == 503, f"{route_id(key)} answered {response.status_code} instead of 503"
        assert response.json()["detail"] == AUTH_NOT_CONFIGURED
    else:
        assert response.status_code != 503, f"{route_id(key)} is not an auth endpoint but answered 503"


def test_the_503_set_is_exactly_the_documented_endpoints() -> None:
    """Two-sided pin: the set above is what the sweeps assert per route."""
    assert DISABLED_503_KEYS == {
        ("POST", "/login"),
        ("POST", "/refresh"),
        ("POST", "/logout"),
        ("GET", "/me"),
        ("GET", "/users"),
        ("POST", "/users"),
        ("PATCH", "/users/{user_id}"),
    }
    assert DISABLED_503_KEYS <= set(permissions.ROUTE_PERMISSIONS)
