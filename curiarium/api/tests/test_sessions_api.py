"""The four session routes: list/revoke own devices and administer another user's.

AC-1 is the list contract (one row per active session, never a hash), AC-2 is
"revoking my session kills my access token and my outstanding file grant", and
AC-3 is the admin surface. Every test starts from empty users/sessions and a
private storage root, so nothing here leaks a row or a file into another file.
"""

import json
from typing import Optional
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import asset_file_service
import asset_service
import audit
import auth
import db
import library_scan
import login_throttle as login_throttle_module
import main
import sessions
from db import engine
from migrations import run_migrations
from models import Asset, AssetFile, AuditEvent, Folder, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}
STL_BYTES = b"solid cube\nendsolid cube\n"
NOT_CONFIGURED = "Authentication is not configured on the server"
SESSION_KEYS = {
    "id",
    "username",
    "kind",
    "device",
    "user_agent",
    "client_ip",
    "created_at",
    "last_used_at",
    "current",
}


def truncate_accounts() -> None:
    with Session(engine) as db_session:
        db_session.execute(delete(UserSession))
        db_session.execute(delete(User))
        db_session.commit()


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
def isolated_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point every storage binding at a temp root and undo the rows a test made."""
    storage = tmp_path / "storage"
    (storage / "thumbs").mkdir(parents=True)
    monkeypatch.setattr(db, "STORAGE", storage)
    monkeypatch.setattr(db, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(main, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "THUMBS", storage / "thumbs")
    monkeypatch.setattr(asset_service, "STORAGE", storage)
    monkeypatch.setattr(asset_file_service, "STORAGE", storage)
    monkeypatch.setattr(library_scan, "STORAGE", storage)
    run_migrations(engine)

    with Session(engine) as session:
        assets_before = {asset.id for asset in session.exec(select(Asset))}
        folders_before = {folder.id for folder in session.exec(select(Folder))}

    yield storage

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


def bootstrap_admin(client: TestClient) -> dict:
    glass = login(client, **BREAK_GLASS)
    created = create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, "admin")
    admin = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    admin["id"] = created["id"]
    return admin


def sid_of(token: str) -> str:
    return str(auth.decode_access_token(token)["sid"])


def create_session(
    *,
    user_id: Optional[str],
    username: str = ADMIN_USERNAME,
    kind: str = sessions.PASSWORD_KIND,
    device: Optional[str] = None,
) -> str:
    with Session(engine) as db_session:
        row, _ = sessions.create(
            db_session,
            username=username,
            user_id=user_id,
            kind=kind,
            access_ttl=auth.AUTH_ACCESS_TOKEN_TTL,
            refresh_ttl=auth.AUTH_REFRESH_TTL_SECONDS,
            device=device,
        )
        db_session.commit()
        return row.id


def audit_rows(action: str, target: str) -> list[AuditEvent]:
    with Session(engine) as db_session:
        return list(
            db_session.exec(select(AuditEvent).where(AuditEvent.action == action, AuditEvent.target == target))
        )


def upload_with_supporting_file(client: TestClient, token: str) -> tuple[dict, dict]:
    asset = client.post(
        "/upload", files={"file": ("cube.stl", STL_BYTES, "model/stl")}, headers=bearer(token)
    )
    assert asset.status_code == 200, asset.text
    created = client.post(
        f"/asset/{asset.json()['id']}/files",
        files={"file": ("notes.txt", b"layer notes\n", "text/plain")},
        headers=bearer(token),
    )
    assert created.status_code == 200, created.text
    files = client.get(f"/asset/{asset.json()['id']}/files", headers=bearer(token))
    assert files.status_code == 200, files.text
    return asset.json(), files.json()[0]


# --- AC-1: the list contract --------------------------------------------------


def test_list_me_sessions_returns_one_row_per_active_session(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    second = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    oidc_id = create_session(user_id=admin["id"], kind=sessions.OIDC_KIND, device="sso")
    revoked_id = create_session(user_id=admin["id"], device="dead")
    with Session(engine) as db_session:
        sessions.revoke(db_session, db_session.get(UserSession, revoked_id))
        db_session.commit()

    listing = client.get("/me/sessions", headers=bearer(admin["token"]))

    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert {row["id"] for row in rows} == {sid_of(admin["token"]), sid_of(second["token"]), oidc_id}
    assert {row["kind"] for row in rows} == {sessions.PASSWORD_KIND, sessions.OIDC_KIND}
    assert next(row for row in rows if row["id"] == oidc_id)["device"] == "sso"
    for row in rows:
        assert set(row) == SESSION_KEYS
        assert not any("hash" in key for key in row)
        assert isinstance(row["created_at"], int)
        assert isinstance(row["last_used_at"], int)
    current = [row for row in rows if row["current"]]
    assert len(current) == 1
    assert current[0]["id"] == sid_of(admin["token"])


def test_a_revoked_session_is_not_listed(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    doomed = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    doomed_sid = sid_of(doomed["token"])
    assert client.delete(f"/me/sessions/{doomed_sid}", headers=bearer(admin["token"])).status_code == 204

    listing = client.get("/me/sessions", headers=bearer(admin["token"]))

    assert [row["id"] for row in listing.json()] == [sid_of(admin["token"])]


def test_break_glass_sessions_are_listed_for_break_glass(client: TestClient) -> None:
    glass = login(client, **BREAK_GLASS)

    listing = client.get("/me/sessions", headers=bearer(glass["token"]))

    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert len(rows) == 1
    assert set(rows[0]) == SESSION_KEYS
    assert rows[0]["id"] == sid_of(glass["token"])
    assert rows[0]["current"] is True
    assert rows[0]["kind"] == sessions.BREAK_GLASS_KIND
    assert rows[0]["username"] == "admin"


# --- AC-2: revoking my session kills my credential ----------------------------


def test_revoking_my_session_kills_the_access_token_and_its_file_grant(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    asset, supporting = upload_with_supporting_file(client, admin["token"])
    grant_path = f"/asset/{asset['id']}/files/{supporting['id']}"
    minted = client.post("/file-grants", json={"paths": [grant_path]}, headers=bearer(admin["token"]))
    assert minted.status_code == 200, minted.text
    grant_url = minted.json()["grants"][0]["url"]
    assert client.get(grant_url).status_code == 200

    revoked = client.delete(f"/me/sessions/{sid_of(admin['token'])}", headers=bearer(admin["token"]))

    assert revoked.status_code == 204
    # Same still-unexpired access token, two different authenticators: the
    # header path and the `?sig=` grant both re-read the session row.
    assert client.get("/assets", headers=bearer(admin["token"])).status_code == 401
    assert client.get(grant_url).status_code == 401


# --- AC-3: an admin administers another principal's sessions ------------------


def test_admin_lists_and_revokes_another_users_session(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    viewer = create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    viewer_session = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    viewer_sid = sid_of(viewer_session["token"])

    listing = client.get(f"/users/{viewer['id']}/sessions", headers=bearer(admin["token"]))

    assert listing.status_code == 200, listing.text
    rows = listing.json()
    assert [row["id"] for row in rows] == [viewer_sid]
    assert rows[0]["username"] == VIEWER_USERNAME
    assert rows[0]["current"] is False

    revoked = client.delete(f"/sessions/{viewer_sid}", headers=bearer(admin["token"]))

    assert revoked.status_code == 204
    assert client.get("/assets", headers=bearer(viewer_session["token"])).status_code == 401
    events = audit_rows(audit.SESSION_ADMIN_REVOKE, viewer_sid)
    assert len(events) == 1
    assert events[0].actor == ADMIN_USERNAME
    assert events[0].actor_user_id == admin["id"]
    assert json.loads(events[0].detail_json or "{}")["username"] == VIEWER_USERNAME


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_non_admins_cannot_use_the_admin_session_routes(client: TestClient, role: str) -> None:
    admin = bootstrap_admin(client)
    create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, role)
    member = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    admin_sid = sid_of(admin["token"])

    listing = client.get(f"/users/{admin['id']}/sessions", headers=bearer(member["token"]))
    revoking = client.delete(f"/sessions/{admin_sid}", headers=bearer(member["token"]))

    assert listing.status_code == 403
    assert revoking.status_code == 403
    # Refused before the handler, so the admin's session was never touched.
    assert client.get("/assets", headers=bearer(admin["token"])).status_code == 200


def test_a_foreign_session_id_is_404_and_leaves_it_live(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD, "viewer")
    viewer = login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    admin_sid = sid_of(admin["token"])

    response = client.delete(f"/me/sessions/{admin_sid}", headers=bearer(viewer["token"]))

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"
    assert client.get("/assets", headers=bearer(admin["token"])).status_code == 200


def test_an_unknown_session_id_is_404_on_both_delete_routes(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    unknown = uuid4().hex

    mine = client.delete(f"/me/sessions/{unknown}", headers=bearer(admin["token"]))
    administered = client.delete(f"/sessions/{unknown}", headers=bearer(admin["token"]))

    assert mine.status_code == 404
    assert administered.status_code == 404


def test_revoking_the_same_session_twice_is_idempotent(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    doomed = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    sid = sid_of(doomed["token"])

    first = client.delete(f"/me/sessions/{sid}", headers=bearer(admin["token"]))
    second = client.delete(f"/me/sessions/{sid}", headers=bearer(admin["token"]))

    assert first.status_code == 204
    assert second.status_code == 204


def test_the_session_routes_503_when_auth_is_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    unknown = uuid4().hex

    for method, path in (
        ("get", "/me/sessions"),
        ("delete", f"/me/sessions/{unknown}"),
        ("get", f"/users/{unknown}/sessions"),
        ("delete", f"/sessions/{unknown}"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 503, f"{method.upper()} {path} answered {response.status_code}"
        assert response.json()["detail"] == NOT_CONFIGURED
