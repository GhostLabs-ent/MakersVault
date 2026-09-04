import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select
from webauthn.helpers.structs import CredentialDeviceType

from auth import DEVELOPMENT_PENDING_LOGIN_COOKIE
from identity_service import bootstrap_initial_administrator
from main import app, engine, login_limiter
from migrations import run_migrations
from models import (
    AuditEvent,
    BrowserSession,
    UserAccount,
    WebAuthnChallenge,
    WebAuthnCredential,
)
from passkey_service import begin_passkey_login, complete_passkey_login
from session_service import DEVELOPMENT_SESSION_COOKIE


def _engine(path: Path):
    return create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )


def _passkey_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBAUTHN_RP_ID", "localhost")
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "http://localhost")
    monkeypatch.setenv("WEBAUTHN_RP_NAME", "MakersVault Test")


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client_data(challenge: str) -> str:
    return _encoded(
        json.dumps(
            {
                "type": "webauthn.get",
                "challenge": challenge,
                "origin": "http://localhost",
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _credential(challenge: str, credential_id: bytes) -> dict:
    encoded_id = _encoded(credential_id)
    return {
        "id": encoded_id,
        "rawId": encoded_id,
        "type": "public-key",
        "response": {
            "clientDataJSON": _client_data(challenge),
            "authenticatorData": "AA",
            "signature": "AA",
            "userHandle": None,
        },
    }


def _verified(credential_id: bytes, sign_count: int = 7):
    return SimpleNamespace(
        user_verified=True,
        credential_id=credential_id,
        new_sign_count=sign_count,
        credential_device_type=CredentialDeviceType.MULTI_DEVICE,
        credential_backed_up=True,
    )


def _enable_passkey(database_engine, user_id: str, credential_id: bytes) -> str:
    with Session(database_engine) as session:
        account = session.get(UserAccount, user_id)
        assert account is not None
        account.mfa_enabled = True
        account.last_login_at = None
        session.add(account)
        row = WebAuthnCredential(
            user_id=user_id,
            credential_id=_encoded(credential_id),
            public_key=_encoded(b"test-public-key"),
            sign_count=0,
            transports_json='["internal"]',
            device_type="single_device",
            backed_up=False,
            label="Test passkey",
            created_at="2026-09-04T00:00:00Z",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def test_pending_login_is_digest_only_bounded_and_one_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _passkey_environment(monkeypatch)
    database_engine = _engine(tmp_path / "passkey-login.db")
    run_migrations(database_engine)
    identity = bootstrap_initial_administrator(
        database_engine,
        username="Owner",
        password="a sufficiently long owner password",
    )
    credential_id = b"owner-passkey"
    _enable_passkey(database_engine, identity.user_id, credential_id)

    pending = begin_passkey_login(database_engine, user_id=identity.user_id, now=1_000)
    assert pending.public_key["userVerification"] == "required"
    assert pending.public_key["allowCredentials"][0]["id"] == _encoded(credential_id)
    with Session(database_engine) as session:
        challenge = session.exec(select(WebAuthnChallenge)).one()
        assert challenge.transaction_digest
        assert pending.token not in challenge.transaction_digest
        assert challenge.session_id is None
        assert session.exec(select(BrowserSession)).all() == []
        assert session.get(UserAccount, identity.user_id).last_login_at is None

    invalid = _credential(pending.public_key["challenge"], b"other-passkey")
    for _ in range(5):
        with pytest.raises(HTTPException, match="Invalid or expired login") as denied:
            complete_passkey_login(
                database_engine,
                token=pending.token,
                credential=invalid,
                now=1_001,
            )
        assert denied.value.status_code == 401
    with Session(database_engine) as session:
        assert session.exec(select(WebAuthnChallenge)).one().attempt_count == 5
        assert session.exec(select(BrowserSession)).all() == []

    second = begin_passkey_login(database_engine, user_id=identity.user_id, now=1_010)
    monkeypatch.setattr(
        "passkey_service.verify_authentication_response",
        lambda **_kwargs: _verified(credential_id),
    )
    completed = complete_passkey_login(
        database_engine,
        token=second.token,
        credential=_credential(second.public_key["challenge"], credential_id),
        now=1_011,
    )
    assert completed.user_id == identity.user_id
    assert completed.mfa_enabled is True
    with pytest.raises(HTTPException, match="Invalid or expired login") as replay:
        complete_passkey_login(
            database_engine,
            token=second.token,
            credential=_credential(second.public_key["challenge"], credential_id),
            now=1_012,
        )
    assert replay.value.status_code == 401
    with Session(database_engine) as session:
        account = session.get(UserAccount, identity.user_id)
        stored_id = session.exec(select(WebAuthnCredential.id)).one()
        stored = session.get(WebAuthnCredential, stored_id)
        assert account is not None and account.last_login_at is not None
        assert stored is not None and stored.sign_count == 7
        assert session.exec(select(BrowserSession)).all() == []

    expired = begin_passkey_login(database_engine, user_id=identity.user_id, now=2_000)
    with pytest.raises(HTTPException, match="Invalid or expired login") as timeout:
        complete_passkey_login(
            database_engine,
            token=expired.token,
            credential=_credential(expired.public_key["challenge"], credential_id),
            now=2_300,
        )
    assert timeout.value.status_code == 401

    for offset in range(11):
        begin_passkey_login(
            database_engine, user_id=identity.user_id, now=3_000 + offset
        )
    with Session(database_engine) as session:
        outstanding = list(
            session.exec(
                select(WebAuthnChallenge).where(
                    WebAuthnChallenge.purpose == "authentication",
                    WebAuthnChallenge.consumed_at.is_(None),
                )
            )
        )
        assert len(outstanding) <= 10


def test_mfa_login_issues_session_only_after_assertion_and_strengthens_recent_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    monkeypatch.setattr(
        "auth.configured_browser_origins", lambda: {"http://localhost"}
    )
    credential_id = b"global-admin-passkey"
    account_id = ""
    session_id = ""
    old_mfa = False
    old_last_login = None
    old_password_change_required = False

    try:
        with TestClient(app) as client:
            with Session(engine) as session:
                account = session.exec(
                    select(UserAccount).where(
                        UserAccount.username_normalized == "admin"
                    )
                ).one()
                account_id = account.id
                old_mfa = account.mfa_enabled
                old_last_login = account.last_login_at
                old_password_change_required = account.password_change_required
            _enable_passkey(engine, account_id, credential_id)

            password = client.post(
                "/login",
                headers={"Origin": "http://localhost"},
                json={"username": "admin", "password": "test-only-password"},
            )
            assert password.status_code == 200
            assert password.json()["authenticated"] is False
            assert password.json()["mfa_required"] is True
            assert client.cookies.get(DEVELOPMENT_SESSION_COOKIE) is None
            pending_token = client.cookies.get(DEVELOPMENT_PENDING_LOGIN_COOKIE)
            assert pending_token
            pending_header = next(
                value
                for value in password.headers.get_list("set-cookie")
                if value.startswith(f"{DEVELOPMENT_PENDING_LOGIN_COOKIE}=")
            )
            assert "HttpOnly" in pending_header
            assert "SameSite=strict" in pending_header
            max_age = int(pending_header.split("Max-Age=")[1].split(";")[0])
            assert 1 <= max_age <= 300
            with Session(engine) as session:
                account = session.get(UserAccount, account_id)
                assert account is not None and account.last_login_at is None

            assertion = _credential(
                password.json()["public_key"]["challenge"], credential_id
            )
            wrong_origin = client.post(
                "/login/passkey",
                headers={"Origin": "https://attacker.example"},
                json={"credential": assertion},
            )
            assert wrong_origin.status_code == 403
            assert client.cookies.get(DEVELOPMENT_SESSION_COOKIE) is None

            monkeypatch.setattr(
                "passkey_service.verify_authentication_response",
                lambda **_kwargs: _verified(credential_id),
            )
            authenticated = client.post(
                "/login/passkey",
                headers={"Origin": "http://localhost"},
                json={"credential": assertion},
            )
            assert authenticated.status_code == 200
            assert authenticated.json()["authenticated"] is True
            assert authenticated.json()["mfa_enabled"] is True
            assert client.cookies.get(DEVELOPMENT_SESSION_COOKIE)
            assert client.cookies.get(DEVELOPMENT_PENDING_LOGIN_COOKIE) is None
            csrf = authenticated.json()["csrf_token"]
            session_id = client.get("/session").json()["session_id"]
            with Session(engine) as session:
                events = list(
                    session.exec(
                        select(AuditEvent).where(
                            AuditEvent.action.in_(
                                {
                                    "passkey.authentication.begin",
                                    "passkey.authentication.complete",
                                    "identity.login.passkey",
                                }
                            )
                        )
                    )
                )
                assert {
                    "passkey.authentication.begin",
                    "passkey.authentication.complete",
                    "identity.login.passkey",
                }.issubset({event.action for event in events})
                audit_text = " ".join(event.details_json for event in events)
                assert pending_token not in audit_text
                assert _encoded(credential_id) not in audit_text
                assert password.json()["public_key"]["challenge"] not in audit_text

            headers = {
                "Origin": "http://localhost",
                "X-CSRF-Token": csrf,
            }
            password_reauth = client.post(
                "/session/reauthenticate",
                headers=headers,
                json={"password": "test-only-password"},
            )
            assert password_reauth.status_code == 200
            assert password_reauth.json()["mfa_required"] is True
            assert client.delete("/sessions/missing", headers=headers).status_code == 403

            options = client.post(
                "/account/passkeys/reauthentication/options", headers=headers
            )
            assert options.status_code == 200
            passkey_reauth = client.post(
                "/account/passkeys/reauthentication/verify",
                headers=headers,
                json={
                    "credential": _credential(
                        options.json()["challenge"], credential_id
                    )
                },
            )
            assert passkey_reauth.status_code == 200
            assert client.delete("/sessions/missing", headers=headers).status_code == 404

            with Session(engine) as session:
                account = session.get(UserAccount, account_id)
                assert account is not None
                account.password_change_required = True
                session.add(account)
                session.commit()
            forced_change_options = client.post(
                "/account/passkeys/reauthentication/options", headers=headers
            )
            assert forced_change_options.status_code == 200
            forced_change_verify = client.post(
                "/account/passkeys/reauthentication/verify",
                headers=headers,
                json={
                    "credential": _credential(
                        forced_change_options.json()["challenge"], credential_id
                    )
                },
            )
            assert forced_change_verify.status_code == 200
            with Session(engine) as session:
                account = session.get(UserAccount, account_id)
                assert account is not None
                account.password_change_required = False
                session.add(account)
                session.commit()

        with TestClient(app) as replay:
            replay.cookies.set(DEVELOPMENT_PENDING_LOGIN_COOKIE, pending_token)
            for _ in range(3):
                denied = replay.post(
                    "/login/passkey",
                    headers={"Origin": "http://localhost"},
                    json={"credential": assertion},
                )
                assert denied.status_code == 401
            limited = replay.post(
                "/login/passkey",
                headers={"Origin": "http://localhost"},
                json={"credential": assertion},
            )
            assert limited.status_code == 429
            assert int(limited.headers["Retry-After"]) >= 1
            assert replay.cookies.get(DEVELOPMENT_SESSION_COOKIE) is None
    finally:
        login_limiter.clear()
        with engine.begin() as connection:
            if account_id:
                connection.exec_driver_sql(
                    "DELETE FROM webauthnchallenge WHERE user_id = ?", (account_id,)
                )
                connection.exec_driver_sql(
                    "DELETE FROM webauthncredential WHERE user_id = ?", (account_id,)
                )
            if session_id:
                connection.exec_driver_sql(
                    "DELETE FROM browsersession WHERE id = ?", (session_id,)
                )
            if account_id:
                connection.exec_driver_sql(
                    "UPDATE useraccount SET mfa_enabled = ?, last_login_at = ?, "
                    "password_change_required = ? WHERE id = ?",
                    (
                        int(old_mfa),
                        old_last_login,
                        int(old_password_change_required),
                        account_id,
                    ),
                )
