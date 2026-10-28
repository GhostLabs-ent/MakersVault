import hmac
import os
import time
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlmodel import Session

import accounts
import sessions
from config import env_bool
from db import engine
from models import UserSession

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "super-secret")
AUTH_SECRET = os.getenv("AUTH_SECRET", "changeme-secret")
# Deprecated: only the access token TTL is used now. Kept so an existing
# environment that still sets AUTH_TOKEN_TTL keeps starting.
AUTH_TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL", "43200"))
AUTH_ACCESS_TOKEN_TTL = int(os.getenv("AUTH_ACCESS_TOKEN_TTL", "900"))
AUTH_REFRESH_TTL_SECONDS = int(os.getenv("AUTH_REFRESH_TTL_SECONDS", str(30 * 24 * 60 * 60)))
AUTH_ALGO = "HS256"
AUTH_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)
# Escape hatch for throwaway/dev deployments that intentionally keep the
# published sample credentials. Never set this on a reachable host.
AUTH_ALLOW_INSECURE_DEFAULTS = env_bool("AUTH_ALLOW_INSECURE_DEFAULTS", False)
INSECURE_DEFAULT_PASSWORD = "super-secret"
INSECURE_DEFAULT_SECRET = "changeme-secret"
ACCESS_TOKEN_TYPE = "access"
BREAK_GLASS_SUBJECT = "break-glass"
auth_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
  """The authenticated principal behind one request."""

  session_id: str
  user_id: Optional[str]
  username: str
  role: str
  kind: str


@dataclass(frozen=True)
class LoginResult:
  """A fresh session's tokens plus the access-token lifetime in seconds."""

  token: str
  refresh_token: str
  expires_in: int


def credentials_match(username: str, password: str) -> bool:
  """Compare submitted credentials without leaking timing information."""
  user_ok = hmac.compare_digest((username or "").encode(), (AUTH_USERNAME or "").encode())
  pass_ok = hmac.compare_digest((password or "").encode(), (AUTH_PASSWORD or "").encode())
  return user_ok and pass_ok


def validate_auth_configuration() -> None:
  """Refuse to start with the published sample credentials still in place.

  The sample values are documented in the README, so leaving them active turns
  "auth enabled" into "publicly writable". Only enforced when auth is on.
  """
  if not AUTH_ENABLED or AUTH_ALLOW_INSECURE_DEFAULTS:
    return
  problems = []
  if AUTH_PASSWORD == INSECURE_DEFAULT_PASSWORD:
    problems.append("AUTH_PASSWORD is the published sample value")
  if AUTH_SECRET in {"", INSECURE_DEFAULT_SECRET}:
    problems.append("AUTH_SECRET is the published sample value")
  if problems:
    raise RuntimeError(
      "; ".join(problems)
      + ". Set AUTH_PASSWORD and AUTH_SECRET, or set AUTH_ALLOW_INSECURE_DEFAULTS=1 "
      "to accept a publicly-known login (not recommended)."
    )


def create_access_token(session_row: UserSession, role: str) -> str:
  """Sign a short-lived access token bound to one session row.

  The token is a 15-minute ticket, not a self-contained identity: `sid` must
  still map to a live session, and role/disabled state is re-read per request.
  """
  now = int(time.time())
  payload = {
    "sub": session_row.user_id or BREAK_GLASS_SUBJECT,
    "sid": session_row.id,
    "typ": ACCESS_TOKEN_TYPE,
    "role": role,
    "username": session_row.username,
    "iat": now,
    "exp": now + AUTH_ACCESS_TOKEN_TTL,
  }
  return jwt.encode(payload, AUTH_SECRET, algorithm=AUTH_ALGO)


def decode_access_token(token: str) -> dict:
  """Verify signature and expiry, and demand the claims issued tokens carry."""
  return jwt.decode(
    token,
    AUTH_SECRET,
    algorithms=[AUTH_ALGO],
    options={"require": ["sub", "sid", "typ", "iat", "exp"]},
  )


def login(
  db: Session,
  username: str,
  password: str,
  *,
  user_agent: Optional[str] = None,
  client_ip: Optional[str] = None,
) -> Optional[LoginResult]:
  """Open a session for these credentials, or return None when they do not match.

  The env break-glass admin is only accepted while the users table is empty: a
  real account always wins over the published sample credentials.
  """
  user = accounts.get_user_by_username(db, username)
  if user is None:
    if not accounts.users_table_empty(db):
      accounts.dummy_verify()
      return None
    if not credentials_match(username, password):
      return None
    user_id = None
    kind = sessions.BREAK_GLASS_KIND
    session_username = AUTH_USERNAME
  else:
    if user.disabled or not accounts.verify_password(user.password_hash, password):
      return None
    if accounts.needs_rehash(user.password_hash or ""):
      accounts.update_password_hash(db, user, password)
    user_id = user.id
    kind = sessions.PASSWORD_KIND
    session_username = user.username

  session_row, refresh_token = sessions.create(
    db,
    username=session_username,
    user_id=user_id,
    kind=kind,
    access_ttl=AUTH_ACCESS_TOKEN_TTL,
    refresh_ttl=AUTH_REFRESH_TTL_SECONDS,
    user_agent=user_agent,
    client_ip=client_ip,
  )
  token = create_access_token(session_row, sessions.role_for(session_row, user))
  return LoginResult(token=token, refresh_token=refresh_token, expires_in=AUTH_ACCESS_TOKEN_TTL)


def require_auth(
  credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
  token_param: Optional[str] = Query(default=None, alias="token"),
) -> Optional[AuthContext]:
  """Authenticate the request; returns None when auth is disabled."""
  if not AUTH_ENABLED:
    return None
  token = credentials.credentials if credentials else token_param
  if not token:
    raise HTTPException(status_code=401, detail="Unauthorized")
  try:
    payload = decode_access_token(token)
  except PyJWTError:
    raise HTTPException(status_code=401, detail="Invalid or expired token") from None
  session_id = payload.get("sid")
  if payload.get("typ") != ACCESS_TOKEN_TYPE or not session_id:
    raise HTTPException(status_code=401, detail="Invalid or expired token")
  with Session(engine) as db:
    session_row = sessions.get(db, str(session_id))
    if session_row is None:
      raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = accounts.get_user(db, session_row.user_id)
    if not sessions.is_live(session_row, user):
      raise HTTPException(status_code=401, detail="Invalid or expired token")
    return AuthContext(
      session_id=session_row.id,
      user_id=session_row.user_id,
      username=session_row.username,
      role=sessions.role_for(session_row, user),
      kind=session_row.kind,
    )


def require_admin(context: Optional[AuthContext] = Depends(require_auth)) -> Optional[AuthContext]:
  """Gate user administration on the admin role (break-glass counts as admin)."""
  if context is None:
    return None
  if context.role != accounts.ADMIN_ROLE:
    raise HTTPException(status_code=403, detail="Administrator access required")
  return context
