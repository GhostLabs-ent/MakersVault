import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select
from webauthn.helpers.structs import CredentialDeviceType

from audit_service import AuditContext
from authorization import Role
from identity_service import bootstrap_initial_administrator
from migrations import run_migrations
from main import app, engine
from models import (
    AuditEvent,
    AuthenticatorPolicy,
    UserAccount,
    WebAuthnChallenge,
    WebAuthnCredential,
)
from passkey_config import (
    PasskeyConfigurationError,
    load_passkey_config,
    validate_passkey_runtime,
)
from passkey_service import (
    begin_passkey_reauthentication,
    begin_passkey_registration,
    complete_passkey_reauthentication,
    complete_passkey_registration,
    list_passkeys,
    remove_passkey,
    rename_passkey,
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
    return AuditContext(
        correlation_id=str(uuid4()),
        actor=None,
        action=action,
        method="POST",
        route="/account/passkeys",
        permission="identity.manage_self",
        source_address="test",
    )


def _client_data(challenge: str, ceremony_type: str) -> str:
    encoded = json.dumps(
        {
            "type": ceremony_type,
            "challenge": challenge,
            "origin": "http://localhost",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def _credential(challenge: str, credential_id: bytes, ceremony_type: str) -> dict:
    encoded_id = base64.urlsafe_b64encode(credential_id).rstrip(b"=").decode("ascii")
    response = {
        "clientDataJSON": _client_data(challenge, ceremony_type),
    }
    if ceremony_type == "webauthn.create":
        response.update({"attestationObject": "AA", "transports": ["internal"]})
    else:
        response.update(
            {"authenticatorData": "AA", "signature": "AA", "userHandle": None}
        )
    return {
        "id": encoded_id,
        "rawId": encoded_id,
        "type": "public-key",
        "response": response,
    }


def _account_and_session(database_engine):
    identity = bootstrap_initial_administrator(
        database_engine,
        username="Owner",
        password="a sufficiently long owner password",
    )
    browser = create_browser_session(
        database_engine,
        user_id=identity.user_id,
        client_address=None,
        user_agent=None,
    )
    return identity, browser


def test_passkey_configuration_is_explicit_origin_bound_and_fail_closed(
    tmp_path: Path,
) -> None:
    disabled = load_passkey_config({"MAKERSVAULT_ENV": "production"})
    assert disabled.enabled is False

    configured = load_passkey_config(
        {
            "MAKERSVAULT_ENV": "production",
            "WEBAUTHN_RP_ID": "example.com",
            "WEBAUTHN_ORIGIN": "https://vault.example.com:443/",
        }
    )
    assert configured.enabled is True
    assert configured.origin == "https://vault.example.com"

    invalid_settings = (
        {
            "MAKERSVAULT_ENV": "production",
            "WEBAUTHN_RP_ID": "example.com",
        },
        {
            "MAKERSVAULT_ENV": "production",
            "WEBAUTHN_RP_ID": "192.168.1.2",
            "WEBAUTHN_ORIGIN": "https://192.168.1.2",
        },
        {
            "MAKERSVAULT_ENV": "production",
            "WEBAUTHN_RP_ID": "vault.local",
            "WEBAUTHN_ORIGIN": "https://vault.local",
        },
        {
            "MAKERSVAULT_ENV": "production",
            "WEBAUTHN_RP_ID": "example.com",
            "WEBAUTHN_ORIGIN": "http://example.com",
        },
        {
            "MAKERSVAULT_ENV": "production",
            "WEBAUTHN_RP_ID": "example.com",
            "WEBAUTHN_ORIGIN": "https://other.test",
        },
    )
    for settings in invalid_settings:
        with pytest.raises(PasskeyConfigurationError):
            load_passkey_config(settings)

    database_engine = _engine(tmp_path / "fail-closed.db")
    run_migrations(database_engine)
    identity = bootstrap_initial_administrator(
        database_engine,
        username="Owner",
        password="a sufficiently long owner password",
    )
    with database_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE useraccount SET mfa_enabled = 1 WHERE id = ?",
            (identity.user_id,),
        )
    with pytest.raises(PasskeyConfigurationError, match="Stored MFA state"):
        validate_passkey_runtime(
            database_engine, {"MAKERSVAULT_ENV": "production"}
        )


def test_registration_reauthentication_and_self_management_are_bound_and_audited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    database_engine = _engine(tmp_path / "passkeys.db")
    run_migrations(database_engine)
    identity, browser = _account_and_session(database_engine)
    now = int(time.time())

    options = begin_passkey_registration(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        password_recent=True,
        audit_context=_audit("passkey.registration.begin"),
        now=now,
    )
    challenge = options["challenge"]
    assert options["attestation"] == "none"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["timeout"] == 300000

    with Session(database_engine) as session:
        stored_challenge = session.exec(select(WebAuthnChallenge)).one()
        assert stored_challenge.challenge_digest != challenge
        assert challenge not in stored_challenge.challenge_digest

    first_challenge = challenge
    replacement_options = begin_passkey_registration(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        password_recent=True,
        now=now,
    )
    challenge = replacement_options["challenge"]
    assert challenge != first_challenge
    with Session(database_engine) as session:
        assert len(list(session.exec(select(WebAuthnChallenge)))) == 1
    with pytest.raises(HTTPException, match="could not be verified"):
        complete_passkey_registration(
            database_engine,
            user_id=identity.user_id,
            session_id=browser.id,
            label="Superseded",
            credential=_credential(
                first_challenge, b"superseded-id", "webauthn.create"
            ),
            now=now + 1,
        )

    credential_id = b"first-passkey-id"
    monkeypatch.setattr(
        "passkey_service.verify_registration_response",
        lambda **_kwargs: SimpleNamespace(
            user_verified=True,
            credential_id=credential_id,
            credential_public_key=b"public-cose-key",
            sign_count=2,
            credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
            credential_backed_up=False,
        ),
    )
    other_browser = create_browser_session(
        database_engine,
        user_id=identity.user_id,
        client_address=None,
        user_agent=None,
    )
    with pytest.raises(HTTPException, match="could not be verified"):
        complete_passkey_registration(
            database_engine,
            user_id=identity.user_id,
            session_id=other_browser.id,
            label="Wrong session",
            credential=_credential(challenge, credential_id, "webauthn.create"),
            now=now + 1,
        )
    registered = complete_passkey_registration(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        label="Laptop passkey",
        credential=_credential(challenge, credential_id, "webauthn.create"),
        audit_context=_audit("passkey.registration.complete"),
        now=now + 1,
    )
    record_id = registered["credential"]["id"]
    assert registered["mfa_enabled"] is True
    assert registered["credential_count"] == 1

    with pytest.raises(HTTPException, match="already used"):
        complete_passkey_registration(
            database_engine,
            user_id=identity.user_id,
            session_id=browser.id,
            label="Replay",
            credential=_credential(challenge, credential_id, "webauthn.create"),
            now=now + 2,
        )
    with pytest.raises(HTTPException, match="Recent passkey confirmation"):
        begin_passkey_registration(
            database_engine,
            user_id=identity.user_id,
            session_id=browser.id,
            password_recent=True,
            now=now + 2,
        )
    with pytest.raises(HTTPException, match="Recent passkey confirmation"):
        remove_passkey(
            database_engine,
            user_id=identity.user_id,
            session_id=browser.id,
            credential_record_id=record_id,
            password_recent=True,
            now=now + 2,
        )

    assertion_options = begin_passkey_reauthentication(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        password_recent=True,
        audit_context=_audit("passkey.reauthentication.begin"),
        now=now + 2,
    )
    assertion_challenge = assertion_options["challenge"]
    assert assertion_options["userVerification"] == "required"
    assert assertion_options["allowCredentials"][0]["id"] == base64.urlsafe_b64encode(
        credential_id
    ).rstrip(b"=").decode("ascii")
    monkeypatch.setattr(
        "passkey_service.verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(
            user_verified=True,
            credential_id=credential_id,
            new_sign_count=3,
            credential_device_type=CredentialDeviceType.MULTI_DEVICE,
            credential_backed_up=True,
        ),
    )
    reauthenticated = complete_passkey_reauthentication(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        credential=_credential(
            assertion_challenge, credential_id, "webauthn.get"
        ),
        audit_context=_audit("passkey.reauthentication.complete"),
        now=now + 3,
    )
    assert reauthenticated == {"reauthenticated_at": now + 3}

    second_options = begin_passkey_registration(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        password_recent=True,
        now=now + 4,
    )
    assert second_options["excludeCredentials"][0]["id"] == assertion_options[
        "allowCredentials"
    ][0]["id"]

    renamed = rename_passkey(
        database_engine,
        user_id=identity.user_id,
        credential_record_id=record_id,
        label="Phone-synced passkey",
        audit_context=_audit("passkey.credential.rename"),
    )
    assert renamed["label"] == "Phone-synced passkey"

    listing = list_passkeys(database_engine, user_id=identity.user_id)
    serialized_listing = json.dumps(listing)
    assert listing["available"] is True
    assert listing["mfa_enabled"] is True
    assert listing["credentials"][0]["backed_up"] is True
    assert "public-cose-key" not in serialized_listing
    assert base64.urlsafe_b64encode(credential_id).decode("ascii") not in serialized_listing

    removed = remove_passkey(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        credential_record_id=record_id,
        password_recent=True,
        audit_context=_audit("passkey.credential.remove"),
        now=now + 4,
    )
    assert removed == {"mfa_enabled": False, "credential_count": 0}

    with Session(database_engine) as session:
        events = list(session.exec(select(AuditEvent).order_by(AuditEvent.occurred_at)))
        actions = {event.action for event in events}
        assert {
            "passkey.registration.begin",
            "passkey.registration.complete",
            "passkey.reauthentication.begin",
            "passkey.reauthentication.complete",
            "passkey.credential.rename",
            "passkey.credential.remove",
        }.issubset(actions)
        encoded_events = json.dumps(
            [
                {
                    "action": event.action,
                    "object_id": event.object_id,
                    "details": event.details_json,
                }
                for event in events
            ]
        )
        assert "public-cose-key" not in encoded_events
        assert challenge not in encoded_events


def test_failed_verification_is_bounded_and_cross_account_management_is_hidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    database_engine = _engine(tmp_path / "passkey-denials.db")
    run_migrations(database_engine)
    identity, browser = _account_and_session(database_engine)
    now = int(time.time())
    options = begin_passkey_registration(
        database_engine,
        user_id=identity.user_id,
        session_id=browser.id,
        password_recent=True,
        now=now,
    )
    payload = _credential(options["challenge"], b"failed-id", "webauthn.create")
    monkeypatch.setattr(
        "passkey_service.verify_registration_response",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("secret verifier detail")),
    )
    for _ in range(5):
        with pytest.raises(HTTPException, match="could not be verified"):
            complete_passkey_registration(
                database_engine,
                user_id=identity.user_id,
                session_id=browser.id,
                label="Will fail",
                credential=payload,
                now=now + 1,
            )
    with Session(database_engine) as session:
        challenge_row = session.exec(select(WebAuthnChallenge)).one()
        assert challenge_row.attempt_count == 5

        other = UserAccount(
            username="Other",
            username_normalized="other",
            display_name="Other",
            password_hash="fixture",
            role=Role.VIEWER.value,
            created_at="2026-09-04T00:00:00Z",
            updated_at="2026-09-04T00:00:00Z",
        )
        session.add(other)
        session.flush()
        foreign = WebAuthnCredential(
            user_id=other.id,
            credential_id=base64.urlsafe_b64encode(b"foreign-id").rstrip(b"=").decode(),
            public_key=base64.urlsafe_b64encode(b"foreign-key").rstrip(b"=").decode(),
            device_type="single_device",
            label="Foreign",
            created_at="2026-09-04T00:00:00Z",
        )
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id

    with pytest.raises(HTTPException, match="Passkey not found") as hidden:
        rename_passkey(
            database_engine,
            user_id=identity.user_id,
            credential_record_id=foreign_id,
            label="Cross-account",
        )
    assert hidden.value.status_code == 404


def test_registration_options_failure_creates_no_challenge_or_success_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    database_engine = _engine(tmp_path / "options-failure.db")
    run_migrations(database_engine)
    identity, browser = _account_and_session(database_engine)
    monkeypatch.setattr(
        "passkey_service.generate_registration_options",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("generation failed")),
    )

    with pytest.raises(ValueError, match="generation failed"):
        begin_passkey_registration(
            database_engine,
            user_id=identity.user_id,
            session_id=browser.id,
            password_recent=True,
            audit_context=_audit("passkey.registration.begin"),
        )

    with Session(database_engine) as session:
        assert list(session.exec(select(WebAuthnChallenge))) == []
        assert list(
            session.exec(
                select(AuditEvent).where(
                    AuditEvent.action == "passkey.registration.begin"
                )
            )
        ) == []


def test_required_policy_prevents_last_credential_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    database_engine = _engine(tmp_path / "required-policy.db")
    run_migrations(database_engine)
    identity, browser = _account_and_session(database_engine)
    now = int(time.time())
    credential = WebAuthnCredential(
        user_id=identity.user_id,
        credential_id=base64.urlsafe_b64encode(b"required-id").rstrip(b"=").decode(),
        public_key=base64.urlsafe_b64encode(b"required-key").rstrip(b"=").decode(),
        device_type="single_device",
        label="Required",
        created_at="2026-09-04T00:00:00Z",
    )
    with Session(database_engine) as session:
        account = session.get(UserAccount, identity.user_id)
        account.mfa_enabled = True
        session.add(account)
        session.add(credential)
        policy = session.get(AuthenticatorPolicy, "global")
        policy.mode = "require_administrators"
        session.add(policy)
        session.add(
            WebAuthnChallenge(
                user_id=identity.user_id,
                purpose="reauthentication",
                challenge_digest="a" * 64,
                session_id=browser.id,
                rp_id="localhost",
                origin="http://localhost",
                created_at=now - 1,
                expires_at=now + 299,
                consumed_at=now,
            )
        )
        session.commit()
        credential_id = credential.id

    with pytest.raises(HTTPException, match="Required MFA policy") as denied:
        remove_passkey(
            database_engine,
            user_id=identity.user_id,
            session_id=browser.id,
            credential_record_id=credential_id,
            password_recent=True,
            now=now,
        )
    assert denied.value.status_code == 409


def test_passkey_self_service_routes_require_the_authenticated_owner_and_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _passkey_environment(monkeypatch)
    challenge_ids: list[str] = []
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
        listed = client.get("/account/passkeys")
        assert listed.status_code == 200
        assert listed.json()["available"] is True
        assert "credential_id" not in listed.text
        assert "public_key" not in listed.text

        missing_csrf = client.post("/account/passkeys/registration/options")
        assert missing_csrf.status_code == 403
        started = client.post(
            "/account/passkeys/registration/options", headers=headers
        )
        assert started.status_code == 200
        assert started.json()["rp"]["id"] == "localhost"
        assert started.headers["Cache-Control"] == "private, no-store"

        with Session(engine) as session:
            challenge_ids = list(
                session.exec(
                    select(WebAuthnChallenge.id).where(
                        WebAuthnChallenge.user_id
                        == select(UserAccount.id)
                        .where(UserAccount.username_normalized == "admin")
                        .scalar_subquery()
                    )
                )
            )
    with engine.begin() as connection:
        for challenge_id in challenge_ids:
            connection.exec_driver_sql(
                "DELETE FROM webauthnchallenge WHERE id = ?", (challenge_id,)
            )
        connection.exec_driver_sql(
            "DELETE FROM auditevent WHERE action LIKE 'passkey.%'"
        )
