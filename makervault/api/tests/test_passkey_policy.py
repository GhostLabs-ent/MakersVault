import base64
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select

from account_service import create_account, reset_account_password, update_account
from audit_service import AuditContext
from authorization import Role
from identity_service import bootstrap_initial_administrator
from migrations import run_migrations
from main import app, engine as application_engine
from models import (
    AuditEvent,
    AuthenticatorPolicy,
    BrowserSession,
    UserAccount,
    WebAuthnChallenge,
    WebAuthnCredential,
)
from passkey_service import (
    get_authenticator_policy,
    reset_account_passkeys,
    update_authenticator_policy,
)
from session_service import create_browser_session


def _engine(path: Path):
    return create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )


def _passkey_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBAUTHN_RP_ID", "localhost")
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "http://localhost")
    monkeypatch.setenv("WEBAUTHN_RP_NAME", "MakersVault Test")


def _audit(action: str) -> AuditContext:
    is_policy = action == "passkey.policy.update"
    return AuditContext(
        correlation_id=str(uuid4()),
        actor=None,
        action=action,
        method="PATCH" if is_policy else "POST",
        route=(
            "/settings/authenticator-policy"
            if is_policy
            else "/users/{user_id}/mfa-reset"
        ),
        permission="settings.manage" if is_policy else "identity.manage",
        source_address="test",
    )


def _enroll(database_engine, user_id: str, suffix: str) -> None:
    with Session(database_engine) as session:
        account = session.get(UserAccount, user_id)
        assert account is not None
        account.mfa_enabled = True
        session.add(account)
        session.add(
            WebAuthnCredential(
                user_id=user_id,
                credential_id=base64.urlsafe_b64encode(
                    f"credential-{suffix}".encode()
                ).rstrip(b"=").decode(),
                public_key=base64.urlsafe_b64encode(
                    f"public-key-{suffix}".encode()
                ).rstrip(b"=").decode(),
                sign_count=0,
                transports_json='["internal"]',
                device_type="single_device",
                backed_up=False,
                label=f"Passkey {suffix}",
                created_at="2026-09-04T00:00:00Z",
            )
        )
        session.commit()


def _recent_passkey_proof(
    database_engine,
    *,
    user_id: str,
    session_id: str,
    suffix: str,
    now: int,
) -> None:
    with Session(database_engine) as session:
        session.add(
            WebAuthnChallenge(
                user_id=user_id,
                purpose="reauthentication",
                challenge_digest=(suffix * 64)[:64],
                session_id=session_id,
                rp_id="localhost",
                origin="http://localhost",
                created_at=now - 1,
                expires_at=now + 299,
                consumed_at=now,
            )
        )
        session.commit()


def test_policy_staging_account_invariants_and_administrator_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    database_engine = _engine(tmp_path / "passkey-policy.db")
    run_migrations(database_engine)
    administrator = bootstrap_initial_administrator(
        database_engine,
        username="Owner",
        password="a sufficiently long owner password",
    )
    member = create_account(
        database_engine,
        username="Member",
        display_name="Member",
        password="a sufficiently long member password",
        role=Role.MEMBER,
    )
    browser = create_browser_session(
        database_engine,
        user_id=administrator.user_id,
        client_address=None,
        user_agent=None,
        now=1_000,
    )
    member_browser = create_browser_session(
        database_engine,
        user_id=member.id,
        client_address=None,
        user_agent=None,
        now=1_000,
    )
    _enroll(database_engine, administrator.user_id, "owner")
    _recent_passkey_proof(
        database_engine,
        user_id=administrator.user_id,
        session_id=browser.id,
        suffix="a",
        now=1_001,
    )

    initial = get_authenticator_policy(database_engine)
    assert initial["available"] is True
    assert initial["mode"] == "optional"
    assert initial["require_administrators_blockers"] == []
    assert initial["require_all_blockers"] == ["Member"]

    administrators = update_authenticator_policy(
        database_engine,
        actor_user_id=administrator.user_id,
        session_id=browser.id,
        password_recent=True,
        mode="require_administrators",
        audit_context=_audit("passkey.policy.update"),
        now=1_002,
    )
    assert administrators["mode"] == "require_administrators"

    with pytest.raises(HTTPException, match="requires this enabled account"):
        create_account(
            database_engine,
            username="SecondOwner",
            display_name="Second owner",
            password="a sufficiently long second owner password",
            role=Role.ADMINISTRATOR,
        )
    viewer = create_account(
        database_engine,
        username="Viewer",
        display_name="Viewer",
        password="a sufficiently long viewer password",
        role=Role.VIEWER,
    )
    with pytest.raises(HTTPException, match="enroll a passkey first"):
        update_account(database_engine, viewer.id, role=Role.ADMINISTRATOR)

    with pytest.raises(HTTPException, match="Every enabled targeted account"):
        update_authenticator_policy(
            database_engine,
            actor_user_id=administrator.user_id,
            session_id=browser.id,
            password_recent=True,
            mode="require_all",
            now=1_003,
        )

    _enroll(database_engine, member.id, "member")
    _enroll(database_engine, viewer.id, "viewer")
    required = update_authenticator_policy(
        database_engine,
        actor_user_id=administrator.user_id,
        session_id=browser.id,
        password_recent=True,
        mode="require_all",
        now=1_004,
    )
    assert required["mode"] == "require_all"
    assert required["require_all_blockers"] == []
    with pytest.raises(HTTPException, match="enroll a passkey first"):
        create_account(
            database_engine,
            username="NotYetEnrolled",
            display_name="Not yet enrolled",
            password="a sufficiently long new account password",
            role=Role.VIEWER,
        )

    reset_account_password(
        database_engine,
        member.id,
        password="a replacement member password",
    )
    with Session(database_engine) as session:
        assert session.exec(
            select(WebAuthnCredential.id).where(
                WebAuthnCredential.user_id == member.id
            )
        ).first() is not None
    with pytest.raises(HTTPException, match="policy prevents resetting"):
        reset_account_passkeys(
            database_engine,
            actor_user_id=administrator.user_id,
            target_user_id=member.id,
            session_id=browser.id,
            password_recent=True,
            now=1_005,
        )

    update_authenticator_policy(
        database_engine,
        actor_user_id=administrator.user_id,
        session_id=browser.id,
        password_recent=True,
        mode="optional",
        now=1_006,
    )
    member_browser = create_browser_session(
        database_engine,
        user_id=member.id,
        client_address=None,
        user_agent=None,
        now=1_006,
    )
    _recent_passkey_proof(
        database_engine,
        user_id=member.id,
        session_id=member_browser.id,
        suffix="b",
        now=1_006,
    )
    with Session(database_engine) as session:
        password_hash = session.get(UserAccount, member.id).password_hash
    reset = reset_account_passkeys(
        database_engine,
        actor_user_id=administrator.user_id,
        target_user_id=member.id,
        session_id=browser.id,
        password_recent=True,
        audit_context=_audit("passkey.administrator.reset"),
        now=1_007,
    )
    assert reset == {
        "mfa_enabled": False,
        "removed_credentials": 1,
        "revoked_sessions": 1,
    }
    with Session(database_engine) as session:
        target = session.get(UserAccount, member.id)
        target_session = session.get(BrowserSession, member_browser.id)
        policy = session.get(AuthenticatorPolicy, "global")
        assert target is not None and target.mfa_enabled is False
        assert target.password_change_required is True
        assert target.password_hash == password_hash
        assert target_session is not None and target_session.revoked_at == 1_007
        assert session.get(BrowserSession, browser.id).revoked_at is None
        assert policy is not None and policy.mode == "optional"
        assert session.exec(
            select(WebAuthnCredential).where(WebAuthnCredential.user_id == member.id)
        ).all() == []
        assert session.exec(
            select(WebAuthnChallenge).where(WebAuthnChallenge.user_id == member.id)
        ).all() == []
        reset_event = session.exec(
            select(AuditEvent).where(
                AuditEvent.action == "passkey.administrator.reset"
            )
        ).one()
        assert reset_event.object_id == member.id
        assert "credential-" not in reset_event.details_json

    with pytest.raises(HTTPException, match="your own passkey settings"):
        reset_account_passkeys(
            database_engine,
            actor_user_id=administrator.user_id,
            target_user_id=administrator.user_id,
            session_id=browser.id,
            password_recent=True,
            now=1_008,
        )


def test_policy_change_requires_current_actor_strength(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    database_engine = _engine(tmp_path / "passkey-policy-strength.db")
    run_migrations(database_engine)
    administrator = bootstrap_initial_administrator(
        database_engine,
        username="Owner",
        password="a sufficiently long owner password",
    )
    browser = create_browser_session(
        database_engine,
        user_id=administrator.user_id,
        client_address=None,
        user_agent=None,
        now=2_000,
    )
    with pytest.raises(HTTPException, match="Recent password confirmation"):
        update_authenticator_policy(
            database_engine,
            actor_user_id=administrator.user_id,
            session_id=browser.id,
            password_recent=False,
            mode="optional",
            now=2_001,
        )
    _enroll(database_engine, administrator.user_id, "owner-strength")
    with pytest.raises(HTTPException, match="Recent passkey confirmation"):
        update_authenticator_policy(
            database_engine,
            actor_user_id=administrator.user_id,
            session_id=browser.id,
            password_recent=True,
            mode="optional",
            now=2_002,
        )


def test_policy_http_surface_is_administrator_only_and_recent_auth_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    with TestClient(app) as client:
        login = client.post(
            "/login",
            json={"username": "admin", "password": "test-only-password"},
        )
        assert login.status_code == 200
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        policy = client.get("/settings/authenticator-policy")
        assert policy.status_code == 200
        assert policy.json()["available"] is True
        assert policy.json()["mode"] == "optional"
        session_id = client.get("/session").json()["session_id"]
        with application_engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE browsersession SET reauthenticated_at = 0 WHERE id = ?",
                (session_id,),
            )
        assert client.patch(
            "/settings/authenticator-policy",
            headers=headers,
            json={"mode": "optional"},
        ).status_code == 403
        confirmed = client.post(
            "/session/reauthenticate",
            headers=headers,
            json={"password": "test-only-password"},
        )
        assert confirmed.status_code == 200
        updated = client.patch(
            "/settings/authenticator-policy",
            headers=headers,
            json={"mode": "optional"},
        )
        assert updated.status_code == 200
        assert updated.json()["mode"] == "optional"
        accounts = client.get("/users")
        assert accounts.status_code == 200
        assert accounts.json()[0]["mfa_enabled"] is False
        try:
            for role in (Role.VIEWER, Role.MEMBER):
                with application_engine.begin() as connection:
                    connection.exec_driver_sql(
                        "UPDATE useraccount SET role = ? WHERE username_normalized = 'admin'",
                        (role.value,),
                    )
                assert client.get("/settings/authenticator-policy").status_code == 403
                assert client.patch(
                    "/settings/authenticator-policy",
                    headers=headers,
                    json={"mode": "optional"},
                ).status_code == 403
                assert client.post(
                    "/users/missing/mfa-reset", headers=headers,
                ).status_code == 403
        finally:
            with application_engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE useraccount SET role = 'administrator' "
                    "WHERE username_normalized = 'admin'"
                )

    with application_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE authenticatorpolicy SET mode = 'optional', "
            "updated_by_user_id = NULL WHERE id = 'global'"
        )
