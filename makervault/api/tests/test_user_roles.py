"""Role changes, the last-admin guard, and how a role reaches a live session.

Why this file exists: Mf-2nbc made `users.role` mutable through
`PATCH /users/{user_id}`, and the rules that are easy to break later are not
"does the 403 fire" - `tests/test_permissions_matrix.py` sweeps every route for
that - but the invariants around *changing* a role:

* a change takes effect on the target's next request, on the session it already
  holds: `require_auth` re-reads `users.role` per request, so a demotion bites
  immediately and sessions are not revoked;
* an administrator cannot demote or disable the last enabled administrator,
  because once the users table is non-empty the env break-glass admin no longer
  authenticates and there is no way back through the API;
* anything that is not a real change is rejected rather than silently accepted
  (empty patch, unknown role, unknown field, unknown user);
* a role string nobody knows ranks as public, so a hand-edited row fails closed.

The last section guards the guard: `permissions.assert_routes_classified` runs in
`main.lifespan`, and a test that only ever calls it on the real app cannot show
that it *would* refuse a bad route. Tiny throwaway apps with local matrices pin
each failure mode, and the real matrix is never mutated without monkeypatch
restoring it.
"""

import pytest
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import accounts
import asset_file_service
import asset_service
import db
import library_scan
import login_throttle as login_throttle_module
import main
import permissions
import settings_service
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, Folder, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
EDITOR_USERNAME = "editor"
EDITOR_PASSWORD = "editor-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}

LAST_ADMIN_DETAIL = "at least one enabled administrator is required"


def truncate_accounts() -> None:
    with Session(engine) as db:
        db.execute(delete(UserSession))
        db.execute(delete(User))
        db.commit()


@pytest.fixture(autouse=True)
def clean_accounts():
    """Migrate once, then start and finish every test without accounts.

    An empty users table is also what makes break-glass login possible, so the
    break-glass tests do not have to invent a reset of their own.
    """
    run_migrations(engine)
    truncate_accounts()
    login_throttle_module.limiter.reset()
    yield
    truncate_accounts()
    login_throttle_module.limiter.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use argon2's floor parameters, in this file only.

    Every test here bootstraps two or three accounts; at the library defaults a
    hash costs ~50 ms. Nothing in this file asserts anything about hashing
    (test_auth_users.py owns that), so the cheap hasher only keeps the role
    matrix affordable.
    """
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Keep folder directories in a temp root and undo the rows a test created.

    `POST /folders` materialises a directory before it inserts its row, and the
    database is shared for the whole session, so both sides are isolated here.
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
    with Session(engine) as session:
        folders_before = {folder.id for folder in session.exec(select(Folder))}
        assets_before = {asset.id for asset in session.exec(select(Asset))}

    yield storage

    settings_service.set_storage_template(template_before)
    with Session(engine) as session:
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


def create_user(client: TestClient, admin_token: str, username: str, password: str, role: str) -> dict:
    response = client.post(
        "/users",
        json={"username": username, "password": password, "role": role},
        headers=bearer(admin_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def bootstrap_admin(client: TestClient) -> tuple[dict, dict]:
    """Promote break-glass to a real admin account and sign in as it.

    The insert of the first user revokes the break-glass sessions in the same
    transaction, so every later request has to use this session (that is also the
    reason the last-admin guard matters at all).
    """
    glass = login(client, **BREAK_GLASS)
    user = create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, "admin")
    return login(client, ADMIN_USERNAME, ADMIN_PASSWORD), user


def create_folder(client: TestClient, token: str, name: str):
    return client.post("/folders", json={"name": name}, headers=bearer(token))


def patch_user(client: TestClient, admin_token: str, user_id: str, body: dict):
    return client.patch(f"/users/{user_id}", json=body, headers=bearer(admin_token))


# --- promotion and demotion -------------------------------------------------


def test_admin_promotes_a_viewer_to_editor(client: TestClient) -> None:
    admin, _ = bootstrap_admin(client)
    viewer_user = create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    viewer = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    assert client.get("/me", headers=bearer(viewer["token"])).json()["role"] == "viewer"

    denied = create_folder(client, viewer["token"], "Viewer Denied")
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == permissions.DENY_DETAIL[permissions.WRITE]

    promoted = patch_user(client, admin["token"], viewer_user["id"], {"role": "editor"})

    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "editor"
    # Same token, no re-login: the promotion is read from the database per request.
    me = client.get("/me", headers=bearer(viewer["token"]))
    assert me.status_code == 200
    assert me.json()["id"] == viewer_user["id"]
    assert me.json()["role"] == "editor"
    allowed = create_folder(client, viewer["token"], "Editor Allowed")
    assert allowed.status_code == 200, allowed.text


def test_admin_demotes_an_editor_and_the_live_session_loses_write_access(client: TestClient) -> None:
    admin, _ = bootstrap_admin(client)
    editor_user = create_user(client, admin["token"], EDITOR_USERNAME, EDITOR_PASSWORD, "editor")
    editor = login(client, EDITOR_USERNAME, EDITOR_PASSWORD)
    assert create_folder(client, editor["token"], "Editor Folder").status_code == 200

    demoted = patch_user(client, admin["token"], editor_user["id"], {"role": "viewer"})

    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == "viewer"

    write = create_folder(client, editor["token"], "After Demotion")
    assert write.status_code == 403, write.text
    assert write.json()["detail"] == permissions.DENY_DETAIL[permissions.WRITE]
    # Reads still work, and the identity still resolves: the session is alive and
    # only the role it carries changed.
    assert client.get("/assets", headers=bearer(editor["token"])).status_code == 200
    assert client.get("/me", headers=bearer(editor["token"])).json()["role"] == "viewer"
    # Not revoked either: the refresh token of the demoted session still rotates.
    refreshed = client.post("/refresh", json={"refresh_token": editor["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    assert client.post("/logout", json={"refresh_token": refreshed.json()["refresh_token"]}).status_code == 204


def test_only_an_admin_may_change_a_role(client: TestClient) -> None:
    admin, _ = bootstrap_admin(client)
    editor_user = create_user(client, admin["token"], EDITOR_USERNAME, EDITOR_PASSWORD, "editor")
    viewer_user = create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    editor = login(client, EDITOR_USERNAME, EDITOR_PASSWORD)
    viewer = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)

    for token, target in ((editor["token"], viewer_user["id"]), (editor["token"], editor_user["id"])):
        denied = patch_user(client, token, target, {"role": "admin"})
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"] == permissions.DENY_DETAIL[permissions.ADMIN]
    denied = patch_user(client, viewer["token"], viewer_user["id"], {"disabled": True})
    assert denied.status_code == 403
    assert denied.json()["detail"] == permissions.DENY_DETAIL[permissions.ADMIN]

    anonymous = client.patch(f"/users/{viewer_user['id']}", json={"role": "admin"})
    assert anonymous.status_code == 401, anonymous.text

    # A refused patch changed nothing, including the editor's own role.
    listing = {user["id"]: user["role"] for user in client.get("/users", headers=bearer(admin["token"])).json()}
    assert listing[editor_user["id"]] == "editor"
    assert listing[viewer_user["id"]] == "viewer"


def test_user_patch_validation(client: TestClient) -> None:
    admin, _ = bootstrap_admin(client)
    viewer_user = create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")

    unknown_role = patch_user(client, admin["token"], viewer_user["id"], {"role": "owner"})
    empty_patch = patch_user(client, admin["token"], viewer_user["id"], {})
    unknown_field = patch_user(client, admin["token"], viewer_user["id"], {"nickname": "root"})
    extra_alongside_a_change = patch_user(
        client, admin["token"], viewer_user["id"], {"disabled": False, "nickname": "root"}
    )
    unknown_user = patch_user(client, admin["token"], "does-not-exist", {"disabled": True})

    assert unknown_role.status_code == 422, unknown_role.text
    assert empty_patch.status_code == 422, empty_patch.text
    assert unknown_field.status_code == 422, unknown_field.text
    assert extra_alongside_a_change.status_code == 422, extra_alongside_a_change.text
    assert unknown_user.status_code == 404, unknown_user.text

    # `{"disabled": ...}` on its own is still a valid patch (no forced role).
    disabled = patch_user(client, admin["token"], viewer_user["id"], {"disabled": True})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["disabled"] is True
    assert disabled.json()["role"] == "viewer"
    enabled = patch_user(client, admin["token"], viewer_user["id"], {"disabled": False})
    assert enabled.status_code == 200
    assert enabled.json()["disabled"] is False


# --- the last-admin invariant ----------------------------------------------


def test_the_last_admin_cannot_demote_itself(client: TestClient) -> None:
    admin, admin_user = bootstrap_admin(client)

    response = patch_user(client, admin["token"], admin_user["id"], {"role": "editor"})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == LAST_ADMIN_DETAIL
    # Refused, not half-applied: the session is still an administrator.
    role_after = patch_user(client, admin["token"], admin_user["id"], {"role": "admin"})
    assert role_after.status_code == 200
    assert client.get("/users", headers=bearer(admin["token"])).status_code == 200


def test_the_last_admin_cannot_disable_itself(client: TestClient) -> None:
    admin, admin_user = bootstrap_admin(client)

    response = patch_user(client, admin["token"], admin_user["id"], {"disabled": True})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == LAST_ADMIN_DETAIL
    assert client.get("/users", headers=bearer(admin["token"])).status_code == 200
    me = client.get("/me", headers=bearer(admin["token"]))
    assert me.json()["role"] == "admin"
    assert me.json()["disabled"] is False


def test_a_second_enabled_admin_allows_self_demotion(client: TestClient) -> None:
    admin, admin_user = bootstrap_admin(client)
    create_user(client, admin["token"], "second", "second-password-1", "admin")
    second = login(client, "second", "second-password-1")
    assert client.get("/users", headers=bearer(second["token"])).status_code == 200

    demoted = patch_user(client, admin["token"], admin_user["id"], {"role": "viewer"})

    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == "viewer"
    # The demoted admin loses admin-only access on its very next request, while
    # the surviving admin keeps it (and reads stay open for the demoted one).
    denied = client.get("/users", headers=bearer(admin["token"]))
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == permissions.DENY_DETAIL[permissions.ADMIN]
    assert client.get("/assets", headers=bearer(admin["token"])).status_code == 200
    assert client.get("/users", headers=bearer(second["token"])).status_code == 200


def test_a_disabled_second_admin_does_not_count(client: TestClient) -> None:
    admin, admin_user = bootstrap_admin(client)
    second_user = create_user(client, admin["token"], "second", "second-password-1", "admin")

    disabled = patch_user(client, admin["token"], second_user["id"], {"disabled": True})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["disabled"] is True

    # The only remaining enabled admin is the caller: demoting itself is refused.
    demote = patch_user(client, admin["token"], admin_user["id"], {"role": "editor"})
    assert demote.status_code == 409, demote.text
    assert demote.json()["detail"] == LAST_ADMIN_DETAIL
    disable_self = patch_user(client, admin["token"], admin_user["id"], {"disabled": True})
    assert disable_self.status_code == 409, disable_self.text
    assert disable_self.json()["detail"] == LAST_ADMIN_DETAIL


def test_a_combined_role_and_disable_patch_is_guarded_too(client: TestClient) -> None:
    """Both fields feed one viability decision, so one request cannot sneak past."""
    admin, admin_user = bootstrap_admin(client)

    response = patch_user(client, admin["token"], admin_user["id"], {"role": "editor", "disabled": True})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == LAST_ADMIN_DETAIL
    # Refused, not half-applied: neither half of the patch reached the account.
    me = client.get("/me", headers=bearer(admin["token"]))
    assert me.json()["role"] == "admin"
    assert me.json()["disabled"] is False


def test_a_combined_promote_and_enable_patch_makes_a_viable_admin(client: TestClient) -> None:
    """The same request shape is allowed when the post-change state is viable."""
    admin, admin_user = bootstrap_admin(client)
    second_user = create_user(client, admin["token"], "second", "second-password-1", "editor")
    assert patch_user(client, admin["token"], second_user["id"], {"disabled": True}).status_code == 200

    promoted = patch_user(client, admin["token"], second_user["id"], {"role": "admin", "disabled": False})

    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "admin"
    assert promoted.json()["disabled"] is False
    # The promoted account is a viable admin now, so the caller may step down.
    assert patch_user(client, admin["token"], admin_user["id"], {"role": "viewer"}).status_code == 200


# --- break-glass and fail-closed -------------------------------------------


def test_break_glass_administers_an_empty_deployment(client: TestClient) -> None:
    glass = login(client, **BREAK_GLASS)

    assert client.get("/users", headers=bearer(glass["token"])).json() == []
    template = client.get("/settings/storage", headers=bearer(glass["token"])).json()["template"]
    stored = client.post("/settings/storage", json={"template": template}, headers=bearer(glass["token"]))
    assert stored.status_code == 200, stored.text
    assert client.post("/trash/purge", headers=bearer(glass["token"])).status_code == 200

    me = client.get("/me", headers=bearer(glass["token"]))
    assert me.status_code == 200
    assert me.json() == {
        "id": None,
        "username": "admin",
        "email": None,
        "role": "admin",
        "disabled": False,
        "kind": "break-glass",
    }


def test_an_unknown_role_in_the_database_fails_closed(client: TestClient) -> None:
    admin, _ = bootstrap_admin(client)
    viewer_user = create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    viewer = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    assert client.get("/assets", headers=bearer(viewer["token"])).status_code == 200

    # Bypass the API: a hand-edited row, or a role from a future release.
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE users SET role = 'owner' WHERE id = ?", (viewer_user["id"],))

    read = client.get("/assets", headers=bearer(viewer["token"]))
    assert read.status_code == 403, read.text
    assert read.json()["detail"] == permissions.DENY_DETAIL[permissions.READ]
    assert create_folder(client, viewer["token"], "Owner Denied").status_code == 403
    # `/me` is a read route, so even the identity endpoint is closed: an unknown
    # role ranks as public, not as "at least a viewer". A 401 would mean the token
    # was refused; a 403 means it authenticated and the role granted nothing.
    assert client.get("/me", headers=bearer(viewer["token"])).status_code == 403
    listing = client.get("/users", headers=bearer(admin["token"])).json()
    assert [user["role"] for user in listing if user["id"] == viewer_user["id"]] == ["owner"]
    assert client.get("/assets", headers=bearer(admin["token"])).status_code == 200


# --- the startup check itself ----------------------------------------------


def tiny_app(path: str, *dependencies) -> FastAPI:
    """A throwaway app with one route, so a matrix can be checked in isolation."""
    app = FastAPI()

    def handler():
        return {"ok": True}

    app.get(path, dependencies=list(dependencies))(handler)
    return app


def test_assert_routes_classified_accepts_a_matching_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = {("GET", "/open"): permissions.PUBLIC}
    monkeypatch.setattr(permissions, "ROUTE_PERMISSIONS", matrix)

    assert permissions.assert_routes_classified(tiny_app("/open")) is matrix


def test_assert_routes_classified_rejects_an_unclassified_route(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = {("GET", "/unclassified"): permissions.READ}
    monkeypatch.setattr(permissions, "ROUTE_PERMISSIONS", matrix)

    with pytest.raises(RuntimeError) as excinfo:
        permissions.assert_routes_classified(tiny_app("/unclassified"))

    message = str(excinfo.value)
    assert "permission matrix does not match the routes" in message
    assert "GET /unclassified declares no permission but the matrix says 'read'" in message


def test_assert_routes_classified_rejects_two_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = {("GET", "/twice"): permissions.READ}
    monkeypatch.setattr(permissions, "ROUTE_PERMISSIONS", matrix)

    with pytest.raises(RuntimeError) as excinfo:
        permissions.assert_routes_classified(
            tiny_app("/twice", Depends(permissions.require_read), Depends(permissions.require_write))
        )

    message = str(excinfo.value)
    assert "/twice declares 2 permission levels (read, write); declare exactly one" in message


def test_assert_routes_classified_rejects_a_route_missing_from_the_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(permissions, "ROUTE_PERMISSIONS", {})

    with pytest.raises(RuntimeError) as excinfo:
        permissions.assert_routes_classified(tiny_app("/unlisted", Depends(permissions.require_read)))

    message = str(excinfo.value)
    assert "GET /unlisted is missing from ROUTE_PERMISSIONS" in message


def test_assert_routes_classified_rejects_a_level_that_drifted(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = {("GET", "/drifted"): permissions.READ}
    monkeypatch.setattr(permissions, "ROUTE_PERMISSIONS", matrix)

    with pytest.raises(RuntimeError) as excinfo:
        permissions.assert_routes_classified(tiny_app("/drifted", Depends(permissions.require_write)))

    message = str(excinfo.value)
    assert "GET /drifted declares 'write' but the matrix says 'read'" in message


def test_assert_routes_classified_rejects_a_stale_matrix_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = {("GET", "/gone"): permissions.PUBLIC}
    monkeypatch.setattr(permissions, "ROUTE_PERMISSIONS", matrix)

    with pytest.raises(RuntimeError) as excinfo:
        permissions.assert_routes_classified(tiny_app("/elsewhere"))

    message = str(excinfo.value)
    assert "GET /gone is in ROUTE_PERMISSIONS but no such route exists" in message
