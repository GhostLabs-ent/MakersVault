"""The audit log: one row per real action, written in the action's transaction.

Every audited route is swept from `audit.ROUTE_ACTIONS`, so adding an audited
route without an emission fails here as well as at startup. Rows are looked up
by the request id the client sent in `X-Request-ID`, which makes the assertions
independent of the append-only table's shared history: nothing can be deleted to
clean up, by design.

The failure tests are the important half. Fail-closed means an audit insert that
raises must roll the mutation back (the row is still there); fail-loud means the
two filesystem-only actions return 500 and log instead of pretending success.
"""

import json
import logging
import re
from dataclasses import dataclass, replace
from typing import Callable
from uuid import uuid4

import pytest
import snapshot_fakes
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, delete, select

import accounts
import asset_file_service
import asset_service
import audit
import auth
import config
import db
import library_scan
import login_throttle as login_throttle_module
import main
import oidc
import permissions
import sessions
import settings_service
import snapshot_guard
import snapshots
from config import MOUNT_IMPORT_COPY, MOUNT_IMPORT_ENABLED
from db import engine
from migrations import run_migrations
from models import (
    AppConfig,
    Asset,
    AssetFile,
    AuditEvent,
    Folder,
    OidcIdentity,
    Project,
    ProjectAsset,
    User,
    UserSession,
)

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
EDITOR_USERNAME = "editor"
EDITOR_PASSWORD = "editor-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}

STL_BYTES = b"solid cube\nendsolid cube\n"
REQUEST_ID_HEADER = "X-Request-ID"

RETENTION_KEYS = (
    snapshots.RETENTION_KEEP_LAST_N_KEY,
    snapshots.RETENTION_KEEP_DAILY_KEY,
    snapshots.RETENTION_MAX_AGE_DAYS_KEY,
    snapshots.RETENTION_HARD_CAP_KEY,
)


def truncate_accounts() -> None:
    with Session(engine) as db_session:
        # Identities first: they hold a foreign key onto users, and the OIDC
        # exchange sweep provisions one.
        db_session.execute(delete(OidcIdentity))
        db_session.execute(delete(UserSession))
        db_session.execute(delete(User))
        db_session.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2's floor parameters: this file bootstraps accounts in every test."""
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A temp storage root and the settings/rows a test changed restored afterwards.

    Audit rows are deliberately NOT removed: the append-only triggers refuse it,
    and the tests address their own rows by request id instead.
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
    # `POST /snapshots/retention` is one of the audited routes, so the four
    # settings it writes are saved and restored raw like the two above: a
    # configuration with no rows keeps none, which `test_snapshots.py` asserts.
    with Session(engine) as session:
        retention_before = {
            key: (row.value if (row := session.get(AppConfig, key)) is not None else None)
            for key in RETENTION_KEYS
        }
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        projects_before = {project.id for project in session.exec(select(Project))}

    yield storage

    settings_service.set_storage_template(template_before)
    settings_service.set_mount_import_enabled(enabled_before)
    settings_service.set_mount_import_copy(copy_before)
    with Session(engine) as session:
        for key, value in retention_before.items():
            row = session.get(AppConfig, key)
            if value is None:
                if row is not None:
                    session.delete(row)
            elif row is None:
                session.add(AppConfig(key=key, value=value))
            else:
                row.value = value
        session.commit()
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
    # raise_server_exceptions=False: the failure tests assert the 500 itself.
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


@dataclass(frozen=True)
class Ids:
    admin_token: str
    editor_token: str
    viewer_token: str
    admin_refresh_token: str
    admin_id: str
    editor_id: str
    viewer_id: str
    folder_id: str
    other_folder_id: str
    asset_id: str
    spare_asset_id: str
    spare_asset_filename: str
    batch_asset_id: str
    batch_asset_filename: str
    file_id: str
    doomed_folder_id: str
    project_id: str
    storage_template: str
    mount_enabled: bool
    mount_copy: bool


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
    assert response.status_code == 200, response.text
    return response


def upload(client: TestClient, headers: dict[str, str], filename: str, folder_id: str | None = None) -> dict:
    data = {"folder_id": folder_id} if folder_id else {}
    return ok(client.post("/upload", files={"file": (filename, STL_BYTES, "model/stl")}, data=data, headers=headers)).json()


def seed_library(client: TestClient, headers: dict[str, str]) -> Ids:
    shelf = ok(client.post("/folders", json={"name": "Shelf"}, headers=headers)).json()
    other = ok(client.post("/folders", json={"name": "Other"}, headers=headers)).json()
    doomed = ok(client.post("/folders", json={"name": "Doomed"}, headers=headers)).json()
    cube = upload(client, headers, "cube.stl", shelf["id"])
    spare = upload(client, headers, "spare.stl")
    batch = upload(client, headers, "batch.stl")
    ok(client.post(f"/asset/{cube['id']}/files", files={"file": ("notes.txt", b"notes\n", "text/plain")}, headers=headers))
    ok(client.post(f"/asset/{cube['id']}/files", files={"file": ("cube.gcode", b"; cube\n", "text/plain")}, headers=headers))
    supporting = ok(client.get(f"/asset/{cube['id']}/files", headers=headers)).json()
    project = client.post("/projects", json={"name": "Seed Project"}, headers=headers)
    assert project.status_code == 201, project.text
    ok(client.post(f"/project/{project.json()['id']}/assets", json={"asset_ids": [cube["id"]]}, headers=headers))
    storage = ok(client.get("/settings/storage", headers=headers)).json()
    mount = ok(client.get("/settings/mount-import", headers=headers)).json()
    return Ids(
        admin_token="",
        editor_token="",
        viewer_token="",
        admin_refresh_token="",
        admin_id="",
        editor_id="",
        viewer_id="",
        folder_id=shelf["id"],
        other_folder_id=other["id"],
        asset_id=cube["id"],
        spare_asset_id=spare["id"],
        spare_asset_filename=spare["filename"],
        batch_asset_id=batch["id"],
        batch_asset_filename=batch["filename"],
        file_id=supporting[0]["id"],
        doomed_folder_id=doomed["id"],
        project_id=project.json()["id"],
        storage_template=storage["template"],
        mount_enabled=mount["enabled"],
        mount_copy=mount["copy_files"],
    )


@pytest.fixture()
def ids(client: TestClient) -> Ids:
    glass = login(client, **BREAK_GLASS)
    admin = create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, "admin")
    admin_session = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    editor = create_user(client, admin_session["token"], EDITOR_USERNAME, EDITOR_PASSWORD, "editor")
    viewer = create_user(client, admin_session["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    editor_session = login(client, EDITOR_USERNAME, EDITOR_PASSWORD)
    viewer_session = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    seed = seed_library(client, bearer(admin_session["token"]))
    return replace(
        seed,
        admin_token=admin_session["token"],
        editor_token=editor_session["token"],
        viewer_token=viewer_session["token"],
        admin_refresh_token=admin_session["refresh_token"],
        admin_id=admin["id"],
        editor_id=editor["id"],
        viewer_id=viewer["id"],
    )


def request_id_for(test_name: str) -> str:
    """A unique, header-legal id: letters, digits and dashes only."""
    return f"{test_name}-{uuid4().hex}"


def events_for(value: str) -> list[AuditEvent]:
    with Session(engine) as session:
        return list(session.exec(select(AuditEvent).where(AuditEvent.request_id == value)))


def one_event(value: str) -> AuditEvent:
    rows = events_for(value)
    assert len(rows) == 1, [row.action for row in rows]
    return rows[0]


def audit_headers(token: str, value: str) -> dict[str, str]:
    return {**bearer(token), REQUEST_ID_HEADER: value}


# --- every audited route emits -------------------------------------------------


CallSpec = Callable[..., Response]


def call_login(client, headers, ids, monkeypatch) -> Response:
    return client.post("/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}, headers=headers)


def call_oidc_exchange(client, headers, ids, monkeypatch) -> Response:
    """Spend a parked handoff code; the callback is what talks to the provider.

    Parking the code directly exercises exactly this route, so the sweep needs no
    provider mock and opens no socket. `ids` has already seeded an enabled admin,
    which is what the provisioning gate requires.
    """
    monkeypatch.setattr(config, "OIDC_ENABLED", True)
    monkeypatch.setattr(config, "OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("PUBLIC_URL", "https://vault.example.com")
    code = oidc.park_handoff({"sub": "audit-sweep-subject", "preferred_username": "sso-sweep", "groups": []})
    return client.post("/auth/oidc/exchange", json={"code": code}, headers=headers)


def call_refresh(client, headers, ids, monkeypatch) -> Response:
    """Drive the grace path: it is the only refresh path the sweep may see.

    The first presentation rotates silently (a normal refresh writes no row);
    the second presents the same token inside the grace window, which is the
    one refresh outcome worth a row.
    """
    client.post("/refresh", json={"refresh_token": ids.admin_refresh_token})
    return client.post("/refresh", json={"refresh_token": ids.admin_refresh_token}, headers=headers)


def call_delete_own_session(client, headers, ids, monkeypatch) -> Response:
    """Delete one of the admin's *other* sessions, never the sweep's own."""
    login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    listing = ok(client.get("/me/sessions", headers=headers)).json()
    target = next(row for row in listing if not row["current"])
    return client.delete(f"/me/sessions/{target['id']}", headers=headers)


def call_admin_delete_session(client, headers, ids, monkeypatch) -> Response:
    """Revoke a freshly created viewer session, leaving the fixture's alone."""
    viewer_session = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    sid = auth.decode_access_token(viewer_session["token"])["sid"]
    return client.delete(f"/sessions/{sid}", headers=headers)


def call_delete_asset(client, headers, ids, monkeypatch) -> Response:
    return client.delete(
        f"/asset/{ids.spare_asset_id}", params={"confirm_name": ids.spare_asset_filename}, headers=headers
    )


def call_batch_delete(client, headers, ids, monkeypatch) -> Response:
    # The guard's decision must not depend on the host: on a CephFS box a real
    # detection would take a snapshot, and a strict policy could answer 409.
    snapshot_fakes.use_unavailable(monkeypatch)
    return client.post(
        "/assets/batch/delete",
        json={"asset_ids": [ids.spare_asset_id], "confirm_count": 1},
        headers=headers,
    )


def call_rename_asset(client, headers, ids, monkeypatch) -> Response:
    return client.post(f"/asset/{ids.asset_id}/rename", json={"filename": "renamed.stl"}, headers=headers)


def call_meta_rename_asset(client, headers, ids, monkeypatch) -> Response:
    return client.post(f"/asset/{ids.asset_id}/meta", json={"name": "Meta Renamed"}, headers=headers)


def call_move_asset(client, headers, ids, monkeypatch) -> Response:
    return client.post(f"/asset/{ids.spare_asset_id}/folder", json={"folder_id": ids.folder_id}, headers=headers)


def call_batch_move(client, headers, ids, monkeypatch) -> Response:
    return client.post(
        "/assets/batch/folder",
        json={"asset_ids": [ids.spare_asset_id], "folder_id": ids.folder_id},
        headers=headers,
    )


def call_delete_supporting_file(client, headers, ids, monkeypatch) -> Response:
    return client.delete(f"/asset/{ids.asset_id}/files/{ids.file_id}", headers=headers)


def call_rename_supporting_file(client, headers, ids, monkeypatch) -> Response:
    # A real rename every call: an unchanged name writes no audit row.
    return client.patch(
        f"/asset/{ids.asset_id}/files/{ids.file_id}",
        json={"filename": f"renamed-{uuid4().hex}.txt"},
        headers=headers,
    )


def call_reorder_supporting_files(client, headers, ids, monkeypatch) -> Response:
    # A second supporting file, then the reverse of the current order: the
    # seeded asset has one file, and an unchanged order writes no row.
    ok(client.post(
        f"/asset/{ids.asset_id}/files",
        files={"file": ("extra.txt", b"extra\n", "text/plain")},
        headers=headers,
    ))
    current = [row["id"] for row in ok(client.get(f"/asset/{ids.asset_id}/files", headers=headers)).json()]
    return client.put(
        f"/asset/{ids.asset_id}/files/order",
        json={"file_ids": list(reversed(current))},
        headers=headers,
    )


def call_delete_prepared_print(client, headers, ids, monkeypatch) -> Response:
    return client.delete(f"/asset/{ids.asset_id}/prepared-print", headers=headers)


def call_rename_folder(client, headers, ids, monkeypatch) -> Response:
    return client.patch(f"/folder/{ids.folder_id}", json={"name": "Shelf Renamed"}, headers=headers)


def call_delete_folder(client, headers, ids, monkeypatch) -> Response:
    # Same reason as the batch delete: pin the guard's capability answer.
    snapshot_fakes.use_unavailable(monkeypatch)
    return client.delete(f"/folder/{ids.doomed_folder_id}", params={"confirm_name": "Doomed"}, headers=headers)


def call_purge(client, headers, ids, monkeypatch) -> Response:
    # Same reason as the batch delete: pin the guard's capability answer.
    snapshot_fakes.use_unavailable(monkeypatch)
    return client.post("/trash/purge", headers=headers)


def call_storage_settings(client, headers, ids, monkeypatch) -> Response:
    return client.post("/settings/storage", json={"template": ids.storage_template}, headers=headers)


def call_mount_import_settings(client, headers, ids, monkeypatch) -> Response:
    return client.post(
        "/settings/mount-import",
        json={"enabled": ids.mount_enabled, "copy_files": ids.mount_copy},
        headers=headers,
    )


def call_create_user(client, headers, ids, monkeypatch) -> Response:
    return client.post("/users", json={"username": "probe", "password": VIEWER_PASSWORD}, headers=headers)


def call_update_user(client, headers, ids, monkeypatch) -> Response:
    return client.patch(f"/users/{ids.viewer_id}", json={"disabled": True}, headers=headers)


def call_start_scan(client, headers, ids, monkeypatch) -> Response:
    monkeypatch.setattr(main, "start_scan", lambda: True)
    return client.post("/library/scan", headers=headers)


def call_create_snapshot(client, headers, ids, monkeypatch) -> Response:
    # A real provider: this sweep asserts at least one row, and a null provider
    # would answer 409 instead of creating anything. The tree copy writes into
    # the test's temporary storage root, never a real library.
    snapshot_fakes.use_tree_copy(monkeypatch, db.STORAGE)
    return client.post("/snapshots", headers=headers)


def call_delete_snapshot(client, headers, ids, monkeypatch) -> Response:
    provider = snapshot_fakes.use_tree_copy(monkeypatch, db.STORAGE)
    # No context: the fake writes no rows, so the delete route owns the row.
    created = provider.create()
    return client.delete(f"/snapshots/{created.snapshot.name}", headers=headers)


def call_restore_snapshot(client, headers, ids, monkeypatch) -> Response:
    provider = snapshot_fakes.use_tree_copy(monkeypatch, db.STORAGE)
    (db.STORAGE / "cube.stl").write_bytes(STL_BYTES)
    created = provider.create()
    monkeypatch.setattr(main, "start_scan", lambda: True)
    return client.post(
        f"/snapshots/{created.snapshot.name}/restore",
        json={"path": "cube.stl"},
        headers=headers,
    )


def call_update_snapshot_retention(client, headers, ids, monkeypatch) -> Response:
    body = {
        "keep_last_n": snapshots.DEFAULT_KEEP_LAST_N,
        "keep_daily": snapshots.DEFAULT_KEEP_DAILY,
        "max_age_days": snapshots.DEFAULT_MAX_AGE_DAYS,
        "hard_cap": snapshots.DEFAULT_HARD_CAP,
    }
    return client.post("/snapshots/retention", json=body, headers=headers)


def call_rename_project(client, headers, ids, monkeypatch) -> Response:
    # A real rename: project.rename is only written when the name changes.
    return client.patch(f"/project/{ids.project_id}", json={"name": f"Project {uuid4().hex}"}, headers=headers)


def call_delete_project(client, headers, ids, monkeypatch) -> Response:
    # Its own throwaway project, so the sweep never 404s on a second pass.
    created = client.post("/projects", json={"name": f"Doomed {uuid4().hex}"}, headers=headers)
    return client.request("DELETE", f"/project/{created.json()['id']}", headers=headers)


CALLS: dict[tuple[str, str], CallSpec] = {
    ("POST", "/login"): call_login,
    ("POST", "/refresh"): call_refresh,
    ("POST", "/auth/oidc/exchange"): call_oidc_exchange,
    ("DELETE", "/me/sessions/{session_id}"): call_delete_own_session,
    ("DELETE", "/sessions/{session_id}"): call_admin_delete_session,
    ("DELETE", "/asset/{asset_id}"): call_delete_asset,
    ("POST", "/assets/batch/delete"): call_batch_delete,
    ("POST", "/asset/{asset_id}/rename"): call_rename_asset,
    ("POST", "/asset/{asset_id}/meta"): call_meta_rename_asset,
    ("POST", "/asset/{asset_id}/folder"): call_move_asset,
    ("POST", "/assets/batch/folder"): call_batch_move,
    ("DELETE", "/asset/{asset_id}/files/{file_id}"): call_delete_supporting_file,
    ("PATCH", "/asset/{asset_id}/files/{file_id}"): call_rename_supporting_file,
    ("PUT", "/asset/{asset_id}/files/order"): call_reorder_supporting_files,
    ("DELETE", "/asset/{asset_id}/prepared-print"): call_delete_prepared_print,
    ("PATCH", "/folder/{folder_id}"): call_rename_folder,
    ("DELETE", "/folder/{folder_id}"): call_delete_folder,
    ("PATCH", "/project/{project_id}"): call_rename_project,
    ("DELETE", "/project/{project_id}"): call_delete_project,
    ("POST", "/trash/purge"): call_purge,
    ("POST", "/settings/storage"): call_storage_settings,
    ("POST", "/settings/mount-import"): call_mount_import_settings,
    ("POST", "/users"): call_create_user,
    ("PATCH", "/users/{user_id}"): call_update_user,
    ("POST", "/library/scan"): call_start_scan,
    ("POST", "/snapshots"): call_create_snapshot,
    ("DELETE", "/snapshots/{name}"): call_delete_snapshot,
    ("POST", "/snapshots/{name}/restore"): call_restore_snapshot,
    ("POST", "/snapshots/retention"): call_update_snapshot_retention,
}


def route_id(key: tuple[str, str]) -> str:
    return f"{key[0]} {key[1]}"


# `POST /auth/oidc/exchange` is a login, not an action taken *by* the caller: the
# audited actor is the account the identity provider just authenticated, so the
# sweep's shared "the admin did it" assertions describe a caller who already has a
# session and do not apply. It is named here and asserted in its own test below.
ACTOR_SELF_ROUTES = {("POST", "/auth/oidc/exchange")}


def test_the_call_table_covers_every_audited_route() -> None:
    assert set(CALLS) == set(audit.ROUTE_ACTIONS)


@pytest.mark.parametrize("key", sorted(audit.ROUTE_ACTIONS), ids=route_id)
def test_every_audited_route_emits_one_of_its_actions(client, ids, key, monkeypatch) -> None:
    value = request_id_for("sweep")
    response = CALLS[key](client, audit_headers(ids.admin_token, value), ids, monkeypatch)

    assert response.status_code < 400, f"{route_id(key)} answered {response.status_code}: {response.text}"
    assert response.headers[REQUEST_ID_HEADER] == value
    rows = events_for(value)
    assert rows, f"{route_id(key)} wrote no audit row"
    actions = {row.action for row in rows}
    assert actions & set(audit.ROUTE_ACTIONS[key]), sorted(actions)
    assert actions <= audit.ACTIONS, sorted(actions)
    row = rows[0]
    assert row.method == key[0]
    assert row.target
    if key in ACTOR_SELF_ROUTES:
        assert row.actor_kind == sessions.OIDC_KIND
        return
    assert row.actor == ADMIN_USERNAME
    assert row.actor_user_id == ids.admin_id
    assert row.actor_role == "admin"
    assert row.actor_kind == "password"


def test_a_replayed_refresh_token_revokes_the_session_and_writes_its_own_row(
    client: TestClient, ids: Ids
) -> None:
    """The replay 401 path is deliberately outside the sweep.

    The sweep asserts every audited route answers `< 400`; this route's audited
    outcome *is* the 401, so it needs its own test. The revoke and the row must
    both be committed before the exception unwinds the handler's transaction.
    """
    value = request_id_for("replay")
    sid = auth.decode_access_token(ids.admin_token)["sid"]
    first = client.post("/refresh", json={"refresh_token": ids.admin_refresh_token})
    assert first.status_code == 200, first.text
    with Session(engine) as db_session:
        row = db_session.get(UserSession, sid)
        assert row is not None
        row.rotated_at = sessions._now() - sessions.REFRESH_GRACE_SECONDS - 1
        db_session.commit()

    replayed = client.post(
        "/refresh",
        json={"refresh_token": ids.admin_refresh_token},
        headers={REQUEST_ID_HEADER: value},
    )

    assert replayed.status_code == 401
    rows = events_for(value)
    assert [row.action for row in rows] == [audit.SESSION_REFRESH_REPLAYED]
    row = rows[0]
    assert row.actor == ADMIN_USERNAME
    assert row.actor_user_id == ids.admin_id
    assert row.target == sid
    assert "client_ip" in json.loads(row.detail_json or "{}")
    with Session(engine) as db_session:
        stored = db_session.get(UserSession, sid)
        assert stored is not None and stored.revoked_at is not None
    assert client.get("/assets", headers=bearer(ids.admin_token)).status_code == 401


# --- what the row says ---------------------------------------------------------


def test_asset_delete_row_names_the_asset_and_file(client: TestClient, ids: Ids) -> None:
    value = request_id_for("asset-delete")
    response = client.delete(
        f"/asset/{ids.spare_asset_id}",
        params={"confirm_name": ids.spare_asset_filename},
        headers=audit_headers(ids.admin_token, value),
    )
    assert response.status_code == 200, response.text

    row = one_event(value)
    assert row.action == audit.ASSET_DELETE
    assert row.target == ids.spare_asset_id
    assert row.detail_json == '{"filename": "spare.stl"}'


def test_asset_move_row_names_the_new_folder(client: TestClient, ids: Ids) -> None:
    value = request_id_for("asset-move")
    response = client.post(
        f"/asset/{ids.spare_asset_id}/folder",
        json={"folder_id": ids.folder_id},
        headers=audit_headers(ids.admin_token, value),
    )
    assert response.status_code == 200, response.text

    row = one_event(value)
    assert row.action == audit.ASSET_MOVE
    assert row.target == ids.spare_asset_id
    assert row.detail_json == f'{{"folder_id": "{ids.folder_id}"}}'


def test_supporting_file_rename_row_names_the_old_and_the_new_name(client: TestClient, ids: Ids) -> None:
    value = request_id_for("file-rename")
    response = client.patch(
        f"/asset/{ids.asset_id}/files/{ids.file_id}",
        json={"filename": "Renamed notes.txt"},
        headers=audit_headers(ids.admin_token, value),
    )
    assert response.status_code == 200, response.text

    row = one_event(value)
    assert row.action == audit.ASSET_FILE_RENAME
    assert row.target == ids.asset_id
    assert row.detail_json == json.dumps(
        {"file_id": ids.file_id, "from": "notes.txt", "to": "Renamed notes.txt"}, sort_keys=True
    )


def test_supporting_file_reorder_row_records_the_new_order(client: TestClient, ids: Ids) -> None:
    value = request_id_for("file-reorder")
    ok(client.post(
        f"/asset/{ids.asset_id}/files",
        files={"file": ("second.txt", b"second\n", "text/plain")},
        headers=audit_headers(ids.admin_token, value),
    ))
    current = [row["id"] for row in ok(client.get(f"/asset/{ids.asset_id}/files", headers=bearer(ids.admin_token))).json()]
    reversed_ids = list(reversed(current))
    response = client.put(
        f"/asset/{ids.asset_id}/files/order",
        json={"file_ids": reversed_ids},
        headers=audit_headers(ids.admin_token, value),
    )
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == reversed_ids

    row = one_event(value)
    assert row.action == audit.ASSET_FILE_REORDER
    assert row.target == ids.asset_id
    assert row.detail_json == json.dumps({"order": reversed_ids})


def test_folder_patch_records_rename_and_move_as_two_facts(client: TestClient, ids: Ids) -> None:
    value = request_id_for("folder-both")
    response = client.patch(
        f"/folder/{ids.folder_id}",
        json={"name": "Renamed", "parent_id": ids.other_folder_id},
        headers=audit_headers(ids.admin_token, value),
    )
    assert response.status_code == 200, response.text

    actions = sorted(row.action for row in events_for(value))
    assert actions == [audit.FOLDER_MOVE, audit.FOLDER_RENAME]


def test_role_change_and_disable_write_one_row_per_changed_field(client: TestClient, ids: Ids) -> None:
    value = request_id_for("role-and-disable")
    response = client.patch(
        f"/users/{ids.viewer_id}",
        json={"role": "editor", "disabled": True},
        headers=audit_headers(ids.admin_token, value),
    )
    assert response.status_code == 200, response.text

    rows = {row.action: row for row in events_for(value)}
    assert set(rows) == {audit.USER_ROLE_CHANGE, audit.USER_DISABLE}
    assert rows[audit.USER_ROLE_CHANGE].target == VIEWER_USERNAME
    assert rows[audit.USER_ROLE_CHANGE].detail_json == '{"from": "viewer", "to": "editor"}'
    assert rows[audit.USER_DISABLE].detail_json == '{"from": false, "to": true}'


def test_re_enabling_a_user_writes_user_enable(client: TestClient, ids: Ids) -> None:
    disable = request_id_for("disable")
    response = client.patch(
        f"/users/{ids.viewer_id}",
        json={"disabled": True},
        headers=audit_headers(ids.admin_token, disable),
    )
    assert response.status_code == 200, response.text
    assert one_event(disable).action == audit.USER_DISABLE

    enable = request_id_for("enable")
    response = client.patch(
        f"/users/{ids.viewer_id}",
        json={"disabled": False},
        headers=audit_headers(ids.admin_token, enable),
    )
    assert response.status_code == 200, response.text

    row = one_event(enable)
    assert row.action == audit.USER_ENABLE
    assert row.target == VIEWER_USERNAME
    assert row.detail_json == '{"from": true, "to": false}'


def test_login_row_names_the_real_user_and_never_the_secret(client: TestClient, ids: Ids) -> None:
    value = request_id_for("login")
    response = client.post(
        "/login",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        headers={REQUEST_ID_HEADER: value},
    )
    assert response.status_code == 200, response.text

    row = one_event(value)
    assert row.action == audit.LOGIN_SUCCEEDED
    assert row.target == ADMIN_USERNAME
    assert row.actor == ADMIN_USERNAME
    assert row.actor_kind == "password"
    assert row.actor_role == "admin"
    assert ADMIN_PASSWORD not in (row.detail_json or "")
    assert "refresh" not in (row.detail_json or "").lower()


def test_oidc_exchange_row_names_the_sso_principal_and_no_secret(
    client: TestClient, ids: Ids, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one mutating OIDC route names the account the provider authenticated.

    The actor is the SSO account, not the caller of the request (there is no
    caller: the route runs before a session exists). The detail carries only the
    three documented keys - a client secret, a handoff code or a token must never
    reach the row.
    """
    value = request_id_for("oidc-exchange")
    monkeypatch.setattr(config, "OIDC_ENABLED", True)
    monkeypatch.setattr(config, "OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setattr(config, "OIDC_CLIENT_SECRET", "super-secret-client-value")
    monkeypatch.setenv("PUBLIC_URL", "https://vault.example.com")
    code = oidc.park_handoff({"sub": "row-subject", "preferred_username": "sso-row", "groups": []})

    response = client.post(
        "/auth/oidc/exchange",
        json={"code": code},
        headers={REQUEST_ID_HEADER: value, "Authorization": f"Bearer {ids.admin_token}"},
    )
    assert response.status_code == 200, response.text

    row = one_event(value)
    assert row.action == audit.LOGIN_OIDC_SUCCEEDED
    assert row.target == "sso-row"
    assert row.actor == "sso-row"
    assert row.actor_kind == sessions.OIDC_KIND
    assert row.actor_role == "viewer"
    detail = json.loads(row.detail_json or "{}")
    assert set(detail) == {"kind", "client_ip", "issuer"}
    assert detail["issuer"] == "https://idp.example.com"
    assert "super-secret-client-value" not in (row.detail_json or "")
    assert code not in (row.detail_json or "")


def test_break_glass_login_row_is_the_env_admin(client: TestClient) -> None:
    truncate_accounts()
    value = request_id_for("break-glass")
    response = client.post("/login", json=BREAK_GLASS, headers={REQUEST_ID_HEADER: value})
    assert response.status_code == 200, response.text

    row = one_event(value)
    assert row.action == audit.LOGIN_SUCCEEDED
    assert row.actor == BREAK_GLASS["username"]
    assert row.actor_kind == "break-glass"
    assert row.actor_role == "admin"
    assert row.actor_user_id is None


def test_auth_disabled_records_local_and_never_500s(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    value = request_id_for("disabled")
    response = client.post(
        "/settings/mount-import",
        json={"enabled": False, "copy_files": False},
        headers={REQUEST_ID_HEADER: value},
    )

    assert response.status_code == 200, response.text
    row = one_event(value)
    assert row.actor == audit.ACTOR_DISABLED_USERNAME
    assert row.actor_role == audit.ACTOR_DISABLED_ROLE
    assert row.actor_kind == audit.ACTOR_DISABLED_ROLE
    assert row.actor_user_id is None
    assert client.get("/audit").status_code == 200


# --- nothing changed, nothing written ------------------------------------------


def test_no_op_requests_write_nothing(client: TestClient, ids: Ids) -> None:
    requests = [
        (
            "post",
            f"/asset/{ids.asset_id}/rename",
            {"filename": "cube.stl"},
            request_id_for("noop-rename"),
        ),
        (
            "post",
            f"/asset/{ids.asset_id}/folder",
            {"folder_id": ids.folder_id},
            request_id_for("noop-move"),
        ),
        (
            "patch",
            f"/users/{ids.viewer_id}",
            {"role": "viewer"},
            request_id_for("noop-role"),
        ),
        (
            "patch",
            f"/folder/{ids.folder_id}",
            {"name": "Shelf", "tags": ["changed"]},
            request_id_for("noop-tags"),
        ),
    ]
    for method, path, body, value in requests:
        response = getattr(client, method)(path, json=body, headers=audit_headers(ids.admin_token, value))
        assert response.status_code == 200, f"{method} {path}: {response.text}"
        assert events_for(value) == [], f"{method} {path} wrote a row for a no-op"


def test_a_denied_write_writes_no_row(client: TestClient, ids: Ids) -> None:
    value = request_id_for("denied")
    response = client.delete(
        f"/asset/{ids.spare_asset_id}",
        params={"confirm_name": ids.spare_asset_filename},
        headers=audit_headers(ids.viewer_token, value),
    )

    assert response.status_code == 403
    assert events_for(value) == []


# --- the admin view ------------------------------------------------------------


def test_admin_view_filters_page_and_sorts_newest_first(client: TestClient, ids: Ids) -> None:
    first = request_id_for("view-a")
    second = request_id_for("view-b")
    assert client.delete(
        f"/asset/{ids.spare_asset_id}",
        params={"confirm_name": ids.spare_asset_filename},
        headers=audit_headers(ids.admin_token, first),
    ).status_code == 200
    assert client.delete(
        f"/asset/{ids.batch_asset_id}",
        params={"confirm_name": ids.batch_asset_filename},
        headers=audit_headers(ids.admin_token, second),
    ).status_code == 200

    response = client.get(
        "/audit",
        params={"actor": "ROOT", "action": audit.ASSET_DELETE, "limit": 50, "offset": 0},
        headers=bearer(ids.admin_token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] >= 2
    assert {event["request_id"] for event in body["events"]} >= {first, second}
    assert body["events"][0]["request_id"] == second, "newest first"
    event = next(item for item in body["events"] if item["request_id"] == first)
    assert event["actor"] == ADMIN_USERNAME
    assert event["actor_kind"] == "password"
    assert event["path"] == f"/asset/{ids.spare_asset_id}"
    assert isinstance(event["detail"], dict)

    target = client.get(
        "/audit",
        params={"target": ids.spare_asset_id, "action": audit.ASSET_DELETE},
        headers=bearer(ids.admin_token),
    )
    assert target.status_code == 200
    assert all(item["target"] == ids.spare_asset_id for item in target.json()["events"])

    paged = client.get(
        "/audit",
        params={"action": audit.ASSET_DELETE, "limit": 1, "offset": 1},
        headers=bearer(ids.admin_token),
    )
    assert paged.status_code == 200
    assert paged.json()["limit"] == 1
    assert paged.json()["offset"] == 1
    assert len(paged.json()["events"]) == 1
    assert paged.json()["total"] >= 2

    today = one_event(first).created_at[:10]
    windowed = client.get(
        "/audit",
        params={"target": ids.spare_asset_id, "since": today, "until": today},
        headers=bearer(ids.admin_token),
    )
    assert windowed.status_code == 200
    assert [item["request_id"] for item in windowed.json()["events"]] == [first]


def test_a_target_filter_treats_like_metacharacters_as_literal(client: TestClient, ids: Ids) -> None:
    """`%` in a target filter must be escaped, not read as a wildcard.

    The two usernames differ only where a `%` wildcard would have matched, so a
    missing `_escape_like` returns the near miss too.
    """
    marker = uuid4().hex[:8]
    literal = f"wild{marker}%card"
    near_miss = f"wild{marker}Xcard"
    for username in (literal, near_miss):
        response = client.post(
            "/users",
            json={"username": username, "password": VIEWER_PASSWORD},
            headers=bearer(ids.admin_token),
        )
        assert response.status_code == 201, response.text

    response = client.get(
        "/audit",
        params={"target": literal, "action": audit.USER_CREATE},
        headers=bearer(ids.admin_token),
    )

    assert response.status_code == 200, response.text
    targets = {item["target"] for item in response.json()["events"]}
    assert targets == {literal}, "a % in the target filter must not match as a wildcard"


def test_the_view_rejects_editor_viewer_and_anonymous(client: TestClient, ids: Ids) -> None:
    assert client.get("/audit", headers=bearer(ids.editor_token)).status_code == 403
    assert client.get("/audit", headers=bearer(ids.viewer_token)).status_code == 403
    assert client.get("/audit").status_code == 401


# --- failure semantics ---------------------------------------------------------


def explode(_session, _row) -> None:
    raise RuntimeError("audit insert failed")


def stub_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take the snapshot guard out of the way, without changing what a test asserts.

    The guard writes its own fail-loud row before the route's mutation, so with
    `audit._add` exploding the failure would surface there first and never reach
    the surface these tests pin (the rollback, the per-asset report, the logged
    `trash.purge`). Stubbing it keeps each failure surface exactly as it was; the
    guard's own ordering has its own test below.
    """
    monkeypatch.setattr(snapshot_guard, "guard", lambda *args, **kwargs: None)


def test_audit_failure_rolls_back_the_asset_delete(client: TestClient, ids: Ids, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_guard(monkeypatch)
    monkeypatch.setattr(audit, "_add", explode)

    response = client.delete(
        f"/asset/{ids.spare_asset_id}",
        params={"confirm_name": ids.spare_asset_filename},
        headers=bearer(ids.admin_token),
    )

    assert response.status_code == 500
    with Session(engine) as session:
        assert session.get(Asset, ids.spare_asset_id) is not None, "the delete must have rolled back"


def test_audit_failure_is_reported_per_asset_in_a_batch_delete(
    client: TestClient, ids: Ids, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_guard(monkeypatch)
    monkeypatch.setattr(audit, "_add", explode)

    response = client.post(
        "/assets/batch/delete",
        json={"asset_ids": [ids.batch_asset_id], "confirm_count": 1},
        headers=bearer(ids.admin_token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] == []
    assert [failure["id"] for failure in body["failed"]] == [ids.batch_asset_id]
    with Session(engine) as session:
        assert session.get(Asset, ids.batch_asset_id) is not None


def test_audit_failure_on_purge_is_loud(client: TestClient, ids: Ids, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    stub_guard(monkeypatch)
    monkeypatch.setattr(audit, "_add", explode)

    with caplog.at_level(logging.ERROR):
        response = client.post("/trash/purge", headers=bearer(ids.admin_token))

    assert response.status_code == 500
    assert "Audit write failed for trash.purge" in caplog.text


def test_the_guards_own_row_fails_loud_before_the_purge_touches_anything(
    client: TestClient, ids: Ids, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A failure in the guard's row is the first thing to break, not `trash.purge`.

    The guard writes `destructive.snapshot_missed` before the mutation, so an
    audit failure surfaces there and the trash entries are still on disk. That
    ordering is the point: a destructive route cannot destroy what it could not
    audit. `snapshot_guard.guard` is deliberately NOT stubbed here.
    """
    snapshot_fakes.use_unavailable(monkeypatch)
    entry = db.STORAGE / ".trash" / "20250101T000000Z-Old"
    entry.mkdir(parents=True)
    (entry / "a.stl").write_bytes(b"aaaa")
    monkeypatch.setattr(audit, "_add", explode)

    with caplog.at_level(logging.ERROR):
        response = client.post("/trash/purge", headers=bearer(ids.admin_token))

    assert response.status_code == 500
    assert "Audit write failed for destructive.snapshot_missed" in caplog.text
    assert "Audit write failed for trash.purge" not in caplog.text
    assert (entry / "a.stl").read_bytes() == b"aaaa"
    listing = client.get("/trash", headers=bearer(ids.admin_token))
    assert listing.status_code == 200, listing.text
    assert [item["name"] for item in listing.json()["entries"]] == ["20250101T000000Z-Old"]


def test_audit_failure_on_login_leaves_no_session(
    client: TestClient, ids: Ids, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        before = len(list(session.exec(select(UserSession).where(UserSession.username == VIEWER_USERNAME))))
    monkeypatch.setattr(audit, "_add", explode)

    response = client.post("/login", json={"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD})

    assert response.status_code == 500
    with Session(engine) as session:
        after = len(list(session.exec(select(UserSession).where(UserSession.username == VIEWER_USERNAME))))
    assert after == before, "the login session row must have rolled back with its audit row"


def test_audit_failure_on_a_move_leaves_the_bytes_where_the_row_says(
    client: TestClient, ids: Ids, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row is staged before the bytes move, so a failed insert moves nothing.

    Staging after the move would return 500 with the file already relocated and
    the row still naming the old folder.
    """
    monkeypatch.setattr(audit, "_add", explode)

    response = client.post(
        f"/asset/{ids.spare_asset_id}/folder",
        json={"folder_id": ids.folder_id},
        headers=bearer(ids.admin_token),
    )

    assert response.status_code == 500
    with Session(engine) as session:
        asset = session.get(Asset, ids.spare_asset_id)
        assert asset is not None, "the move must have rolled back"
        assert asset.folder_id is None, "the move must have rolled back"
        path = asset_service.managed_asset_path(asset)
    assert path.exists(), "the audit row must be staged before the bytes move"


def test_audit_module_has_no_mutating_helper() -> None:
    names = {name for name in vars(audit) if not name.startswith("_")}
    assert not {name for name in names if name.startswith("update") or name.startswith("delete")}


# --- the drift guard -----------------------------------------------------------


def test_the_real_app_covers_every_mutating_route() -> None:
    assert audit.assert_audit_coverage() is audit.ROUTE_ACTIONS
    for method, path in permissions.ROUTE_PERMISSIONS:
        if method == "GET":
            continue
        assert (method, path) in audit.ROUTE_ACTIONS or (method, path) in audit.EXEMPT_ROUTES


def test_a_new_mutating_route_without_an_action_fails_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = dict(permissions.ROUTE_PERMISSIONS)
    matrix[("POST", "/new-mutating-route")] = permissions.WRITE
    monkeypatch.setattr(permissions, "ROUTE_PERMISSIONS", matrix)

    with pytest.raises(RuntimeError) as excinfo:
        audit.assert_audit_coverage()

    assert "POST /new-mutating-route mutates but is neither" in str(excinfo.value)


def test_a_typo_action_fails_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    drifted = dict(audit.ROUTE_ACTIONS)
    drifted[("DELETE", "/asset/{asset_id}")] = ("asset.delet",)
    monkeypatch.setattr(audit, "ROUTE_ACTIONS", drifted)

    with pytest.raises(RuntimeError) as excinfo:
        audit.assert_audit_coverage()

    assert "declares unknown action 'asset.delet'" in str(excinfo.value)


def test_an_exempt_route_needs_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    drifted = dict(audit.EXEMPT_ROUTES)
    drifted[("POST", "/upload")] = ""
    monkeypatch.setattr(audit, "EXEMPT_ROUTES", drifted)

    with pytest.raises(RuntimeError) as excinfo:
        audit.assert_audit_coverage()

    assert "POST /upload is exempt without a reason" in str(excinfo.value)


def test_a_stale_action_key_fails_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    drifted = dict(audit.ROUTE_ACTIONS)
    drifted[("POST", "/gone")] = (audit.ASSET_DELETE,)
    monkeypatch.setattr(audit, "ROUTE_ACTIONS", drifted)

    with pytest.raises(RuntimeError) as excinfo:
        audit.assert_audit_coverage()

    assert "POST /gone is in ROUTE_ACTIONS but no such route exists" in str(excinfo.value)


def test_a_route_cannot_be_audited_and_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(audit.EXEMPT_ROUTES, ("DELETE", "/asset/{asset_id}"), "double booked")

    with pytest.raises(RuntimeError) as excinfo:
        audit.assert_audit_coverage()

    assert "DELETE /asset/{asset_id} is in both ROUTE_ACTIONS and EXEMPT_ROUTES" in str(excinfo.value)


# --- request ids ---------------------------------------------------------------


def test_a_sane_request_id_is_used_and_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: "client-id_1.2:3"})

    assert response.headers[REQUEST_ID_HEADER] == "client-id_1.2:3"


@pytest.mark.parametrize("hostile", ["bad id with spaces", "x" * 500, "", "id\nwith-newline", b"caf\xe9"])
def test_a_hostile_request_id_is_replaced(client: TestClient, hostile) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: hostile})

    echoed = response.headers[REQUEST_ID_HEADER]
    assert echoed != hostile
    assert re.fullmatch(r"[0-9a-f]{32}", echoed)


def test_an_absent_request_id_is_generated(client: TestClient) -> None:
    response = client.get("/health")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])


def test_the_audit_row_carries_the_echoed_request_id(client: TestClient, ids: Ids) -> None:
    value = request_id_for("echo")
    response = client.delete(
        f"/asset/{ids.spare_asset_id}",
        params={"confirm_name": ids.spare_asset_filename},
        headers=audit_headers(ids.admin_token, value),
    )

    assert response.headers[REQUEST_ID_HEADER] == value
    assert one_event(value).request_id == value
