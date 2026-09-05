"""Origin-bound passkey enrollment and account self-management."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from audit_service import AuditContext, append_audit_event
from authorization import Role
from models import (
    AuthenticatorPolicy,
    BrowserSession,
    UserAccount,
    WebAuthnChallenge,
    WebAuthnCredential,
)
from passkey_config import (
    PasskeyConfigurationError,
    load_passkey_config,
    require_passkey_config,
)
from security_config import load_security_config


CHALLENGE_BYTES = 32
CHALLENGE_TTL_SECONDS = 300
CHALLENGE_ATTEMPT_LIMIT = 5
CHALLENGE_CLEANUP_LIMIT = 200
MAX_CREDENTIALS_PER_ACCOUNT = 10
MAX_PENDING_LOGINS_PER_ACCOUNT = 10
AUTHENTICATOR_POLICY_MODES = frozenset(
    {"optional", "require_administrators", "require_all"}
)
MAX_CEREMONY_RESPONSE_BYTES = 128 * 1024
MAX_CLIENT_DATA_BYTES = 16 * 1024
MAX_CREDENTIAL_ID_BYTES = 1024
MAX_PUBLIC_KEY_BYTES = 4096
LABEL_MAX_LENGTH = 128
CEREMONY_TIMEOUT_MS = CHALLENGE_TTL_SECONDS * 1000
_TRANSPORTS = frozenset(item.value for item in AuthenticatorTransport)
AUTHENTICATOR_MUTATION_LOCK = threading.RLock()


@dataclass(frozen=True)
class PendingPasskeyLogin:
    token: str
    public_key: dict[str, object]
    expires_at: int


@dataclass(frozen=True)
class CompletedPasskeyLogin:
    user_id: str
    username: str
    role: Role
    password_change_required: bool
    mfa_enabled: bool


def _now(value: Optional[int] = None) -> int:
    return int(time.time()) if value is None else int(value)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: object, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum * 2 or "=" in value:
        raise ValueError("invalid base64url value")
    try:
        raw = base64.b64decode(
            value.encode("ascii") + b"=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("invalid base64url value") from exc
    if len(raw) > maximum or _b64url_encode(raw) != value:
        raise ValueError("invalid base64url value")
    return raw


def _challenge_digest(challenge: bytes) -> str:
    key = load_security_config().secret.encode("utf-8")
    return hmac.new(
        key,
        b"makersvault-webauthn-challenge\0" + challenge,
        hashlib.sha256,
    ).hexdigest()


def _transaction_digest(token: str) -> str:
    key = load_security_config().secret.encode("utf-8")
    return hmac.new(
        key,
        b"makersvault-webauthn-login-transaction\0" + token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _configured():
    try:
        return require_passkey_config()
    except PasskeyConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _clean_label(value: str) -> str:
    label = str(value or "").strip()
    if (
        not label
        or len(label) > LABEL_MAX_LENGTH
        or any(not character.isprintable() for character in label)
    ):
        raise HTTPException(
            status_code=422,
            detail="Passkey label must contain between 1 and 128 printable characters",
        )
    return label


def _bounded_credential_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HTTPException(status_code=422, detail="Invalid passkey response")
    try:
        payload = json.loads(json.dumps(dict(value), separators=(",", ":")))
        size = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    except (RecursionError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid passkey response") from exc
    if size > MAX_CEREMONY_RESPONSE_BYTES:
        raise HTTPException(status_code=413, detail="Passkey response is too large")
    return payload


def _challenge_from_credential(credential: Mapping[str, Any]) -> bytes:
    try:
        response = credential["response"]
        if not isinstance(response, dict):
            raise ValueError("response is not an object")
        client_data = _b64url_decode(
            response["clientDataJSON"], maximum=MAX_CLIENT_DATA_BYTES
        )
        parsed = json.loads(client_data)
        if not isinstance(parsed, dict):
            raise ValueError("client data is not an object")
        return _b64url_decode(parsed["challenge"], maximum=128)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail="Passkey ceremony could not be verified"
        ) from exc


def _credential_id_from_response(credential: Mapping[str, Any]) -> tuple[str, bytes]:
    try:
        raw = _b64url_decode(credential.get("id"), maximum=MAX_CREDENTIAL_ID_BYTES)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Passkey ceremony could not be verified"
        ) from exc
    return _b64url_encode(raw), raw


def _stored_bytes(value: str, *, maximum: int) -> bytes:
    try:
        return _b64url_decode(value, maximum=maximum)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Stored passkey state is invalid") from exc


def _enum_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    return str(candidate)


def _submitted_transports(credential: Mapping[str, Any]) -> list[str]:
    response = credential.get("response")
    values = response.get("transports", []) if isinstance(response, dict) else []
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > len(_TRANSPORTS):
        raise HTTPException(status_code=422, detail="Invalid authenticator transports")
    normalized = sorted({str(value) for value in values})
    if any(value not in _TRANSPORTS for value in normalized):
        raise HTTPException(status_code=422, detail="Invalid authenticator transports")
    return normalized


def _transport_enums(value: str) -> list[AuthenticatorTransport]:
    try:
        decoded = json.loads(value)
        if not isinstance(decoded, list):
            return []
        return [AuthenticatorTransport(item) for item in decoded if item in _TRANSPORTS]
    except (json.JSONDecodeError, ValueError, TypeError):
        return []


def _descriptor(row: WebAuthnCredential) -> PublicKeyCredentialDescriptor:
    return PublicKeyCredentialDescriptor(
        id=_stored_bytes(row.credential_id, maximum=MAX_CREDENTIAL_ID_BYTES),
        transports=_transport_enums(row.transports_json),
    )


def _require_account(session: Session, user_id: str) -> UserAccount:
    account = session.get(UserAccount, user_id)
    if account is None or not account.enabled:
        raise HTTPException(status_code=403, detail="Account is unavailable")
    return account


def _require_active_session(session: Session, user_id: str, session_id: str, now: int) -> None:
    browser_session = session.get(BrowserSession, session_id)
    if (
        browser_session is None
        or browser_session.user_id != user_id
        or browser_session.revoked_at is not None
        or now >= browser_session.idle_expires_at
        or now >= browser_session.absolute_expires_at
    ):
        raise HTTPException(status_code=401, detail="Active browser session required")


def _cleanup_challenges(session: Session, now: int) -> None:
    rows = list(
        session.exec(
            select(WebAuthnChallenge)
            .where(
                WebAuthnChallenge.expires_at <= now,
                or_(
                    WebAuthnChallenge.consumed_at.is_(None),
                    WebAuthnChallenge.consumed_at
                    <= now - CHALLENGE_TTL_SECONDS,
                ),
            )
            .order_by(WebAuthnChallenge.expires_at, WebAuthnChallenge.id)
            .limit(CHALLENGE_CLEANUP_LIMIT)
        )
    )
    for row in rows:
        session.delete(row)


def _supersede_pending_challenges(
    session: Session,
    *,
    user_id: str,
    session_id: str,
    purpose: str,
) -> None:
    rows = list(
        session.exec(
            select(WebAuthnChallenge).where(
                WebAuthnChallenge.user_id == user_id,
                WebAuthnChallenge.session_id == session_id,
                WebAuthnChallenge.purpose == purpose,
                WebAuthnChallenge.consumed_at.is_(None),
            )
        )
    )
    for row in rows:
        session.delete(row)


def _challenge_row(
    session: Session,
    *,
    challenge: bytes,
    purpose: str,
    user_id: str,
    session_id: str,
    rp_id: str,
    origin: str,
    now: int,
) -> WebAuthnChallenge:
    row = session.exec(
        select(WebAuthnChallenge).where(
            WebAuthnChallenge.challenge_digest == _challenge_digest(challenge)
        )
    ).first()
    if (
        row is None
        or row.purpose != purpose
        or row.user_id != user_id
        or row.session_id != session_id
        or row.rp_id != rp_id
        or row.origin != origin
    ):
        raise HTTPException(status_code=400, detail="Passkey ceremony could not be verified")
    if row.consumed_at is not None:
        raise HTTPException(status_code=409, detail="Passkey ceremony was already used")
    if row.expires_at <= now or row.attempt_count >= CHALLENGE_ATTEMPT_LIMIT:
        raise HTTPException(status_code=400, detail="Passkey ceremony has expired")
    return row


def _pending_login_row(
    session: Session,
    *,
    token: str,
    rp_id: str,
    origin: str,
    now: int,
) -> WebAuthnChallenge:
    if not token or len(token) > 512:
        raise HTTPException(status_code=401, detail="Invalid or expired login")
    row = session.exec(
        select(WebAuthnChallenge).where(
            WebAuthnChallenge.transaction_digest == _transaction_digest(token)
        )
    ).first()
    if (
        row is None
        or row.purpose != "authentication"
        or row.session_id is not None
        or row.rp_id != rp_id
        or row.origin != origin
        or row.consumed_at is not None
        or row.expires_at <= now
        or row.attempt_count >= CHALLENGE_ATTEMPT_LIMIT
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired login")
    return row


def _record_failed_attempt(engine: Engine, challenge_id: str) -> None:
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        row = session.get(WebAuthnChallenge, challenge_id)
        if row is not None and row.consumed_at is None:
            row.attempt_count = min(CHALLENGE_ATTEMPT_LIMIT, row.attempt_count + 1)
            session.add(row)
            session.commit()


def _limit_pending_logins(session: Session, *, user_id: str) -> None:
    rows = list(
        session.exec(
            select(WebAuthnChallenge)
            .where(
                WebAuthnChallenge.user_id == user_id,
                WebAuthnChallenge.purpose == "authentication",
                WebAuthnChallenge.consumed_at.is_(None),
            )
            .order_by(WebAuthnChallenge.created_at, WebAuthnChallenge.id)
        )
    )
    remove_count = max(0, len(rows) - MAX_PENDING_LOGINS_PER_ACCOUNT + 1)
    for row in rows[:remove_count]:
        session.delete(row)


def _has_recent_passkey_proof(
    session: Session,
    *,
    user_id: str,
    session_id: str,
    rp_id: str,
    origin: str,
    now: int,
) -> bool:
    return session.exec(
        select(WebAuthnChallenge.id).where(
            WebAuthnChallenge.user_id == user_id,
            WebAuthnChallenge.session_id == session_id,
            WebAuthnChallenge.purpose == "reauthentication",
            WebAuthnChallenge.rp_id == rp_id,
            WebAuthnChallenge.origin == origin,
            WebAuthnChallenge.consumed_at.is_not(None),
            WebAuthnChallenge.consumed_at >= now - CHALLENGE_TTL_SECONDS,
            WebAuthnChallenge.consumed_at <= now,
        ).limit(1)
    ).first() is not None


def has_recent_passkey_reauthentication(
    engine: Engine,
    *,
    user_id: str,
    session_id: str,
    origin: Optional[str] = None,
    now: Optional[int] = None,
) -> bool:
    config = _configured()
    if origin is not None and origin != config.origin:
        return False
    with Session(engine) as session:
        return _has_recent_passkey_proof(
            session,
            user_id=user_id,
            session_id=session_id,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=_now(now),
        )


def _require_current_strength(
    session: Session,
    account: UserAccount,
    session_id: str,
    *,
    password_recent: bool,
    rp_id: str,
    origin: str,
    now: int,
) -> None:
    if not password_recent:
        raise HTTPException(status_code=403, detail="Recent password confirmation required")
    if account.mfa_enabled and not _has_recent_passkey_proof(
        session,
        user_id=account.id,
        session_id=session_id,
        rp_id=rp_id,
        origin=origin,
        now=now,
    ):
        raise HTTPException(status_code=403, detail="Recent passkey confirmation required")


def _policy_requires_account(session: Session, account: UserAccount) -> bool:
    policy = session.get(AuthenticatorPolicy, "global")
    mode = policy.mode if policy is not None else "optional"
    return mode == "require_all" or (
        mode == "require_administrators" and account.role == Role.ADMINISTRATOR.value
    )


def account_satisfies_authenticator_policy_candidate(
    session: Session,
    *,
    account_id: Optional[str],
    role: Role,
    enabled: bool,
) -> None:
    """Reject account creation/authority changes that would violate MFA policy."""
    policy = session.get(AuthenticatorPolicy, "global")
    mode = policy.mode if policy is not None else "optional"
    targeted = bool(enabled) and (
        mode == "require_all"
        or mode == "require_administrators" and role is Role.ADMINISTRATOR
    )
    if not targeted:
        return
    enrolled = False
    if account_id:
        account = session.get(UserAccount, account_id)
        enrolled = bool(account and account.mfa_enabled) and session.exec(
            select(WebAuthnCredential.id).where(
                WebAuthnCredential.user_id == account_id
            ).limit(1)
        ).first() is not None
    if not enrolled:
        raise HTTPException(
            status_code=409,
            detail="Authenticator policy requires this enabled account to enroll a passkey first",
        )


def _authenticator_policy_status(session: Session) -> dict[str, object]:
    policy = session.get(AuthenticatorPolicy, "global")
    if policy is None:
        raise HTTPException(status_code=500, detail="Authenticator policy is unavailable")
    credentials = set(session.exec(select(WebAuthnCredential.user_id)))
    accounts = list(
        session.exec(
            select(UserAccount)
            .where(UserAccount.enabled.is_(True))
            .order_by(UserAccount.username_normalized, UserAccount.id)
        )
    )
    unenrolled = [
        account
        for account in accounts
        if not account.mfa_enabled or account.id not in credentials
    ]
    return {
        "mode": policy.mode,
        "require_administrators_blockers": [
            account.username
            for account in unenrolled
            if account.role == Role.ADMINISTRATOR.value
        ],
        "require_all_blockers": [account.username for account in unenrolled],
        "updated_at": policy.updated_at,
    }


def get_authenticator_policy(engine: Engine) -> dict[str, object]:
    try:
        available = load_passkey_config().enabled
    except PasskeyConfigurationError:
        available = False
    with Session(engine) as session:
        return {
            "available": available,
            **_authenticator_policy_status(session),
        }


def update_authenticator_policy(
    engine: Engine,
    *,
    actor_user_id: str,
    session_id: str,
    password_recent: bool,
    mode: str,
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> dict[str, object]:
    config = _configured()
    if mode not in AUTHENTICATOR_POLICY_MODES:
        raise HTTPException(status_code=422, detail="Invalid authenticator policy")
    current = _now(now)
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        actor = _require_account(session, actor_user_id)
        if actor.role != Role.ADMINISTRATOR.value:
            raise HTTPException(status_code=403, detail="Administrator access required")
        _require_active_session(session, actor_user_id, session_id, current)
        _require_current_strength(
            session,
            actor,
            session_id,
            password_recent=password_recent,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        status = _authenticator_policy_status(session)
        blockers_key = (
            "require_administrators_blockers"
            if mode == "require_administrators"
            else "require_all_blockers"
        )
        blockers = [] if mode == "optional" else list(status[blockers_key])
        if blockers:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Every enabled targeted account must enroll before this policy can be enabled: "
                    + ", ".join(blockers)
                ),
            )
        policy = session.get(AuthenticatorPolicy, "global")
        if policy is None:
            raise HTTPException(status_code=500, detail="Authenticator policy is unavailable")
        policy.mode = mode
        policy.updated_at = _timestamp()
        policy.updated_by_user_id = actor_user_id
        session.add(policy)
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("authenticator_policy", "global"),
                result="success",
                status_code=200,
                details={"changed_fields": ["mode"]},
            )
        session.commit()
        return {
            "available": True,
            **_authenticator_policy_status(session),
        }


def reset_account_passkeys(
    engine: Engine,
    *,
    actor_user_id: str,
    target_user_id: str,
    session_id: str,
    password_recent: bool,
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> dict[str, object]:
    config = _configured()
    current = _now(now)
    if actor_user_id == target_user_id:
        raise HTTPException(
            status_code=409,
            detail="Use your own passkey settings to remove your credentials",
        )
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        actor = _require_account(session, actor_user_id)
        if actor.role != Role.ADMINISTRATOR.value:
            raise HTTPException(status_code=403, detail="Administrator access required")
        _require_active_session(session, actor_user_id, session_id, current)
        _require_current_strength(
            session,
            actor,
            session_id,
            password_recent=password_recent,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        target = session.get(UserAccount, target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Account not found")
        if target.enabled and _policy_requires_account(session, target):
            raise HTTPException(
                status_code=409,
                detail="Required authenticator policy prevents resetting this account",
            )
        credentials = list(
            session.exec(
                select(WebAuthnCredential).where(
                    WebAuthnCredential.user_id == target_user_id
                )
            )
        )
        if not target.mfa_enabled and not credentials:
            raise HTTPException(status_code=409, detail="Account has no passkey MFA to reset")
        challenges = list(
            session.exec(
                select(WebAuthnChallenge).where(
                    WebAuthnChallenge.user_id == target_user_id
                )
            )
        )
        browser_sessions = list(
            session.exec(
                select(BrowserSession).where(
                    BrowserSession.user_id == target_user_id,
                    BrowserSession.revoked_at.is_(None),
                )
            )
        )
        for row in credentials:
            session.delete(row)
        for row in challenges:
            session.delete(row)
        for row in browser_sessions:
            row.revoked_at = current
            session.add(row)
        target.mfa_enabled = False
        target.updated_at = _timestamp()
        session.add(target)
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", target_user_id),
                result="success",
                status_code=200,
                details={
                    "removed_credentials": len(credentials),
                    "revoked_challenges": len(challenges),
                    "revoked_sessions": len(browser_sessions),
                },
            )
        session.commit()
        return {
            "mfa_enabled": False,
            "removed_credentials": len(credentials),
            "revoked_sessions": len(browser_sessions),
        }


def _credential_out(row: WebAuthnCredential) -> dict[str, object]:
    return {
        "id": row.id,
        "label": row.label,
        "transports": json.loads(row.transports_json),
        "device_type": row.device_type,
        "backed_up": row.backed_up,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
    }


def begin_passkey_login(
    engine: Engine,
    *,
    user_id: str,
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> PendingPasskeyLogin:
    config = _configured()
    current = _now(now)
    challenge = secrets.token_bytes(CHALLENGE_BYTES)
    token = secrets.token_urlsafe(32)
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        account = _require_account(session, user_id)
        if not account.mfa_enabled:
            raise HTTPException(status_code=409, detail="Passkey MFA is not enabled")
        credentials = list(
            session.exec(
                select(WebAuthnCredential)
                .where(WebAuthnCredential.user_id == user_id)
                .order_by(WebAuthnCredential.created_at, WebAuthnCredential.id)
            )
        )
        if not credentials:
            raise HTTPException(
                status_code=503,
                detail="MFA account has no usable registered passkey",
            )
        options = generate_authentication_options(
            rp_id=config.rp_id or "",
            challenge=challenge,
            timeout=CEREMONY_TIMEOUT_MS,
            allow_credentials=[_descriptor(row) for row in credentials],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        public_key = json.loads(options_to_json(options))
        _cleanup_challenges(session, current)
        _limit_pending_logins(session, user_id=user_id)
        session.add(
            WebAuthnChallenge(
                user_id=user_id,
                purpose="authentication",
                challenge_digest=_challenge_digest(challenge),
                transaction_digest=_transaction_digest(token),
                rp_id=config.rp_id or "",
                origin=config.origin or "",
                created_at=current,
                expires_at=current + CHALLENGE_TTL_SECONDS,
            )
        )
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", user_id),
                result="success",
                status_code=200,
            )
        session.commit()
    return PendingPasskeyLogin(
        token=token,
        public_key=public_key,
        expires_at=current + CHALLENGE_TTL_SECONDS,
    )


def complete_passkey_login(
    engine: Engine,
    *,
    token: str,
    credential: Mapping[str, Any],
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> CompletedPasskeyLogin:
    config = _configured()
    current = _now(now)
    with Session(engine) as session:
        pending = _pending_login_row(
            session,
            token=token,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        challenge_id = pending.id
        user_id = pending.user_id
    try:
        payload = _bounded_credential_payload(credential)
        challenge = _challenge_from_credential(payload)
        credential_id, response_credential_id = _credential_id_from_response(payload)
    except HTTPException as exc:
        _record_failed_attempt(engine, challenge_id)
        if exc.status_code == 413:
            raise
        raise HTTPException(status_code=401, detail="Invalid or expired login") from exc

    with Session(engine) as session:
        pending = _pending_login_row(
            session,
            token=token,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        if pending.challenge_digest != _challenge_digest(challenge):
            stored = None
        else:
            stored = session.exec(
                select(WebAuthnCredential).where(
                    WebAuthnCredential.user_id == pending.user_id,
                    WebAuthnCredential.credential_id == credential_id,
                )
            ).first()
        if stored is None:
            stored_id = None
            public_key = b""
            current_sign_count = 0
        else:
            stored_id = stored.id
            public_key = _stored_bytes(
                stored.public_key, maximum=MAX_PUBLIC_KEY_BYTES
            )
            current_sign_count = stored.sign_count
    if stored_id is None:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(status_code=401, detail="Invalid or expired login")

    try:
        verified = verify_authentication_response(
            credential=payload,
            expected_challenge=challenge,
            expected_rp_id=config.rp_id or "",
            expected_origin=config.origin or "",
            credential_public_key=public_key,
            credential_current_sign_count=current_sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(
            status_code=401, detail="Invalid or expired login"
        ) from exc
    if not verified.user_verified or verified.credential_id != response_credential_id:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(status_code=401, detail="Invalid or expired login")

    timestamp = _timestamp()
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        pending = _pending_login_row(
            session,
            token=token,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        if (
            pending.id != challenge_id
            or pending.user_id != user_id
            or pending.challenge_digest != _challenge_digest(challenge)
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired login")
        account = _require_account(session, user_id)
        stored = session.get(WebAuthnCredential, stored_id)
        if (
            not account.mfa_enabled
            or stored is None
            or stored.user_id != user_id
            or stored.sign_count != current_sign_count
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired login")
        try:
            role = Role(account.role)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired login") from exc
        pending.consumed_at = current
        stored.sign_count = max(stored.sign_count, int(verified.new_sign_count))
        stored.device_type = _enum_value(verified.credential_device_type)
        stored.backed_up = bool(verified.credential_backed_up)
        stored.last_used_at = timestamp
        account.last_login_at = timestamp
        account.updated_at = timestamp
        session.add(pending)
        session.add(stored)
        session.add(account)
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", user_id),
                result="success",
                status_code=200,
            )
        session.commit()
        return CompletedPasskeyLogin(
            user_id=account.id,
            username=account.username,
            role=role,
            password_change_required=account.password_change_required,
            mfa_enabled=True,
        )


def list_passkeys(engine: Engine, *, user_id: str) -> dict[str, object]:
    try:
        available = load_passkey_config().enabled
    except PasskeyConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    with Session(engine) as session:
        account = _require_account(session, user_id)
        rows = list(
            session.exec(
                select(WebAuthnCredential)
                .where(WebAuthnCredential.user_id == user_id)
                .order_by(WebAuthnCredential.created_at, WebAuthnCredential.id)
            )
        )
        return {
            "available": available,
            "mfa_enabled": account.mfa_enabled,
            "credentials": [_credential_out(row) for row in rows],
        }


def begin_passkey_registration(
    engine: Engine,
    *,
    user_id: str,
    session_id: str,
    password_recent: bool,
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> dict[str, object]:
    config = _configured()
    current = _now(now)
    challenge = secrets.token_bytes(CHALLENGE_BYTES)
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        account = _require_account(session, user_id)
        _require_active_session(session, user_id, session_id, current)
        _require_current_strength(
            session,
            account,
            session_id,
            password_recent=password_recent,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        credentials = list(
            session.exec(
                select(WebAuthnCredential)
                .where(WebAuthnCredential.user_id == user_id)
                .order_by(WebAuthnCredential.created_at, WebAuthnCredential.id)
            )
        )
        if len(credentials) >= MAX_CREDENTIALS_PER_ACCOUNT:
            raise HTTPException(status_code=409, detail="Passkey limit reached")
        username = account.username
        display_name = account.display_name
        excluded_credentials = [_descriptor(row) for row in credentials]
        options = generate_registration_options(
            rp_id=config.rp_id or "",
            rp_name=config.rp_name,
            user_id=uuid.UUID(user_id).bytes,
            user_name=username,
            user_display_name=display_name,
            challenge=challenge,
            timeout=CEREMONY_TIMEOUT_MS,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.DISCOURAGED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=excluded_credentials,
        )
        response = json.loads(options_to_json(options))
        _cleanup_challenges(session, current)
        _supersede_pending_challenges(
            session,
            user_id=user_id,
            session_id=session_id,
            purpose="registration",
        )
        session.add(
            WebAuthnChallenge(
                user_id=user_id,
                purpose="registration",
                challenge_digest=_challenge_digest(challenge),
                session_id=session_id,
                rp_id=config.rp_id or "",
                origin=config.origin or "",
                created_at=current,
                expires_at=current + CHALLENGE_TTL_SECONDS,
            )
        )
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", user_id),
                result="success",
                status_code=200,
            )
        session.commit()
    return response


def complete_passkey_registration(
    engine: Engine,
    *,
    user_id: str,
    session_id: str,
    label: str,
    credential: Mapping[str, Any],
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> dict[str, object]:
    config = _configured()
    current = _now(now)
    cleaned_label = _clean_label(label)
    payload = _bounded_credential_payload(credential)
    challenge = _challenge_from_credential(payload)
    transports = _submitted_transports(payload)
    with Session(engine) as session:
        row = _challenge_row(
            session,
            challenge=challenge,
            purpose="registration",
            user_id=user_id,
            session_id=session_id,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        challenge_id = row.id
    try:
        verified = verify_registration_response(
            credential=payload,
            expected_challenge=challenge,
            expected_rp_id=config.rp_id or "",
            expected_origin=config.origin or "",
            require_user_presence=True,
            require_user_verification=True,
        )
    except Exception as exc:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(
            status_code=400, detail="Passkey ceremony could not be verified"
        ) from exc
    if not verified.user_verified:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(
            status_code=400, detail="Passkey ceremony could not be verified"
        )
    credential_id = _b64url_encode(verified.credential_id)
    public_key = _b64url_encode(verified.credential_public_key)
    if (
        not credential_id
        or len(verified.credential_id) > MAX_CREDENTIAL_ID_BYTES
        or not public_key
        or len(verified.credential_public_key) > MAX_PUBLIC_KEY_BYTES
    ):
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(status_code=400, detail="Passkey response is invalid")
    timestamp = _timestamp()
    created = WebAuthnCredential(
        user_id=user_id,
        credential_id=credential_id,
        public_key=public_key,
        sign_count=max(0, int(verified.sign_count)),
        transports_json=json.dumps(transports, separators=(",", ":")),
        device_type=_enum_value(verified.credential_device_type),
        backed_up=bool(verified.credential_backed_up),
        label=cleaned_label,
        created_at=timestamp,
    )
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        account = _require_account(session, user_id)
        _require_active_session(session, user_id, session_id, current)
        challenge_row = _challenge_row(
            session,
            challenge=challenge,
            purpose="registration",
            user_id=user_id,
            session_id=session_id,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        count = len(
            list(
                session.exec(
                    select(WebAuthnCredential.id).where(
                        WebAuthnCredential.user_id == user_id
                    )
                )
            )
        )
        if count >= MAX_CREDENTIALS_PER_ACCOUNT:
            raise HTTPException(status_code=409, detail="Passkey limit reached")
        if account.mfa_enabled and not _has_recent_passkey_proof(
            session,
            user_id=user_id,
            session_id=session_id,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        ):
            raise HTTPException(
                status_code=403, detail="Recent passkey confirmation required"
            )
        challenge_row.consumed_at = current
        account.mfa_enabled = True
        account.updated_at = timestamp
        session.add(challenge_row)
        session.add(account)
        session.add(created)
        try:
            session.flush()
            if audit_context is not None:
                append_audit_event(
                    session,
                    audit_context.for_object("user", user_id),
                    result="success",
                    status_code=201,
                )
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="Passkey is already registered") from exc
        session.refresh(created)
        return {
            "mfa_enabled": True,
            "credential_count": count + 1,
            "credential": _credential_out(created),
        }


def begin_passkey_reauthentication(
    engine: Engine,
    *,
    user_id: str,
    session_id: str,
    password_recent: bool,
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> dict[str, object]:
    config = _configured()
    current = _now(now)
    challenge = secrets.token_bytes(CHALLENGE_BYTES)
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        account = _require_account(session, user_id)
        _require_active_session(session, user_id, session_id, current)
        if not password_recent:
            raise HTTPException(status_code=403, detail="Recent password confirmation required")
        credentials = list(
            session.exec(
                select(WebAuthnCredential)
                .where(WebAuthnCredential.user_id == user_id)
                .order_by(WebAuthnCredential.created_at, WebAuthnCredential.id)
            )
        )
        if not account.mfa_enabled or not credentials:
            raise HTTPException(status_code=409, detail="Passkey MFA is not enabled")
        allowed_credentials = [_descriptor(row) for row in credentials]
        options = generate_authentication_options(
            rp_id=config.rp_id or "",
            challenge=challenge,
            timeout=CEREMONY_TIMEOUT_MS,
            allow_credentials=allowed_credentials,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        response = json.loads(options_to_json(options))
        _cleanup_challenges(session, current)
        _supersede_pending_challenges(
            session,
            user_id=user_id,
            session_id=session_id,
            purpose="reauthentication",
        )
        session.add(
            WebAuthnChallenge(
                user_id=user_id,
                purpose="reauthentication",
                challenge_digest=_challenge_digest(challenge),
                session_id=session_id,
                rp_id=config.rp_id or "",
                origin=config.origin or "",
                created_at=current,
                expires_at=current + CHALLENGE_TTL_SECONDS,
            )
        )
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", user_id),
                result="success",
                status_code=200,
            )
        session.commit()
    return response


def complete_passkey_reauthentication(
    engine: Engine,
    *,
    user_id: str,
    session_id: str,
    credential: Mapping[str, Any],
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> dict[str, int]:
    config = _configured()
    current = _now(now)
    payload = _bounded_credential_payload(credential)
    challenge = _challenge_from_credential(payload)
    credential_id, response_credential_id = _credential_id_from_response(payload)
    with Session(engine) as session:
        challenge_row = _challenge_row(
            session,
            challenge=challenge,
            purpose="reauthentication",
            user_id=user_id,
            session_id=session_id,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        challenge_id = challenge_row.id
        stored = session.exec(
            select(WebAuthnCredential).where(
                WebAuthnCredential.user_id == user_id,
                WebAuthnCredential.credential_id == credential_id,
            )
        ).first()
        if stored is None:
            stored_id = None
            public_key = b""
            current_sign_count = 0
        else:
            stored_id = stored.id
            public_key = _stored_bytes(stored.public_key, maximum=MAX_PUBLIC_KEY_BYTES)
            current_sign_count = stored.sign_count
    if stored_id is None:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(
            status_code=400, detail="Passkey ceremony could not be verified"
        )
    try:
        verified = verify_authentication_response(
            credential=payload,
            expected_challenge=challenge,
            expected_rp_id=config.rp_id or "",
            expected_origin=config.origin or "",
            credential_public_key=public_key,
            credential_current_sign_count=current_sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(
            status_code=400, detail="Passkey ceremony could not be verified"
        ) from exc
    if not verified.user_verified or verified.credential_id != response_credential_id:
        _record_failed_attempt(engine, challenge_id)
        raise HTTPException(
            status_code=400, detail="Passkey ceremony could not be verified"
        )
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        _require_account(session, user_id)
        _require_active_session(session, user_id, session_id, current)
        challenge_row = _challenge_row(
            session,
            challenge=challenge,
            purpose="reauthentication",
            user_id=user_id,
            session_id=session_id,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        stored = session.get(WebAuthnCredential, stored_id)
        if stored is None or stored.user_id != user_id or stored.sign_count != current_sign_count:
            raise HTTPException(status_code=409, detail="Passkey state changed; try again")
        challenge_row.consumed_at = current
        stored.sign_count = max(stored.sign_count, int(verified.new_sign_count))
        stored.device_type = _enum_value(verified.credential_device_type)
        stored.backed_up = bool(verified.credential_backed_up)
        stored.last_used_at = _timestamp()
        session.add(challenge_row)
        session.add(stored)
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", user_id),
                result="success",
                status_code=200,
            )
        session.commit()
    return {"reauthenticated_at": current}


def rename_passkey(
    engine: Engine,
    *,
    user_id: str,
    credential_record_id: str,
    label: str,
    audit_context: Optional[AuditContext] = None,
) -> dict[str, object]:
    _configured()
    cleaned_label = _clean_label(label)
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        _require_account(session, user_id)
        row = session.get(WebAuthnCredential, credential_record_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Passkey not found")
        row.label = cleaned_label
        session.add(row)
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", user_id),
                result="success",
                status_code=200,
            )
        session.commit()
        session.refresh(row)
        return _credential_out(row)


def remove_passkey(
    engine: Engine,
    *,
    user_id: str,
    session_id: str,
    credential_record_id: str,
    password_recent: bool,
    audit_context: Optional[AuditContext] = None,
    now: Optional[int] = None,
) -> dict[str, object]:
    config = _configured()
    current = _now(now)
    with AUTHENTICATOR_MUTATION_LOCK, Session(engine) as session:
        account = _require_account(session, user_id)
        _require_active_session(session, user_id, session_id, current)
        _require_current_strength(
            session,
            account,
            session_id,
            password_recent=password_recent,
            rp_id=config.rp_id or "",
            origin=config.origin or "",
            now=current,
        )
        row = session.get(WebAuthnCredential, credential_record_id)
        if row is None or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Passkey not found")
        credentials = list(
            session.exec(
                select(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
            )
        )
        remaining = len(credentials) - 1
        if remaining == 0 and _policy_requires_account(session, account):
            raise HTTPException(
                status_code=409,
                detail="Required MFA policy prevents removing the last passkey",
            )
        session.delete(row)
        if remaining == 0:
            account.mfa_enabled = False
            account.updated_at = _timestamp()
            session.add(account)
            pending = list(
                session.exec(
                    select(WebAuthnChallenge).where(
                        WebAuthnChallenge.user_id == user_id,
                        WebAuthnChallenge.consumed_at.is_(None),
                    )
                )
            )
            for challenge in pending:
                challenge.consumed_at = current
                session.add(challenge)
        if audit_context is not None:
            append_audit_event(
                session,
                audit_context.for_object("user", user_id),
                result="success",
                status_code=200,
            )
        session.commit()
        return {"mfa_enabled": account.mfa_enabled, "credential_count": remaining}
