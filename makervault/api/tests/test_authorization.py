from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from authorization import (
    AccessKind,
    Permission,
    ROUTE_AUTHORIZATION,
    Role,
    SYSTEM_SERVICE_ENTRY_POINTS,
    SystemService,
    permissions_for_role,
    run_system_service,
    validate_route_inventory,
)
from identity_service import bootstrap_initial_administrator
from main import app, engine
from migrations import MIGRATIONS, run_migrations
from session_service import authenticate_browser_session, create_browser_session


def _engine(path: Path):
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": "test-only-password"},
    )
    assert response.status_code == 200
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": response.json()["csrf_token"],
    }


def _set_admin_role(role: Role) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE useraccount SET role = ? WHERE username_normalized = 'admin'",
            (role.value,),
        )


def test_schema14_to_schema15_backfills_roles_without_changing_domain_state(
    tmp_path: Path,
) -> None:
    database_engine = _engine(tmp_path / "roles.db")
    assert run_migrations(database_engine, MIGRATIONS[:14]) == 14
    with database_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO useraccount("
            "id, username, username_normalized, display_name, password_hash, "
            "created_at, updated_at) VALUES ("
            "'owner-id', 'Owner', 'owner', 'Owner', '$argon2id$fixture', "
            "'now', 'now')"
        )
    with database_engine.connect() as connection:
        user_before = connection.exec_driver_sql(
            "SELECT id, username, password_hash, enabled FROM useraccount"
        ).fetchone()

    assert run_migrations(database_engine, MIGRATIONS[:15]) == 15
    assert run_migrations(database_engine, MIGRATIONS[:15]) == 15

    with database_engine.connect() as connection:
        user_after = connection.exec_driver_sql(
            "SELECT id, username, password_hash, enabled, role FROM useraccount"
        ).fetchone()
        columns = {
            str(row[1])
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(useraccount)"
            ).fetchall()
        }
    assert user_after[:4] == user_before
    assert user_after[4] == Role.ADMINISTRATOR.value
    assert "role" in columns

    with database_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO useraccount("
            "id, username, username_normalized, display_name, password_hash, "
            "created_at, updated_at) VALUES ("
            "'future-id', 'Future', 'future', 'Future', '$argon2id$fixture', "
            "'later', 'later')"
        )
    with database_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT role FROM useraccount WHERE id = 'future-id'"
        ).scalar_one() == Role.VIEWER.value

    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE useraccount SET role = 'owner' WHERE id = ?",
                (user_after[0],),
            )


def test_fixed_roles_map_to_stable_permissions() -> None:
    viewer = permissions_for_role(Role.VIEWER)
    member = permissions_for_role(Role.MEMBER)
    administrator = permissions_for_role(Role.ADMINISTRATOR)

    assert viewer == {
        Permission.VAULT_READ,
        Permission.CONTENT_DOWNLOAD,
        Permission.CONTENT_EXPORT,
        Permission.HANDOFF_CREATE,
        Permission.SESSION_MANAGE_SELF,
        Permission.IDENTITY_MANAGE_SELF,
    }
    assert viewer < member < administrator
    assert Permission.CONTENT_MANAGE in member
    assert Permission.TRASH_RESTORE in member
    assert Permission.SETTINGS_MANAGE not in member
    assert Permission.CONTENT_DELETE_PERMANENTLY not in member
    assert Permission.SETTINGS_MANAGE in administrator
    assert Permission.JOBS_MANAGE in administrator
    assert Permission.IDENTITY_MANAGE in administrator
    assert Permission.AUDIT_READ in administrator
    assert Permission.CONTENT_DELETE_PERMANENTLY in administrator
    assert Permission.TRASH_EMPTY in administrator

    with pytest.raises(HTTPException, match="Forbidden") as denied:
        permissions_for_role("owner")  # type: ignore[arg-type]
    assert denied.value.status_code == 403


def test_route_inventory_covers_every_role_decision_and_only_four_non_session_routes() -> None:
    assert {
        key
        for key, rule in ROUTE_AUTHORIZATION.items()
        if rule.kind is not AccessKind.SESSION
    } == {
        ("GET", "/health"),
        ("POST", "/login"),
        ("POST", "/login/passkey"),
        ("GET", "/handoff/redeem"),
    }
    assert all(
        rule.permission is not None
        for rule in ROUTE_AUTHORIZATION.values()
        if rule.kind is AccessKind.SESSION
    )
    assert ROUTE_AUTHORIZATION[("POST", "/trash/empty")].permission is Permission.TRASH_EMPTY
    assert ROUTE_AUTHORIZATION[("GET", "/settings/storage")].permission is Permission.SETTINGS_MANAGE
    assert ROUTE_AUTHORIZATION[("POST", "/settings/content-identity/backfill")].permission is Permission.JOBS_MANAGE
    assert ROUTE_AUTHORIZATION[("POST", "/users")].permission is Permission.IDENTITY_MANAGE
    assert ROUTE_AUTHORIZATION[("POST", "/users")].recent_reauthentication is True
    assert ROUTE_AUTHORIZATION[("PATCH", "/settings/authenticator-policy")].permission is Permission.SETTINGS_MANAGE
    assert ROUTE_AUTHORIZATION[("PATCH", "/settings/authenticator-policy")].recent_reauthentication is True
    assert ROUTE_AUTHORIZATION[("POST", "/users/{user_id}/mfa-reset")].permission is Permission.IDENTITY_MANAGE
    assert ROUTE_AUTHORIZATION[("POST", "/users/{user_id}/mfa-reset")].recent_reauthentication is True


def test_every_application_route_has_exactly_one_access_classification() -> None:
    validate_route_inventory(app)

    unclassified = FastAPI()

    @unclassified.get("/forgotten")
    def forgotten_route():
        return {"unsafe": True}

    with pytest.raises(RuntimeError, match="unclassified"):
        validate_route_inventory(unclassified)


def test_system_service_entry_points_are_explicit_and_fail_closed() -> None:
    assert set(SYSTEM_SERVICE_ENTRY_POINTS) == set(SystemService)
    assert run_system_service(SystemService.SESSION_CLEANUP, lambda: "ran") == "ran"

    invoked = False

    def operation() -> None:
        nonlocal invoked
        invoked = True

    with pytest.raises(RuntimeError, match="unclassified system service"):
        run_system_service("unknown", operation)  # type: ignore[arg-type]
    assert invoked is False


def test_session_principal_uses_the_current_persistent_role(tmp_path: Path) -> None:
    database_engine = _engine(tmp_path / "principal.db")
    run_migrations(database_engine)
    identity = bootstrap_initial_administrator(
        database_engine,
        username="Owner",
        password="a sufficiently long owner password",
    )
    created = create_browser_session(
        database_engine,
        user_id=identity.user_id,
        client_address=None,
        user_agent=None,
    )

    first = authenticate_browser_session(database_engine, created.secret)
    assert first is not None and first.role is Role.ADMINISTRATOR

    with database_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE useraccount SET role = 'viewer' WHERE id = ?",
            (identity.user_id,),
        )
    changed = authenticate_browser_session(database_engine, created.secret)
    assert changed is not None and changed.role is Role.VIEWER


def test_viewer_can_read_export_and_handoff_but_cannot_mutate() -> None:
    with TestClient(app) as client:
        headers = _login(client)
        machine_id = None
        machine_name = f"Archived viewer boundary {uuid4().hex}"
        try:
            machine_response = client.post(
                "/machines",
                json={
                    "name": machine_name,
                    "category": "other",
                },
                headers=headers,
            )
            assert machine_response.status_code == 201
            machine_id = machine_response.json()["id"]
            assert client.post(
                f"/machine/{machine_id}/archive",
                headers=headers,
            ).status_code == 200

            _set_admin_role(Role.VIEWER)
            session = client.get("/session")
            assert session.status_code == 200
            assert session.json()["role"] == Role.VIEWER.value
            assert Permission.CONTENT_MANAGE.value not in session.json()["permissions"]
            assert client.get("/assets").status_code == 200
            assert client.get("/file/missing/model.stl").status_code == 404
            assert client.post(
                "/download/zip",
                json={"asset_ids": ["missing"]},
                headers=headers,
            ).status_code == 404
            assert client.post(
                "/asset/missing/handoff",
                json={"tool": "slicer"},
                headers=headers,
            ).status_code == 404
            assert client.post(
                "/folders",
                json={"name": "Viewer must not create"},
                headers=headers,
            ).status_code == 403
            assert client.get("/trash").status_code == 403
            assert client.get("/settings/storage").status_code == 403
            archived = client.get(
                "/machines",
                params={"include_archived": "true", "q": machine_name},
            )
            assert archived.status_code == 200
            assert archived.json() == []
            assert client.get(f"/machine/{machine_id}").status_code == 404
        finally:
            _set_admin_role(Role.ADMINISTRATOR)
            if machine_id:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "DELETE FROM machineprofile WHERE id = ?",
                        (machine_id,),
                    )


def test_member_can_manage_shared_content_but_not_privileged_operations() -> None:
    with TestClient(app) as client:
        headers = _login(client)
        created_id = None
        try:
            _set_admin_role(Role.MEMBER)
            created = client.post(
                "/folders",
                json={"name": "Member folder"},
                headers=headers,
            )
            assert created.status_code == 200
            created_id = created.json()["id"]
            assert client.get("/trash").status_code == 200
            assert client.get("/settings/storage").status_code == 403
            assert client.post(
                "/trash/empty",
                json={"confirmation": "EMPTY TRASH"},
                headers=headers,
            ).status_code == 403
        finally:
            if created_id:
                client.delete(f"/folder/{created_id}", headers=headers)
            _set_admin_role(Role.ADMINISTRATOR)


def test_administrator_retains_privileged_settings_access() -> None:
    with TestClient(app) as client:
        _login(client)
        _set_admin_role(Role.ADMINISTRATOR)
        assert client.get("/settings/storage").status_code == 200
        assert client.get("/docs").status_code == 404
