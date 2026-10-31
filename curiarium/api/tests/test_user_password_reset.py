"""The admin password reset (Mf-bj51): one route, two doors, one audit row.

Every test starts from an empty users/sessions/identity set and the shared login
throttle cleared, so nothing here can leak an account, a revocation or a lockout
into a later test. The password the shared fixture signs a member in with is
never changed in place: a reset in these tests always targets a throwaway, so
the sweeps in the other files keep the credential they seeded.

`test_a_promoted_role_survives_the_next_login` in `tests/test_oidc.py` already
covers the ticket's "promoting an OIDC account to admin survives re-login"
criterion; nothing is re-asserted here.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import accounts
import audit
import login_throttle as login_throttle_module
import main
from db import engine
from migrations import run_migrations
from models import AuditEvent, OidcIdentity, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
MEMBER_USERNAME = "member"
MEMBER_PASSWORD = "member-password-1"
NEW_PASSWORD = "member-password-2"
EDITOR_USERNAME = "editor"
EDITOR_PASSWORD = "editor-password-1"
VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = "viewer-password-1"
SSO_USERNAME = "cosmos-user"
ISSUER = "https://idp.example.com"
SUBJECT = "cosmos-subject-0001"
REQUEST_ID_HEADER = "X-Request-ID"


def truncate_accounts() -> None:
    """Remove every account, session and SSO binding, children first."""
    with Session(engine) as db:
        db.execute(delete(OidcIdentity))
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

    Every test here hashes and verifies several passwords; at the library
    defaults each one costs ~50 ms, which would make this file slower than the
    code it guards. Nothing here asserts anything about hash strength.
    """
    monkeypatch.setattr(accounts, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture()
def client():
    with TestClient(main.app) as test_client:
        yield test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def break_glass_login(client: TestClient) -> dict:
    response = client.post("/login", json={"username": "admin", "password": "super-secret"})
    assert response.status_code == 200, response.text
    return response.json()


def login_user(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def create_user(
    client: TestClient,
    admin_token: str,
    username: str,
    password: str,
    role: str = "viewer",
    email: str | None = None,
) -> dict:
    payload: dict = {"username": username, "password": password, "role": role}
    if email is not None:
        payload["email"] = email
    response = client.post("/users", json=payload, headers=bearer(admin_token))
    assert response.status_code == 201, response.text
    return response.json()


def bootstrap_admin(client: TestClient) -> dict:
    """Let break-glass create the first (admin) account, then sign in as it."""
    glass = break_glass_login(client)
    create_user(client, glass["token"], ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")
    return login_user(client, ADMIN_USERNAME, ADMIN_PASSWORD)


def create_sso_account(username: str = SSO_USERNAME, role: str = accounts.DEFAULT_ROLE) -> User:
    """Provision an account the way the IdP path does: no local password, ever.

    There is no API that mints one without an identity provider, so a test that
    needs an SSO account writes the row directly, exactly like
    `tests/test_oidc.py`.
    """
    with Session(engine) as db:
        user = accounts.create_sso_user(db, username=username, email=f"{username}@example.com", role=role)
        db.add(
            OidcIdentity(
                id=str(uuid.uuid4()),
                issuer=ISSUER,
                subject=SUBJECT,
                user_id=user.id,
                created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            )
        )
        db.commit()
        db.refresh(user)
        db.expunge(user)
    return user


def disable_account(client: TestClient, admin_token: str, user_id: str) -> None:
    response = client.patch(f"/users/{user_id}", json={"disabled": True}, headers=bearer(admin_token))
    assert response.status_code == 200, response.text


def request_id_for(test_name: str) -> str:
    """A unique, header-legal id: letters, digits and dashes only."""
    return f"{test_name}-{uuid.uuid4().hex}"


def events_for(value: str) -> list[AuditEvent]:
    with Session(engine) as db:
        return list(db.exec(select(AuditEvent).where(AuditEvent.request_id == value)))


def test_an_admin_reset_replaces_the_password_and_the_old_one_stops_working(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    member = create_user(client, admin["token"], MEMBER_USERNAME, MEMBER_PASSWORD)
    login_user(client, MEMBER_USERNAME, MEMBER_PASSWORD)

    response = client.post(
        f"/users/{member['id']}/password",
        json={"password": NEW_PASSWORD},
        headers=bearer(admin["token"]),
    )

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert client.post("/login", json={"username": MEMBER_USERNAME, "password": MEMBER_PASSWORD}).status_code == 401
    assert client.post("/login", json={"username": MEMBER_USERNAME, "password": NEW_PASSWORD}).status_code == 200


def test_only_an_admin_may_reset_a_password(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    create_user(client, admin["token"], EDITOR_USERNAME, EDITOR_PASSWORD, role="editor")
    viewer = create_user(client, admin["token"], VIEWER_USERNAME, VIEWER_PASSWORD)
    editor_session = login_user(client, EDITOR_USERNAME, EDITOR_PASSWORD)
    viewer_session = login_user(client, VIEWER_USERNAME, VIEWER_PASSWORD)

    def reset(headers: dict[str, str]):
        return client.post(f"/users/{viewer['id']}/password", json={"password": NEW_PASSWORD}, headers=headers)

    assert reset(bearer(editor_session["token"])).status_code == 403
    assert reset(bearer(viewer_session["token"])).status_code == 403
    assert reset({}).status_code == 401
    # The refusals changed nothing: the editor's account is still not a door.
    assert reset(bearer(admin["token"])).status_code == 204


def test_the_password_never_reaches_the_response_logs_or_the_audit_row(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    admin = bootstrap_admin(client)
    member = create_user(client, admin["token"], MEMBER_USERNAME, MEMBER_PASSWORD)
    secret = "brand-new-secret-7f2c"
    value = request_id_for("reset-hygiene")

    response = client.post(
        f"/users/{member['id']}/password",
        json={"password": secret},
        headers={**bearer(admin["token"]), REQUEST_ID_HEADER: value},
    )

    assert response.status_code == 204, response.text
    assert response.text == ""
    assert secret not in response.text
    assert secret not in caplog.text
    rows = events_for(value)
    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json)
    assert secret not in rows[0].detail_json
    assert secret not in json.dumps(detail)


def test_the_reset_writes_one_audit_row_naming_the_account_and_the_revocations(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    member = create_user(client, admin["token"], MEMBER_USERNAME, MEMBER_PASSWORD)
    login_user(client, MEMBER_USERNAME, MEMBER_PASSWORD)
    value = request_id_for("reset-audit")

    response = client.post(
        f"/users/{member['id']}/password",
        json={"password": NEW_PASSWORD},
        headers={**bearer(admin["token"]), REQUEST_ID_HEADER: value},
    )

    assert response.status_code == 204, response.text
    rows = events_for(value)
    assert [row.action for row in rows] == [audit.USER_PASSWORD_RESET]
    row = rows[0]
    assert row.target == MEMBER_USERNAME
    detail = json.loads(row.detail_json)
    assert detail["user_id"] == member["id"]
    assert detail["sessions_revoked"] == 1
    assert detail["reset_disabled"] is False
    assert detail["granted_local_login"] is False


def test_a_disabled_account_needs_the_explicit_flag_and_stays_disabled(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    member = create_user(client, admin["token"], MEMBER_USERNAME, MEMBER_PASSWORD)
    disable_account(client, admin["token"], member["id"])

    refused = client.post(
        f"/users/{member['id']}/password",
        json={"password": NEW_PASSWORD},
        headers=bearer(admin["token"]),
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == "this account is disabled; re-enable it before resetting its password"

    allowed = client.post(
        f"/users/{member['id']}/password",
        json={"password": NEW_PASSWORD, "allow_disabled": True},
        headers=bearer(admin["token"]),
    )

    assert allowed.status_code == 204, allowed.text
    # The flag opened the credential, not the account: `disabled` is untouched,
    # so the new password still cannot sign in.
    assert client.post("/login", json={"username": MEMBER_USERNAME, "password": NEW_PASSWORD}).status_code == 401


def test_an_sso_account_needs_the_explicit_flag_to_get_a_local_password(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    sso_account = create_sso_account()

    refused = client.post(
        f"/users/{sso_account.id}/password",
        json={"password": NEW_PASSWORD},
        headers=bearer(admin["token"]),
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "this account signs in with SSO; give it a local password only if the identity provider is unavailable"
    )

    value = request_id_for("reset-sso")
    allowed = client.post(
        f"/users/{sso_account.id}/password",
        json={"password": NEW_PASSWORD, "allow_sso": True},
        headers={**bearer(admin["token"]), REQUEST_ID_HEADER: value},
    )

    assert allowed.status_code == 204, allowed.text
    detail = json.loads(events_for(value)[0].detail_json)
    assert detail["granted_local_login"] is True
    assert client.post("/login", json={"username": SSO_USERNAME, "password": NEW_PASSWORD}).status_code == 200


def test_a_short_password_is_422_and_an_extra_field_is_422(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    member = create_user(client, admin["token"], MEMBER_USERNAME, MEMBER_PASSWORD)

    short = client.post(
        f"/users/{member['id']}/password",
        json={"password": "1234567"},
        headers=bearer(admin["token"]),
    )
    extra = client.post(
        f"/users/{member['id']}/password",
        json={"password": NEW_PASSWORD, "role": "admin"},
        headers=bearer(admin["token"]),
    )

    assert short.status_code == 422
    assert extra.status_code == 422


def test_the_reset_revokes_the_targets_other_sessions_but_not_the_callers_own(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    member = create_user(client, admin["token"], MEMBER_USERNAME, MEMBER_PASSWORD)
    first = login_user(client, MEMBER_USERNAME, MEMBER_PASSWORD)
    second = login_user(client, MEMBER_USERNAME, MEMBER_PASSWORD)

    reset = client.post(
        f"/users/{member['id']}/password",
        json={"password": NEW_PASSWORD},
        headers=bearer(admin["token"]),
    )

    assert reset.status_code == 204, reset.text
    assert client.get("/me", headers=bearer(first["token"])).status_code == 401
    assert client.get("/me", headers=bearer(second["token"])).status_code == 401
    # An admin resetting their own password is not signed out of the tab that
    # did it: losing that session is the one lockout this route could cause.
    admin_id = client.get("/me", headers=bearer(admin["token"])).json()["id"]
    own_reset = client.post(
        f"/users/{admin_id}/password",
        json={"password": "root-password-2"},
        headers=bearer(admin["token"]),
    )
    assert own_reset.status_code == 204, own_reset.text
    assert client.get("/me", headers=bearer(admin["token"])).status_code == 200


def test_an_unknown_user_id_is_404(client: TestClient) -> None:
    admin = bootstrap_admin(client)

    response = client.post(
        "/users/00000000-0000-0000-0000-000000000000/password",
        json={"password": NEW_PASSWORD},
        headers=bearer(admin["token"]),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_the_users_list_reports_the_credential_and_the_binding_separately(client: TestClient) -> None:
    admin = bootstrap_admin(client)
    local = create_user(client, admin["token"], MEMBER_USERNAME, MEMBER_PASSWORD)
    sso_account = create_sso_account()

    response = client.get("/users", headers=bearer(admin["token"]))

    assert response.status_code == 200, response.text
    users = {user["username"]: user for user in response.json()}
    assert users[MEMBER_USERNAME]["auth_source"] == "local"
    assert users[MEMBER_USERNAME]["oidc_issuer"] is None
    assert users[MEMBER_USERNAME]["oidc_subject"] is None
    assert users[SSO_USERNAME]["auth_source"] == "sso"
    assert users[SSO_USERNAME]["oidc_issuer"] == ISSUER
    assert users[SSO_USERNAME]["oidc_subject"] == SUBJECT
    assert users[MEMBER_USERNAME]["id"] == local["id"]
    assert users[SSO_USERNAME]["id"] == sso_account.id
