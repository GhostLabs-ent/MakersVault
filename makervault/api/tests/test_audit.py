import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select

import account_service
import audit_service
from account_service import create_account
from audit_service import (
    AuditActor,
    AuditContext,
    audit_action_for_route,
    list_audit_events,
    record_audit_event,
)
from authorization import ROUTE_AUTHORIZATION, Role
from main import app, engine
from migrations import run_migrations
from models import AuditEvent, Folder, UserAccount


ADMIN_PASSWORD = "test-only-password"


def _engine(path: Path):
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": response.json()["csrf_token"],
    }


def test_every_mutation_and_sensitive_read_has_a_stable_audit_action() -> None:
    sensitive_reads = {
        ("GET", "/users"),
        ("GET", "/sessions"),
        ("GET", "/audit"),
        ("GET", "/folder/{folder_id}/download"),
        ("GET", "/asset/{asset_id}/revisions/export"),
        ("GET", "/project/{project_id}/export"),
        ("GET", "/handoff/redeem"),
    }
    for (method, path), rule in ROUTE_AUTHORIZATION.items():
        action = audit_action_for_route(method, path, rule)
        if method in {"POST", "PUT", "PATCH", "DELETE"} or (method, path) in sensitive_reads:
            assert action
            assert len(action) <= 128

    assert audit_action_for_route(
        "POST", "/users", ROUTE_AUTHORIZATION[("POST", "/users")]
    ) == "identity.account.create"
    assert audit_action_for_route(
        "GET", "/audit", ROUTE_AUTHORIZATION[("GET", "/audit")]
    ) == "audit.read"


def test_audit_storage_is_bounded_paginated_and_rejects_secret_detail_keys(
    tmp_path: Path,
) -> None:
    database_engine = _engine(tmp_path / "audit.db")
    run_migrations(database_engine)
    context = AuditContext(
        correlation_id=str(uuid4()),
        actor=AuditActor("user-id", "Owner", Role.ADMINISTRATOR),
        action="identity.account.update",
        method="PATCH",
        route="/users/{user_id}",
        permission="identity.manage",
        source_address="127.0.0.1",
        object_type="user",
        object_id="target-id",
    )

    with pytest.raises(ValueError, match="not allowed"):
        record_audit_event(
            database_engine,
            context,
            result="success",
            status_code=200,
            details={"password": "must-never-be-stored"},
        )

    for index in range(3):
        record_audit_event(
            database_engine,
            context,
            result="success",
            status_code=200,
            details={
                "changed_fields": ["role"],
                "revoked_sessions": index,
            },
        )
    page = list_audit_events(database_engine, limit=2)
    assert len(page.items) == 2
    assert page.has_more is True
    assert page.next_cursor
    older = list_audit_events(database_engine, limit=200, cursor=page.next_cursor)
    assert len(older.items) == 1
    with pytest.raises(ValueError, match="between 1 and 200"):
        list_audit_events(database_engine, limit=201)
    with pytest.raises(ValueError, match="cursor is invalid"):
        list_audit_events(database_engine, cursor="not-a-valid-cursor")

    serialized = json.dumps([event.model_dump() for event in page.items])
    assert "must-never-be-stored" not in serialized


def test_login_content_mutation_and_audit_reads_are_recorded_without_bodies_or_queries() -> None:
    marker = uuid4().hex
    submitted_username = f"missing-{marker}"
    submitted_password = f"password-secret-{marker}"
    folder_name = f"folder-body-secret-{marker}"
    folder_id = None

    with TestClient(app) as client:
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM auditevent")

        denied_login = client.post(
            "/login?query-secret=" + marker,
            json={"username": submitted_username, "password": submitted_password},
        )
        assert denied_login.status_code == 401
        assert denied_login.headers["X-Correlation-ID"]

        headers = _login(client)
        created = client.post(
            "/folders?another-query-secret=" + marker,
            headers=headers,
            json={"name": folder_name},
        )
        assert created.status_code == 200
        folder_id = created.json()["id"]
        mutation_correlation = created.headers["X-Correlation-ID"]

        first_page = client.get("/audit", params={"limit": 2})
        assert first_page.status_code == 200
        assert len(first_page.json()["items"]) <= 2
        assert first_page.json()["limit"] == 2

        with engine.connect() as connection:
            mutation = connection.exec_driver_sql(
                "SELECT action, result, route, correlation_id FROM auditevent "
                "WHERE correlation_id = ?",
                (mutation_correlation,),
            ).one()
            audit_reads = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM auditevent WHERE action = 'audit.read'"
            ).scalar_one()
            persisted = json.dumps(
                [tuple(row) for row in connection.exec_driver_sql(
                    "SELECT actor_username, action, object_type, object_id, method, "
                    "route, permission, source_address, details_json FROM auditevent"
                ).fetchall()]
            )
        assert mutation == (
            "content.mutate",
            "success",
            "/folders",
            mutation_correlation,
        )
        assert audit_reads >= 1
        assert submitted_username not in persisted
        assert submitted_password not in persisted
        assert folder_name not in persisted
        assert marker not in persisted

    if folder_id:
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM folder WHERE id = ?", (folder_id,))


def test_audit_query_is_administrator_only_and_denial_is_recorded() -> None:
    with TestClient(app) as client:
        headers = _login(client)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE useraccount SET role = 'member' "
                "WHERE username_normalized = 'admin'"
            )
        try:
            denied = client.get("/audit")
            assert denied.status_code == 403
            correlation_id = denied.headers["X-Correlation-ID"]
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE useraccount SET role = 'administrator' "
                    "WHERE username_normalized = 'admin'"
                )

        allowed = client.get("/audit", params={"limit": 200})
        assert allowed.status_code == 200
        assert any(
            item["correlation_id"] == correlation_id
            and item["action"] == "audit.read"
            and item["result"] == "denied"
            and item["actor_role"] == "member"
            for item in allowed.json()["items"]
        )


def test_identity_audit_failure_rolls_back_the_identity_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_engine = _engine(tmp_path / "identity-atomic.db")
    run_migrations(database_engine)
    username = f"atomic-{uuid4().hex}"
    context = AuditContext(
        correlation_id=str(uuid4()),
        actor=AuditActor("owner-id", "Owner", Role.ADMINISTRATOR),
        action="identity.account.create",
        method="POST",
        route="/users",
        permission="identity.manage",
        source_address="127.0.0.1",
        object_type="user",
    )

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(account_service, "append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        create_account(
            database_engine,
            username=username,
            display_name="Atomic User",
            password="a sufficiently long atomic password",
            role=Role.VIEWER,
            audit_context=context,
        )

    with Session(database_engine) as session:
        assert session.exec(
            select(UserAccount).where(UserAccount.username_normalized == username)
        ).first() is None
        assert session.exec(select(AuditEvent)).first() is None


def test_post_commit_audit_failure_is_reported_without_claiming_domain_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder_name = f"audit-failure-{uuid4().hex}"
    folder_id = None
    with TestClient(app) as client:
        headers = _login(client)

        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("simulated post-commit audit failure")

        monkeypatch.setattr(audit_service, "record_audit_event", fail_audit)
        response = client.post(
            "/folders",
            headers=headers,
            json={"name": folder_name},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "Operation completed but audit recording failed"

        with Session(engine) as session:
            folder = session.exec(select(Folder).where(Folder.name == folder_name)).first()
            assert folder is not None
            folder_id = folder.id

    if folder_id:
        with engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM folder WHERE id = ?", (folder_id,))
