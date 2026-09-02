from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import hmac
import secrets
import time
import uuid
from typing import Optional

from sqlalchemy import Engine, or_
from sqlmodel import Session, select

from models import BrowserSession, UserAccount
from security_config import PRODUCTION_ENV, load_security_config


PRODUCTION_SESSION_COOKIE = "__Host-makersvault_session"
PRODUCTION_CSRF_COOKIE = "__Host-makersvault_csrf"
DEVELOPMENT_SESSION_COOKIE = "makersvault_session_dev"
DEVELOPMENT_CSRF_COOKIE = "makersvault_csrf_dev"
SESSION_SECRET_BYTES = 32
SESSION_CLEANUP_LIMIT = 200
CLIENT_ADDRESS_LIMIT = 128
USER_AGENT_LIMIT = 512

_CONFIG = load_security_config()
_DIGEST_KEY = _CONFIG.secret.encode("utf-8")


@dataclass(frozen=True)
class CookiePolicy:
    session_name: str
    csrf_name: str
    secure: bool


@dataclass(frozen=True)
class CreatedBrowserSession:
    id: str
    secret: str
    csrf_token: str
    idle_expires_at: int
    absolute_expires_at: int


@dataclass(frozen=True)
class SessionPrincipal:
    session_id: str
    user_id: str
    username: str
    csrf_token: str
    created_at: int
    last_seen_at: int
    idle_expires_at: int
    absolute_expires_at: int


@dataclass(frozen=True)
class BrowserSessionSummary:
    id: str
    created_at: int
    last_seen_at: int
    idle_expires_at: int
    absolute_expires_at: int
    client_address: Optional[str]
    user_agent: Optional[str]


def cookie_policy(environment: Optional[str] = None) -> CookiePolicy:
    production = (environment or _CONFIG.environment) == PRODUCTION_ENV
    return CookiePolicy(
        session_name=(
            PRODUCTION_SESSION_COOKIE if production else DEVELOPMENT_SESSION_COOKIE
        ),
        csrf_name=PRODUCTION_CSRF_COOKIE if production else DEVELOPMENT_CSRF_COOKIE,
        secure=production,
    )


def _now(value: Optional[int]) -> int:
    return int(time.time()) if value is None else int(value)


def _digest(context: bytes, value: str) -> str:
    return hmac.new(
        _DIGEST_KEY,
        context + value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _session_digest(secret: str) -> str:
    return _digest(b"makersvault-browser-session\0", secret)


def _csrf_token(secret: str) -> str:
    digest = hmac.new(
        _DIGEST_KEY,
        b"makersvault-browser-csrf\0" + secret.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _bounded_metadata(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    cleaned = "".join(character for character in value.strip() if character.isprintable())
    return cleaned[:limit] or None


def cleanup_browser_sessions(
    engine: Engine,
    *,
    now: Optional[int] = None,
    limit: int = SESSION_CLEANUP_LIMIT,
) -> int:
    current = _now(now)
    bounded_limit = max(1, min(int(limit), 1000))
    with Session(engine) as session:
        rows = list(
            session.exec(
                select(BrowserSession)
                .where(
                    or_(
                        BrowserSession.revoked_at.is_not(None),
                        BrowserSession.idle_expires_at <= current,
                        BrowserSession.absolute_expires_at <= current,
                    )
                )
                .order_by(BrowserSession.created_at, BrowserSession.id)
                .limit(bounded_limit)
            )
        )
        for row in rows:
            session.delete(row)
        if rows:
            session.commit()
        return len(rows)


def create_browser_session(
    engine: Engine,
    *,
    user_id: str,
    client_address: Optional[str],
    user_agent: Optional[str],
    now: Optional[int] = None,
    idle_ttl: Optional[int] = None,
    absolute_ttl: Optional[int] = None,
    max_active: Optional[int] = None,
) -> CreatedBrowserSession:
    current = _now(now)
    idle = int(idle_ttl or _CONFIG.session_idle_ttl)
    absolute = int(absolute_ttl or _CONFIG.session_absolute_ttl)
    maximum = int(max_active or _CONFIG.session_max_active)
    if idle <= 0 or absolute < idle or maximum <= 0:
        raise ValueError("invalid browser session policy")

    secret = secrets.token_urlsafe(SESSION_SECRET_BYTES)
    csrf_token = _csrf_token(secret)
    session_id = str(uuid.uuid4())
    idle_expires_at = current + idle
    absolute_expires_at = current + absolute
    created = BrowserSession(
        id=session_id,
        user_id=user_id,
        secret_digest=_session_digest(secret),
        created_at=current,
        last_seen_at=current,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
        idle_ttl_seconds=idle,
        client_address=_bounded_metadata(client_address, CLIENT_ADDRESS_LIMIT),
        user_agent=_bounded_metadata(user_agent, USER_AGENT_LIMIT),
    )
    with Session(engine) as session:
        user = session.get(UserAccount, user_id)
        if user is None or not user.enabled:
            raise ValueError("browser sessions require an enabled user")
        active = list(
            session.exec(
                select(BrowserSession)
                .where(BrowserSession.user_id == user_id)
                .where(BrowserSession.revoked_at.is_(None))
                .where(BrowserSession.idle_expires_at > current)
                .where(BrowserSession.absolute_expires_at > current)
                .order_by(BrowserSession.last_seen_at, BrowserSession.created_at)
            )
        )
        for row in active[: max(0, len(active) - maximum + 1)]:
            row.revoked_at = current
            session.add(row)
        session.add(created)
        session.commit()
    cleanup_browser_sessions(engine, now=current)
    return CreatedBrowserSession(
        id=session_id,
        secret=secret,
        csrf_token=csrf_token,
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )


def authenticate_browser_session(
    engine: Engine,
    secret: str,
    *,
    now: Optional[int] = None,
    touch: bool = True,
    touch_interval: Optional[int] = None,
) -> Optional[SessionPrincipal]:
    if not secret or len(secret) > 512:
        return None
    current = _now(now)
    digest = _session_digest(secret)
    interval = int(touch_interval or _CONFIG.session_touch_interval)
    with Session(engine) as session:
        row = session.exec(
            select(BrowserSession).where(BrowserSession.secret_digest == digest)
        ).first()
        if row is None or row.revoked_at is not None:
            return None
        if current >= row.idle_expires_at or current >= row.absolute_expires_at:
            row.revoked_at = current
            session.add(row)
            session.commit()
            return None
        user = session.get(UserAccount, row.user_id)
        if user is None or not user.enabled:
            row.revoked_at = current
            session.add(row)
            session.commit()
            return None
        if touch and current - row.last_seen_at >= interval:
            row.last_seen_at = current
            row.idle_expires_at = min(
                current + row.idle_ttl_seconds,
                row.absolute_expires_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return SessionPrincipal(
            session_id=row.id,
            user_id=user.id,
            username=user.username,
            csrf_token=_csrf_token(secret),
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
        )


def csrf_matches(principal: SessionPrincipal, token: Optional[str]) -> bool:
    if not token or len(token) > 512:
        return False
    return hmac.compare_digest(principal.csrf_token, token)


def revoke_session_secret(
    engine: Engine,
    secret: Optional[str],
    *,
    now: Optional[int] = None,
) -> bool:
    if not secret or len(secret) > 512:
        return False
    current = _now(now)
    with Session(engine) as session:
        row = session.exec(
            select(BrowserSession).where(
                BrowserSession.secret_digest == _session_digest(secret)
            )
        ).first()
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = current
        session.add(row)
        session.commit()
        return True


def revoke_browser_session(
    engine: Engine,
    *,
    user_id: str,
    session_id: str,
    now: Optional[int] = None,
) -> bool:
    current = _now(now)
    with Session(engine) as session:
        row = session.get(BrowserSession, session_id)
        if row is None or row.user_id != user_id or row.revoked_at is not None:
            return False
        row.revoked_at = current
        session.add(row)
        session.commit()
        return True


def revoke_all_user_sessions(
    engine: Engine,
    *,
    user_id: str,
    now: Optional[int] = None,
) -> int:
    current = _now(now)
    with Session(engine) as session:
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
        if rows:
            session.commit()
        return len(rows)


def list_user_sessions(
    engine: Engine,
    *,
    user_id: str,
    now: Optional[int] = None,
) -> list[BrowserSessionSummary]:
    current = _now(now)
    with Session(engine) as session:
        rows = list(
            session.exec(
                select(BrowserSession)
                .where(BrowserSession.user_id == user_id)
                .where(BrowserSession.revoked_at.is_(None))
                .where(BrowserSession.idle_expires_at > current)
                .where(BrowserSession.absolute_expires_at > current)
                .order_by(BrowserSession.last_seen_at.desc(), BrowserSession.id)
            )
        )
    return [
        BrowserSessionSummary(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
            client_address=row.client_address,
            user_agent=row.user_agent,
        )
        for row in rows
    ]
