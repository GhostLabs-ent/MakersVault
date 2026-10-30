"""Refresh rotation, the one-generation grace window, and replay detection.

AC-5 (a second tab survives one rotation) and AC-6 (a replay revokes that session
row and is audited) are both decisions `sessions.rotate` makes, so every test
drives the real `POST /refresh` route and then reads the row and the audit log
back. The clock is the module's `_now()` seam, so ageing a row never sleeps.
"""

import json
import time
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

import audit
import auth
import login_throttle as login_throttle_module
import main
import sessions
from db import engine
from migrations import run_migrations
from models import AuditEvent, User, UserSession

ADMIN_USERNAME = "root"
ADMIN_PASSWORD = "root-password-1"
BREAK_GLASS = {"username": "admin", "password": "super-secret"}


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


def refresh(client: TestClient, token: str) -> object:
    return client.post("/refresh", json={"refresh_token": token})


def bootstrap_admin(client: TestClient) -> tuple[dict, str]:
    """Break-glass creates the first admin, then sign in as that account."""
    glass = login(client, **BREAK_GLASS)
    created = client.post(
        "/users",
        json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "role": "admin"},
        headers=bearer(glass["token"]),
    )
    assert created.status_code == 201, created.text
    admin = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    me = client.get("/me", headers=bearer(admin["token"]))
    assert me.status_code == 200, me.text
    return admin, me.json()["id"]


def sid_of(token: str) -> str:
    return str(auth.decode_access_token(token)["sid"])


def stored_row(sid: str) -> UserSession:
    with Session(engine) as db:
        row = db.get(UserSession, sid)
        assert row is not None
        db.expunge(row)
    return row


def presented_row(token: str) -> Optional[UserSession]:
    with Session(engine) as db:
        row = sessions.find_by_presented_hash(db, sessions.hash_refresh_token(token))
        if row is not None:
            db.expunge(row)
        return row


def age_rotation(sid: str, *, seconds_ago: int) -> None:
    """Move `rotated_at` into the past so a grace-window boundary is exact."""
    with Session(engine) as db:
        row = db.get(UserSession, sid)
        assert row is not None
        row.rotated_at = sessions._now() - seconds_ago
        db.commit()


def audit_rows(sid: str, action: str) -> list[AuditEvent]:
    with Session(engine) as db:
        return list(
            db.exec(select(AuditEvent).where(AuditEvent.action == action, AuditEvent.target == sid))
        )


def test_a_second_presentation_inside_the_window_is_graced_and_audited(client: TestClient) -> None:
    tokens, admin_id = bootstrap_admin(client)
    sid = sid_of(tokens["token"])

    first = refresh(client, tokens["refresh_token"])
    second = refresh(client, tokens["refresh_token"])

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["refresh_token"] not in {
        tokens["refresh_token"],
        first.json()["refresh_token"],
    }

    rows = audit_rows(sid, audit.SESSION_REFRESH_GRACED)
    assert len(rows) == 1, [row.action for row in rows]
    row = rows[0]
    assert row.actor == ADMIN_USERNAME
    assert row.actor_user_id == admin_id
    assert row.actor_role == "admin"
    assert row.actor_kind == "password"
    detail = json.loads(row.detail_json or "{}")
    assert isinstance(detail["client_ip"], str)


def test_the_grace_is_consumed_by_one_replay(client: TestClient) -> None:
    tokens, _ = bootstrap_admin(client)
    sid = sid_of(tokens["token"])
    assert refresh(client, tokens["refresh_token"]).status_code == 200
    assert refresh(client, tokens["refresh_token"]).status_code == 200

    # The grace rotation moved the superseded hash another generation back, so
    # the original is now older than the one generation that is looked up.
    third = refresh(client, tokens["refresh_token"])

    assert third.status_code == 401
    assert len(audit_rows(sid, audit.SESSION_REFRESH_GRACED)) == 1
    assert audit_rows(sid, audit.SESSION_REFRESH_REPLAYED) == []


def test_a_previous_generation_token_outside_the_window_revokes_and_is_audited(client: TestClient) -> None:
    tokens, admin_id = bootstrap_admin(client)
    sid = sid_of(tokens["token"])
    first = refresh(client, tokens["refresh_token"])
    assert first.status_code == 200, first.text
    age_rotation(sid, seconds_ago=sessions.REFRESH_GRACE_SECONDS + 1)

    replayed = refresh(client, tokens["refresh_token"])

    assert replayed.status_code == 401
    assert replayed.json()["detail"] == "Invalid or expired refresh token"
    # The revoke and the row that explains it were committed before the 401.
    assert stored_row(sid).revoked_at is not None
    rows = audit_rows(sid, audit.SESSION_REFRESH_REPLAYED)
    assert len(rows) == 1, [row.action for row in rows]
    assert rows[0].actor == ADMIN_USERNAME
    assert rows[0].actor_user_id == admin_id
    # The access tokens minted before the replay are dead on the next request.
    assert client.get("/assets", headers=bearer(tokens["token"])).status_code == 401
    assert client.get("/assets", headers=bearer(first.json()["token"])).status_code == 401


def test_an_unknown_hash_is_a_side_effect_free_401(client: TestClient) -> None:
    tokens, _ = bootstrap_admin(client)
    sid = sid_of(tokens["token"])

    response = refresh(client, "this-token-never-existed")

    assert response.status_code == 401
    assert stored_row(sid).revoked_at is None
    assert audit_rows(sid, audit.SESSION_REFRESH_GRACED) == []
    assert audit_rows(sid, audit.SESSION_REFRESH_REPLAYED) == []


def test_a_replay_revokes_only_that_session_row(client: TestClient) -> None:
    tokens_a, _ = bootstrap_admin(client)
    tokens_b = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    sid_a = sid_of(tokens_a["token"])
    sid_b = sid_of(tokens_b["token"])
    assert sid_a != sid_b
    assert refresh(client, tokens_a["refresh_token"]).status_code == 200
    age_rotation(sid_a, seconds_ago=sessions.REFRESH_GRACE_SECONDS + 1)

    assert refresh(client, tokens_a["refresh_token"]).status_code == 401

    # Revoking every device of the owner would let anyone holding one stale
    # token sign the victim out everywhere, so the other session survives.
    assert stored_row(sid_b).revoked_at is None
    assert client.get("/assets", headers=bearer(tokens_b["token"])).status_code == 200
    assert refresh(client, tokens_b["refresh_token"]).status_code == 200


def test_the_grace_window_is_exactly_the_module_constant(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = int(time.time())
    monkeypatch.setattr(sessions, "_now", lambda: now)
    inside, _ = bootstrap_admin(client)
    outside = login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    inside_sid = sid_of(inside["token"])
    outside_sid = sid_of(outside["token"])
    assert refresh(client, inside["refresh_token"]).status_code == 200
    assert refresh(client, outside["refresh_token"]).status_code == 200

    age_rotation(inside_sid, seconds_ago=sessions.REFRESH_GRACE_SECONDS)
    age_rotation(outside_sid, seconds_ago=sessions.REFRESH_GRACE_SECONDS + 1)

    # The boundary is inclusive: exactly REFRESH_GRACE_SECONDS old is still
    # interchangeable, one second older is not.
    assert refresh(client, inside["refresh_token"]).status_code == 200
    assert refresh(client, outside["refresh_token"]).status_code == 401


def test_a_normal_refresh_writes_no_session_audit_row(client: TestClient) -> None:
    tokens, _ = bootstrap_admin(client)
    sid = sid_of(tokens["token"])

    assert refresh(client, tokens["refresh_token"]).status_code == 200

    assert audit_rows(sid, audit.SESSION_REFRESH_GRACED) == []
    assert audit_rows(sid, audit.SESSION_REFRESH_REPLAYED) == []


def test_logout_accepts_a_token_from_one_generation_back(client: TestClient) -> None:
    tokens, _ = bootstrap_admin(client)
    sid = sid_of(tokens["token"])
    assert refresh(client, tokens["refresh_token"]).status_code == 200

    response = client.post("/logout", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 204
    assert stored_row(sid).revoked_at is not None
