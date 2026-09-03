"""Gate 11D shared-vault account administration and safety invariants."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from authorization import Role
from identity_service import (
    PASSWORD_POLICY_VERSION,
    PasswordPolicyError,
    hash_new_password,
    normalize_username,
    verify_password_hash,
)
from models import BrowserSession, UserAccount


ACCOUNT_NAME_MAX_LENGTH = 256
_MUTATION_LOCK = threading.RLock()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _clean_display_name(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > ACCOUNT_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=422,
            detail="display name must contain between 1 and 256 characters",
        )
    return cleaned


def _clean_username(value: str) -> tuple[str, str]:
    username = str(value or "").strip()
    try:
        normalized = normalize_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return username, normalized


def _new_password_hash(password: str) -> str:
    try:
        return hash_new_password(password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_account(session: Session, user_id: str) -> UserAccount:
    account = session.get(UserAccount, user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _revoke_sessions(session: Session, user_id: str) -> int:
    current = int(time.time())
    rows = list(
        session.exec(
            select(BrowserSession)
            .where(BrowserSession.user_id == user_id)
            .where(BrowserSession.revoked_at.is_(None))
        )
    )
    for row in rows:
        row.revoked_at = current
        session.add(row)
    return len(rows)


def _detach(session: Session, account: UserAccount) -> UserAccount:
    session.flush()
    session.refresh(account)
    session.expunge(account)
    return account


def list_accounts(database_engine: Engine) -> list[UserAccount]:
    with Session(database_engine) as session:
        rows = list(
            session.exec(
                select(UserAccount).order_by(
                    UserAccount.username_normalized,
                    UserAccount.id,
                )
            )
        )
        for row in rows:
            session.expunge(row)
        return rows


def create_account(
    database_engine: Engine,
    *,
    username: str,
    display_name: str,
    password: str,
    role: Role,
) -> UserAccount:
    cleaned_username, normalized = _clean_username(username)
    cleaned_display_name = _clean_display_name(display_name)
    password_hash = _new_password_hash(password)
    timestamp = _timestamp()
    account = UserAccount(
        id=str(uuid.uuid4()),
        username=cleaned_username,
        username_normalized=normalized,
        display_name=cleaned_display_name,
        password_hash=password_hash,
        enabled=True,
        password_policy_version=PASSWORD_POLICY_VERSION,
        password_change_required=True,
        role=Role(role).value,
        created_at=timestamp,
        updated_at=timestamp,
    )
    with _MUTATION_LOCK, Session(database_engine) as session:
        session.add(account)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail="Username already exists") from exc
        return _detach(session, account)


def update_account(
    database_engine: Engine,
    user_id: str,
    *,
    display_name: Optional[str] = None,
    role: Optional[Role] = None,
    enabled: Optional[bool] = None,
) -> UserAccount:
    if display_name is None and role is None and enabled is None:
        raise HTTPException(status_code=422, detail="No account changes were supplied")
    with _MUTATION_LOCK, Session(database_engine) as session:
        account = _require_account(session, user_id)
        next_role = Role(role).value if role is not None else account.role
        next_enabled = bool(enabled) if enabled is not None else account.enabled
        removes_enabled_administrator = (
            account.enabled
            and account.role == Role.ADMINISTRATOR.value
            and (not next_enabled or next_role != Role.ADMINISTRATOR.value)
        )
        if removes_enabled_administrator:
            enabled_administrators = len(
                list(
                    session.exec(
                        select(UserAccount.id).where(
                            UserAccount.enabled.is_(True),
                            UserAccount.role == Role.ADMINISTRATOR.value,
                        )
                    )
                )
            )
            if enabled_administrators <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot disable or demote the last enabled Administrator",
                )

        authority_changed = account.role != next_role or account.enabled != next_enabled
        if display_name is not None:
            account.display_name = _clean_display_name(display_name)
        account.role = next_role
        account.enabled = next_enabled
        account.updated_at = _timestamp()
        if authority_changed:
            _revoke_sessions(session, account.id)
        session.add(account)
        session.commit()
        return _detach(session, account)


def reset_account_password(
    database_engine: Engine,
    user_id: str,
    *,
    password: str,
) -> UserAccount:
    password_hash = _new_password_hash(password)
    with _MUTATION_LOCK, Session(database_engine) as session:
        account = _require_account(session, user_id)
        account.password_hash = password_hash
        account.password_policy_version = PASSWORD_POLICY_VERSION
        account.password_change_required = True
        account.updated_at = _timestamp()
        _revoke_sessions(session, account.id)
        session.add(account)
        session.commit()
        return _detach(session, account)


def change_own_password(
    database_engine: Engine,
    user_id: str,
    *,
    password: str,
) -> UserAccount:
    password_hash = _new_password_hash(password)
    with _MUTATION_LOCK, Session(database_engine) as session:
        account = _require_account(session, user_id)
        if not account.enabled:
            raise HTTPException(status_code=403, detail="Account is disabled")
        account.password_hash = password_hash
        account.password_policy_version = PASSWORD_POLICY_VERSION
        account.password_change_required = False
        account.updated_at = _timestamp()
        _revoke_sessions(session, account.id)
        session.add(account)
        session.commit()
        return _detach(session, account)


def verify_account_password(
    database_engine: Engine,
    user_id: str,
    password: str,
) -> bool:
    with Session(database_engine) as session:
        account = session.get(UserAccount, user_id)
        password_hash = account.password_hash if account is not None and account.enabled else ""
    return bool(password_hash) and verify_password_hash(password_hash, password)
