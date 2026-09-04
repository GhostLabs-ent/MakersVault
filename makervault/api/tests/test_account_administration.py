from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from account_service import create_account, update_account
from authorization import Role
from identity_service import bootstrap_initial_administrator
from main import app, engine
from migrations import MIGRATIONS, run_migrations
from session_service import authenticate_browser_session, create_browser_session


ADMIN_PASSWORD = "test-only-password"


def _engine(path: Path):
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def _login(
    client: TestClient,
    username: str = "admin",
    password: str = ADMIN_PASSWORD,
) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    body = response.json()
    return body, {
        "Origin": "http://testserver",
        "X-CSRF-Token": body["csrf_token"],
    }


def test_schema15_to_schema16_adds_administration_audit_and_recovery_state(
    tmp_path: Path,
) -> None:
    database_engine = _engine(tmp_path / "gate11d.db")
    assert run_migrations(database_engine, MIGRATIONS[:15]) == 15
    user_id = str(uuid4())
    browser_id = str(uuid4())
    with database_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO useraccount("
            "id, username, username_normalized, display_name, password_hash, enabled, "
            "password_policy_version, password_change_required, role, created_at, updated_at) "
            "VALUES (?, 'Owner', 'owner', 'Owner', '$argon2id$v=19$fixture', 1, 1, 0, "
            "'administrator', '2026-09-03T00:00:00Z', '2026-09-03T00:00:00Z')",
            (user_id,),
        )
        connection.exec_driver_sql(
            "INSERT INTO browsersession("
            "id, user_id, secret_digest, created_at, last_seen_at, idle_expires_at, "
            "absolute_expires_at, idle_ttl_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (browser_id, user_id, "a" * 64, 1234, 1234, 2000, 3000, 766),
        )
    with database_engine.connect() as connection:
        user_before = connection.exec_driver_sql(
            "SELECT * FROM useraccount WHERE id = ?", (user_id,)
        ).fetchone()

    assert run_migrations(database_engine, MIGRATIONS[:16]) == 16
    assert run_migrations(database_engine, MIGRATIONS[:16]) == 16

    with database_engine.connect() as connection:
        user_after = connection.exec_driver_sql(
            "SELECT * FROM useraccount WHERE id = ?", (user_id,)
        ).fetchone()
        reauthenticated_at = connection.exec_driver_sql(
            "SELECT reauthenticated_at FROM browsersession WHERE id = ?",
            (browser_id,),
        ).scalar_one()
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert user_after == user_before
    assert reauthenticated_at == 1234
    assert {"auditevent", "recoverymarker"}.issubset(tables)


def test_last_enabled_administrator_is_protected_and_privilege_change_revokes_sessions(
    tmp_path: Path,
) -> None:
    database_engine = _engine(tmp_path / "last-admin.db")
    run_migrations(database_engine)
    owner = bootstrap_initial_administrator(
        database_engine,
        username="Owner",
        password="a sufficiently long owner password",
    )
    owner_session = create_browser_session(
        database_engine,
        user_id=owner.user_id,
        client_address=None,
        user_agent=None,
    )

    with pytest.raises(HTTPException, match="last enabled Administrator") as denied:
        update_account(database_engine, owner.user_id, enabled=False)
    assert denied.value.status_code == 409

    second = create_account(
        database_engine,
        username="Second Admin",
        display_name="Second Admin",
        password="another sufficiently long password",
        role=Role.ADMINISTRATOR,
    )
    updated = update_account(database_engine, owner.user_id, role=Role.MEMBER)
    assert updated.role == Role.MEMBER.value
    assert second.role == Role.ADMINISTRATOR.value
    assert authenticate_browser_session(database_engine, owner_session.secret) is None


def test_administrator_account_workflow_forces_password_change_and_enforces_recent_auth() -> None:
    suffix = uuid4().hex
    username = f"viewer-{suffix}"
    temporary_password = f"Temporary password {suffix}"
    replacement_password = f"Replacement password {suffix}"
    reset_password = f"Reset password {suffix}"
    created_id = None

    with TestClient(app) as administrator:
        _admin_body, admin_headers = _login(administrator)
        admin_session_id = administrator.get("/session").json()["session_id"]
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE browsersession SET reauthenticated_at = 0 WHERE id = ?",
                (admin_session_id,),
            )

        stale = administrator.post(
            "/users",
            headers=admin_headers,
            json={
                "username": username,
                "display_name": "Gate 11D Viewer",
                "password": temporary_password,
                "role": "viewer",
            },
        )
        assert stale.status_code == 403
        assert stale.json()["detail"] == "Recent password confirmation required"

        confirmed = administrator.post(
            "/session/reauthenticate",
            headers=admin_headers,
            json={"password": ADMIN_PASSWORD},
        )
        assert confirmed.status_code == 200

        created = administrator.post(
            "/users",
            headers=admin_headers,
            json={
                "username": username,
                "display_name": "Gate 11D Viewer",
                "password": temporary_password,
                "role": "viewer",
            },
        )
        assert created.status_code == 201
        created_id = created.json()["id"]
        assert created.json()["password_change_required"] is True
        listed = administrator.get("/users")
        assert listed.status_code == 200
        assert created_id in {row["id"] for row in listed.json()}
        updated = administrator.patch(
            f"/users/{created_id}",
            headers=admin_headers,
            json={"display_name": "Updated Gate 11D Viewer"},
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "Updated Gate 11D Viewer"

        owner_id = next(
            row["id"] for row in listed.json() if row["username"] == "admin"
        )
        protected = administrator.patch(
            f"/users/{owner_id}",
            headers=admin_headers,
            json={"enabled": False},
        )
        assert protected.status_code == 409

        try:
            with TestClient(app) as viewer:
                login_body, viewer_headers = _login(
                    viewer,
                    username=username,
                    password=temporary_password,
                )
                assert login_body["role"] == "viewer"
                assert login_body["password_change_required"] is True
                assert viewer.get("/assets").status_code == 403
                assert viewer.get("/session").status_code == 200

                changed = viewer.post(
                    "/account/password",
                    headers=viewer_headers,
                    json={"new_password": replacement_password},
                )
                assert changed.status_code == 200
                assert changed.json()["password_change_required"] is False
                assert viewer.get("/assets").status_code == 200

            with TestClient(app) as replacement_login:
                _body, _headers = _login(
                    replacement_login,
                    username=username,
                    password=replacement_password,
                )
                assert replacement_login.get("/assets").status_code == 200

                reset = administrator.post(
                    f"/users/{created_id}/password-reset",
                    headers=admin_headers,
                    json={"new_password": reset_password},
                )
                assert reset.status_code == 200
                assert reset.json()["password_change_required"] is True
                assert replacement_login.get("/session").status_code == 401

            with TestClient(app) as old_password:
                response = old_password.post(
                    "/login",
                    json={"username": username, "password": temporary_password},
                )
                assert response.status_code == 401

            with TestClient(app) as reset_login:
                reset_body, _reset_headers = _login(
                    reset_login,
                    username=username,
                    password=reset_password,
                )
                assert reset_body["password_change_required"] is True
        finally:
            if created_id:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "DELETE FROM browsersession WHERE user_id = ?", (created_id,)
                    )
                    connection.exec_driver_sql(
                        "DELETE FROM useraccount WHERE id = ?", (created_id,)
                    )


def test_non_administrator_cannot_list_or_administer_accounts() -> None:
    with TestClient(app) as client:
        _body, headers = _login(client)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE useraccount SET role = 'member' "
                "WHERE username_normalized = 'admin'"
            )
        try:
            assert client.get("/users").status_code == 403
            assert client.post(
                "/users",
                headers=headers,
                json={
                    "username": "denied-user",
                    "display_name": "Denied",
                    "password": "a sufficiently long denied password",
                    "role": "viewer",
                },
            ).status_code == 403
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE useraccount SET role = 'administrator' "
                    "WHERE username_normalized = 'admin'"
                )
