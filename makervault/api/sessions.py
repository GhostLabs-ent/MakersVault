"""Server-side sessions: the revocable half of the access/refresh token pair.

The access token is a short-lived JWT carrying the session id (`sid`); the
session row is the source of truth, so revoking it kills the access token on the
next request. The refresh token is opaque and only its sha256 is stored, so a
database leak cannot be replayed.

A refresh token is single-use. `rotate` swaps it for a fresh one in one guarded
UPDATE and keeps the superseded hash as `previous_refresh_token_hash`, so a
second tab that presents the token it woke up with still succeeds once inside
`REFRESH_GRACE_SECONDS`. The concession is bounded: the grace path rotates the
same row again, so a token is interchangeable with its own successor for one
generation and sixty seconds only. A previous-generation token presented after
the window is treated as a compromise and revokes *that session row*, never the
user's other sessions - revoking every device would hand anyone holding one
stale token a denial-of-service lever. A hash older than one generation matches
nothing and is a side-effect-free 401, so spraying tokens cannot revoke
anything.

Callers own the transaction: functions here add or mutate rows and flush, but
never commit.

`device`, `user_agent` and `client_ip` are recorded on the row so the session
list can be built without another migration; no refresh hash is ever part of
that list.
"""

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import delete, or_, update
from sqlmodel import Session, select

from accounts import ADMIN_ROLE
from models import User, UserSession

PASSWORD_KIND = "password"
BREAK_GLASS_KIND = "break-glass"
# An SSO login is a real account session, so unlike break-glass it reads the
# stored role rather than asserting admin.
OIDC_KIND = "oidc"
BREAK_GLASS_ROLE = ADMIN_ROLE
REFRESH_TOKEN_BYTES = 32

# How long a superseded refresh token stays interchangeable with its successor.
# A module constant rather than an environment variable on purpose: the grace
# window is a correctness knob, not a deployment choice, and an env var would
# force a matching entry in docker-compose.deploy.yml, .env.example and the
# configuration reference for no operator benefit.
REFRESH_GRACE_SECONDS = 60

# What `rotate` did with the token it was handed.
ROTATE_OK = "ok"
ROTATE_GRACED = "graced"
ROTATE_REPLAYED = "replayed"
ROTATE_STALE = "stale"


def _now() -> int:
    """The module's one clock seam, so a test can age a row without sleeping."""
    return int(time.time())


@dataclass(frozen=True)
class Rotation:
    """The outcome of one refresh presentation.

    `refresh_token` is set only on the two paths that actually rotated the row;
    every other outcome leaves the caller with nothing to hand out.
    """

    outcome: str
    session_row: UserSession
    refresh_token: Optional[str] = None


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
    now = _now() if now is None else now
    return _unexpired(session_row, user, now) and session_row.access_expires_at > now


def is_refreshable(session_row: UserSession, user: Optional[User], now: Optional[int] = None) -> bool:
    """True when this session may still mint tokens (its access token may be dead)."""
    now = _now() if now is None else now
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
    now = _now()
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
    """The row whose *current* refresh token is this hash; not the previous one."""
    return session.exec(select(UserSession).where(UserSession.refresh_token_hash == token_hash)).first()


def find_by_presented_hash(session: Session, token_hash: str) -> Optional[UserSession]:
    """The row that owns this hash, current or one rotation old.

    The grace window is what makes the previous hash worth looking up: a tab
    that was asleep across one rotation still presents the superseded token.
    """
    return session.exec(
        select(UserSession).where(
            or_(
                UserSession.refresh_token_hash == token_hash,
                UserSession.previous_refresh_token_hash == token_hash,
            )
        )
    ).first()


def get(session: Session, session_id: str) -> Optional[UserSession]:
    return session.get(UserSession, session_id)


def rotate(session: Session, session_row: UserSession, *, presented_hash: str, access_ttl: int) -> Rotation:
    """Swap the row's refresh token for a fresh one, with one grace generation.

    Both rotation paths are one guarded UPDATE, so a token that was already
    rotated past the guard changes no rows and loses. The guard differs:

    * the current hash matches: the ordinary path, guarded on `refresh_token_hash`;
    * the previous hash matches inside the grace window: the same rotation
      again, guarded on both hashes so a concurrent winner still wins.

    `previous_refresh_token_hash` is assigned from the pre-update
    `refresh_token_hash` in the same statement, so the superseded hash is
    stashed without a second read and without a second statement to race.
    `refresh_expires_at` is deliberately left alone: expiry is absolute from
    login, never extended by rotation.

    A previous-generation hash outside the window is a replay, and revokes only
    this row. Anything else is stale and has no side effects, so a sprayed hash
    cannot revoke a session.
    """
    now = _now()
    if presented_hash == session_row.refresh_token_hash:
        outcome = ROTATE_OK
    elif presented_hash == session_row.previous_refresh_token_hash and session_row.rotated_at is not None:
        if now - session_row.rotated_at <= REFRESH_GRACE_SECONDS:
            outcome = ROTATE_GRACED
        else:
            revoke(session, session_row)
            return Rotation(ROTATE_REPLAYED, session_row)
    else:
        return Rotation(ROTATE_STALE, session_row)

    refresh_token = new_refresh_token()
    statement = update(UserSession).where(
        UserSession.id == session_row.id,
        UserSession.revoked_at.is_(None),
    )
    if outcome == ROTATE_OK:
        statement = statement.where(UserSession.refresh_token_hash == presented_hash)
    else:
        statement = statement.where(
            UserSession.refresh_token_hash == session_row.refresh_token_hash,
            UserSession.previous_refresh_token_hash == presented_hash,
        )
    result = session.execute(
        statement.values(
            previous_refresh_token_hash=UserSession.refresh_token_hash,
            refresh_token_hash=hash_refresh_token(refresh_token),
            rotated_at=now,
            last_used_at=now,
            access_expires_at=now + access_ttl,
        ).execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return Rotation(ROTATE_STALE, session_row)
    session.refresh(session_row)
    return Rotation(outcome, session_row, refresh_token)


def revoke(session: Session, session_row: UserSession) -> None:
    """Kill a session. The refresh hash stays, so replays still match a dead row."""
    if session_row.revoked_at is not None:
        return
    session_row.revoked_at = _now()
    session.add(session_row)
    session.flush()


def revoke_by_refresh_hash(session: Session, token_hash: str) -> bool:
    """Revoke the session that owns this refresh token; False when unknown.

    Resolves through `find_by_presented_hash`, so logging out with a token from
    one generation back still kills the session instead of leaving it live.
    """
    session_row = find_by_presented_hash(session, token_hash)
    if session_row is None:
        return False
    revoke(session, session_row)
    return True


def list_for_user(session: Session, *, user_id: Optional[str], username: str) -> list[UserSession]:
    """This principal's active sessions, newest use first.

    A real account is scoped by `user_id`; break-glass rows carry `user_id NULL`
    and are scoped by the fixed break-glass username instead. Only active rows
    are listed: a revoked or refresh-expired session cannot authorize anything,
    so showing it would offer the caller an action with no effect. No hash is
    selected into the response - the caller serialises `SessionOut` only.
    """
    now = _now()
    statement = select(UserSession).where(
        UserSession.revoked_at.is_(None),
        UserSession.refresh_expires_at > now,
    )
    if user_id is not None:
        statement = statement.where(UserSession.user_id == user_id)
    else:
        statement = statement.where(UserSession.user_id.is_(None), UserSession.username == username)
    return list(session.exec(statement.order_by(UserSession.last_used_at.desc())))


def delete_stale(session: Session, *, now: int, revoked_retention: int) -> int:
    """Delete rows that can no longer authorize anything; returns the count.

    A row is stale when its refresh token has expired (the access token is
    necessarily expired too, because it is shorter-lived) or when it has been
    revoked for longer than the retention window. Live and freshly-revoked rows
    survive, so a bug in this sweep cannot sign anybody out.
    """
    result = session.execute(
        delete(UserSession)
        .where(
            or_(
                UserSession.refresh_expires_at <= now,
                (UserSession.revoked_at.is_not(None)) & (UserSession.revoked_at <= now - revoked_retention),
            )
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


def revoke_break_glass(session: Session) -> int:
    """Revoke every env-admin session and return how many were live.

    The break-glass login stops working as soon as the first account exists, so
    its sessions must not outlive the bootstrap that created that account.
    """
    result = session.execute(
        update(UserSession)
        .where(UserSession.kind == BREAK_GLASS_KIND, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount
