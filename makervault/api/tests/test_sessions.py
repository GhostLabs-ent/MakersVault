from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from identity_service import bootstrap_initial_administrator
from main import app
from migrations import run_migrations
from session_service import (
    DEVELOPMENT_CSRF_COOKIE,
    DEVELOPMENT_SESSION_COOKIE,
    PRODUCTION_CSRF_COOKIE,
    PRODUCTION_SESSION_COOKIE,
    authenticate_browser_session,
    cookie_policy,
    create_browser_session,
)


def _login(client: TestClient) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    body = response.json()
    return body, {
        "Origin": "http://testserver",
        "X-CSRF-Token": body["csrf_token"],
    }


def test_login_issues_http_only_session_without_returning_a_bearer() -> None:
    with TestClient(app) as client:
        body, _headers = _login(client)
        session_secret = client.cookies.get(DEVELOPMENT_SESSION_COOKIE)
        csrf_cookie = client.cookies.get(DEVELOPMENT_CSRF_COOKIE)

        assert body["authenticated"] is True
        assert body["expires_in"] > 0
        assert "token" not in body
        assert session_secret
        assert csrf_cookie == body["csrf_token"]

        current = client.get("/session")
        assert current.status_code == 200
        assert current.headers["cache-control"] == "private, no-store"
        assert current.json()["username"] == "admin"
        assert current.json()["session_id"]

    # TestClient's cookie jar exposes values but not Set-Cookie flags.
    with TestClient(app) as client:
        response = client.post(
            "/login",
            json={"username": "admin", "password": "test-only-password"},
        )
        cookies = response.headers.get_list("set-cookie")
        assert response.headers["cache-control"] == "private, no-store"
    session_header = next(
        value for value in cookies if value.startswith(f"{DEVELOPMENT_SESSION_COOKIE}=")
    )
    csrf_header = next(
        value for value in cookies if value.startswith(f"{DEVELOPMENT_CSRF_COOKIE}=")
    )
    assert "HttpOnly" in session_header
    assert "SameSite=lax" in session_header
    assert "HttpOnly" not in csrf_header
    assert "SameSite=lax" in csrf_header


def test_bearer_and_query_token_compatibility_paths_are_removed() -> None:
    with TestClient(app) as client:
        assert client.get(
            "/assets", headers={"Authorization": "Bearer legacy"}
        ).status_code == 401
        assert client.get("/assets?token=legacy").status_code == 401
        assert client.post("/refresh").status_code == 404


def test_production_cookie_policy_is_secure_and_separate_from_http_development() -> None:
    production = cookie_policy("production")
    development = cookie_policy("development")

    assert production.session_name == PRODUCTION_SESSION_COOKIE
    assert production.csrf_name == PRODUCTION_CSRF_COOKIE
    assert production.secure is True
    assert development.session_name == DEVELOPMENT_SESSION_COOKIE
    assert development.csrf_name == DEVELOPMENT_CSRF_COOKIE
    assert development.secure is False


def test_successful_login_rotates_a_presented_session() -> None:
    with TestClient(app) as client:
        _first_body, _headers = _login(client)
        first_secret = client.cookies.get(DEVELOPMENT_SESSION_COOKIE)
        assert first_secret

        _second_body, _headers = _login(client)
        second_secret = client.cookies.get(DEVELOPMENT_SESSION_COOKIE)
        assert second_secret and second_secret != first_secret
        assert client.get("/session").status_code == 200

    with TestClient(app) as replay:
        replay.cookies.set(DEVELOPMENT_SESSION_COOKIE, first_secret)
        assert replay.get("/session").status_code == 401


def test_cookie_mutations_require_exact_origin_and_bound_csrf() -> None:
    with TestClient(app) as client:
        body, headers = _login(client)

        assert client.post("/logout").status_code == 403
        assert client.post(
            "/logout",
            headers={
                "Origin": "https://attacker.example",
                "X-CSRF-Token": body["csrf_token"],
            },
        ).status_code == 403
        assert client.post(
            "/logout", headers={"Origin": "http://testserver"}
        ).status_code == 403
        assert client.get("/session").status_code == 200

        logged_out = client.post("/logout", headers=headers)
        assert logged_out.status_code == 204
        assert client.get("/session").status_code == 401


def test_logout_revokes_a_copied_session_secret() -> None:
    with TestClient(app) as client:
        _body, headers = _login(client)
        copied = client.cookies.get(DEVELOPMENT_SESSION_COOKIE)
        assert copied
        assert client.post("/logout", headers=headers).status_code == 204

    with TestClient(app) as replay:
        replay.cookies.set(DEVELOPMENT_SESSION_COOKIE, copied)
        assert replay.get("/session").status_code == 401


def test_session_listing_per_session_revocation_and_revoke_all() -> None:
    with TestClient(app) as first, TestClient(app) as second:
        _first_body, first_headers = _login(first)
        _second_body, second_headers = _login(second)
        first_id = first.get("/session").json()["session_id"]
        second_id = second.get("/session").json()["session_id"]
        assert first_id != second_id

        sessions = first.get("/sessions")
        assert sessions.status_code == 200
        ids = {item["id"] for item in sessions.json()}
        assert {first_id, second_id}.issubset(ids)

        revoked = first.delete(f"/sessions/{second_id}", headers=first_headers)
        assert revoked.status_code == 204
        assert second.get("/session").status_code == 401

        revoked_all = first.post("/sessions/revoke-all", headers=first_headers)
        assert revoked_all.status_code == 200
        assert revoked_all.json()["revoked"] >= 1
        assert first.get("/session").status_code == 401

        assert second.post("/logout", headers=second_headers).status_code == 401


def test_session_secret_is_hashed_and_idle_and_absolute_expiry_fail_closed(
    tmp_path: Path,
) -> None:
    database_engine = create_engine(
        f"sqlite:///{tmp_path / 'sessions.db'}",
        connect_args={"check_same_thread": False},
    )
    run_migrations(database_engine)
    bootstrap_initial_administrator(
        database_engine,
        username="owner",
        password="a sufficiently long owner password",
    )
    with database_engine.connect() as conn:
        user_id = conn.exec_driver_sql("SELECT id FROM useraccount").scalar_one()

    created = create_browser_session(
        database_engine,
        user_id=user_id,
        client_address="127.0.0.1",
        user_agent="test agent",
        now=100,
        idle_ttl=10,
        absolute_ttl=30,
    )
    with database_engine.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT secret_digest FROM browsersession WHERE id = ?",
            (created.id,),
        ).fetchone()
    assert stored is not None
    assert created.secret not in stored[0]
    assert created.csrf_token not in stored[0]

    assert authenticate_browser_session(
        database_engine, created.secret, now=109, touch=False
    ) is not None
    assert authenticate_browser_session(
        database_engine, created.secret, now=111, touch=False
    ) is None

    absolute = create_browser_session(
        database_engine,
        user_id=user_id,
        client_address=None,
        user_agent=None,
        now=200,
        idle_ttl=25,
        absolute_ttl=30,
    )
    assert authenticate_browser_session(
        database_engine, absolute.secret, now=224, touch=True
    ) is not None
    assert authenticate_browser_session(
        database_engine, absolute.secret, now=231, touch=True
    ) is None
