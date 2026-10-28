"""Server-side sessions: the revocable half of the access/refresh token pair.

The access token is a short-lived JWT carrying the session id (`sid`); the
session row is the source of truth, so revoking it kills the access token on the
next request. The refresh token is opaque and only its sha256 is stored, so a
database leak cannot be replayed.

Callers own the transaction: functions here add or mutate rows and flush, but
never commit.

Seams for Mf-7op4 (session list and revoke devices):
- a rotated refresh token that is presented again currently just fails; the
  planned hardening is to treat the replay as theft and revoke the whole
  session (and every session of that user).
- refresh rotation is single-use per session, so two tabs that share one
  browser session will race: the loser gets a 401 and has to sign in again.
  Mf-7op4 owns the grace window or per-device sessions that fix this.
- `device`, `user_agent` and `client_ip` are recorded now so the device list
  can be built without another migration.
"""

import hashlib
import secrets
import time
from typing import Optional

from sqlalchemy import update
from sqlmodel import Session, select

from accounts import ADMIN_ROLE
from models import User, UserSession

PASSWORD_KIND = "password"
BREAK_GLASS_KIND = "break-glass"
BREAK_GLASS_ROLE = ADMIN_ROLE
REFRESH_TOKEN_BYTES = 32


def new_refresh_token() -> str:
    """An opaque bearer secret; only its hash is ever stored."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def _unexpired(session_row: UserSession, user: Optional[User], now: int) -> bool:
    if session_row.revoked_at is not None:
        return False
    if session_row.refresh_expires_at <= now:
        return False
    if session_row.user_id is None:
        return True
    return user is not None and not user.disabled


def is_live(session_row: UserSession, user: Optional[User], now: Optional[int] = None) -> bool:
    """True when this session may still authorize its access token."""
    now = int(time.time()) if now is None else now
    return _unexpired(session_row, user, now) and session_row.access_expires_at > now


def is_refreshable(session_row: UserSession, user: Optional[User], now: Optional[int] = None) -> bool:
    """True when this session may still mint tokens (its access token may be dead)."""
    now = int(time.time()) if now is None else now
    return _unexpired(session_row, user, now)


def role_for(session_row: UserSession, user: Optional[User]) -> str:
    """Break-glass is always admin; every other session reads the current role."""
    if session_row.kind == BREAK_GLASS_KIND:
        return BREAK_GLASS_ROLE
    return user.role if user is not None else "viewer"


def create(
    session: Session,
    *,
    username: str,
    user_id: Optional[str],
    kind: str,
    access_ttl: int,
    refresh_ttl: int,
    device: Optional[str] = None,
    user_agent: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> tuple[UserSession, str]:
    """Open a session and return it with the raw refresh token (stored hashed)."""
    now = int(time.time())
    refresh_token = new_refresh_token()
    session_row = UserSession(
        username=username,
        user_id=user_id,
        kind=kind,
        refresh_token_hash=hash_refresh_token(refresh_token),
        device=device,
        user_agent=user_agent,
        client_ip=client_ip,
        created_at=now,
        last_used_at=now,
        access_expires_at=now + access_ttl,
        refresh_expires_at=now + refresh_ttl,
    )
    session.add(session_row)
    session.flush()
    return session_row, refresh_token


def find_by_refresh_hash(session: Session, token_hash: str) -> Optional[UserSession]:
    return session.exec(select(UserSession).where(UserSession.refresh_token_hash == token_hash)).first()


def get(session: Session, session_id: str) -> Optional[UserSession]:
    return session.get(UserSession, session_id)


def rotate(session: Session, session_row: UserSession, *, access_ttl: int) -> Optional[str]:
    """Swap the row's refresh token for a fresh one.

    The swap is one UPDATE guarded by the presented hash, so a token that was
    already rotated (or revoked) changes no rows and returns None.
    `refresh_expires_at` is deliberately left alone: expiry is absolute from
    login, never extended by rotation.
    """
    now = int(time.time())
    refresh_token = new_refresh_token()
    result = session.execute(
        update(UserSession)
        .where(
            UserSession.id == session_row.id,
            UserSession.refresh_token_hash == session_row.refresh_token_hash,
            UserSession.revoked_at.is_(None),
        )
        .values(
            refresh_token_hash=hash_refresh_token(refresh_token),
            last_used_at=now,
            access_expires_at=now + access_ttl,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    session.refresh(session_row)
    return refresh_token


def revoke(session: Session, session_row: UserSession) -> None:
    """Kill a session. The refresh hash stays, so replays still match a dead row."""
    if session_row.revoked_at is not None:
        return
    session_row.revoked_at = int(time.time())
    session.add(session_row)
    session.flush()


def revoke_by_refresh_hash(session: Session, token_hash: str) -> bool:
    """Revoke the session that owns this refresh token; False when unknown."""
    session_row = find_by_refresh_hash(session, token_hash)
    if session_row is None:
        return False
    revoke(session, session_row)
    return True


def revoke_break_glass(session: Session) -> int:
    """Revoke every env-admin session and return how many were live.

    The break-glass login stops working as soon as the first account exists, so
    its sessions must not outlive the bootstrap that created that account.
    """
    result = session.execute(
        update(UserSession)
        .where(UserSession.kind == BREAK_GLASS_KIND, UserSession.revoked_at.is_(None))
        .values(revoked_at=int(time.time()))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount
