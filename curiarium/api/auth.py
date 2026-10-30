"""Authentication: one session-token verifier, plus the file-grant verifier.

`require_auth` proves who is calling from the `Authorization: Bearer` header and
is the authenticator every permission dependency uses, except the four file
routes. Those also accept a file grant, because file bytes are different: an
`<img>`, `<video>` or `<a download>` cannot set a header, so a browser can only
carry a credential in the URL. `?token=` used to spend a 15-minute,
all-routes session token there, which leaked a powerful credential into browser
history, proxy logs and Referer headers. Instead the client mints a batch of
short-lived, single-path, read-only grants (`POST /file-grants`) and puts one in
`?sig=`; nothing else accepts a grant. The two are cryptographically isolated:
grants are signed with a domain-separated subkey (`file_grant_key`), so a grant
never verifies as a session token and a session token never verifies as a grant.
"""

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from jwt.exceptions import InvalidTokenError
from sqlmodel import Session

import accounts
import config
import sessions
from config import env_bool
from db import engine
from models import UserSession

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "super-secret")
# Which login paths exist. Read once at import; empty and unset both mean the
# legacy `auto` default.
AUTH_MODE = (os.getenv("AUTH_MODE", "auto") or "auto").strip().lower()
AUTH_SECRET = os.getenv("AUTH_SECRET", "changeme-secret")
# Deprecated: only the access token TTL is used now. Kept so an existing
# environment that still sets AUTH_TOKEN_TTL keeps starting.
AUTH_TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL", "43200"))
AUTH_ACCESS_TOKEN_TTL = int(os.getenv("AUTH_ACCESS_TOKEN_TTL", "900"))
AUTH_REFRESH_TTL_SECONDS = int(os.getenv("AUTH_REFRESH_TTL_SECONDS", str(30 * 24 * 60 * 60)))
AUTH_ALGO = "HS256"

AUTH_MODE_AUTO = "auto"
AUTH_MODE_BOTH = "both"
AUTH_MODE_LOCAL = "local"
AUTH_MODE_OFF = "off"
AUTH_MODE_OIDC = "oidc"
AUTH_MODES = (AUTH_MODE_AUTO, AUTH_MODE_BOTH, AUTH_MODE_LOCAL, AUTH_MODE_OFF, AUTH_MODE_OIDC)


def resolve_auth_enabled(mode: str, username: str, password: str) -> bool:
  """The single derivation of "the API requires a principal" from the auth mode.

  `auto` keeps the legacy rule exactly - the pair is set or auth is off - with no
  stripping or normalisation, so `AUTH_USERNAME=' '` keeps whatever meaning it
  has today. Any unknown value fails closed.
  """
  if mode in (AUTH_MODE_LOCAL, AUTH_MODE_OIDC, AUTH_MODE_BOTH):
    return True
  if mode == AUTH_MODE_AUTO:
    return bool(username and password)
  return False


# Mode-derived, not an environment variable: every guard reads this attribute,
# and the test suites monkeypatch it, so the name stays stable even though the
# value is now computed from AUTH_MODE.
AUTH_ENABLED = resolve_auth_enabled(AUTH_MODE, AUTH_USERNAME, AUTH_PASSWORD)


def password_login_allowed() -> bool:
  """True when a local password may open a session (the break-glass door included)."""
  return AUTH_ENABLED and AUTH_MODE != AUTH_MODE_OIDC


def oidc_login_allowed() -> bool:
  """True when an SSO sign-in could reach a provider at all in this mode."""
  return AUTH_ENABLED and AUTH_MODE not in (AUTH_MODE_LOCAL, AUTH_MODE_OFF)


def break_glass_configured() -> bool:
  """True when the environment password pair is actually set, not merely blank.

  A blank pair still matches blank credentials in `credentials_match`, so this is
  what keeps an empty form from being a valid login in a mode that forces auth on.
  """
  return bool(AUTH_USERNAME and AUTH_PASSWORD)


# Escape hatch for throwaway/dev deployments that intentionally keep the
# published sample credentials. Never set this on a reachable host.
AUTH_ALLOW_INSECURE_DEFAULTS = env_bool("AUTH_ALLOW_INSECURE_DEFAULTS", False)
INSECURE_DEFAULT_PASSWORD = "super-secret"
INSECURE_DEFAULT_SECRET = "changeme-secret"
ACCESS_TOKEN_TYPE = "access"
BREAK_GLASS_SUBJECT = "break-glass"
# File grants (`?sig=`) are a different credential from a session token: a
# domain-separated HMAC subkey signs them, and the verifier demands the claims
# below on top of the signature. `MAX_TTL` bounds the lifetime a verifier will
# accept, independent of what `create_file_grant` mints today.
FILE_GRANT_KEY_INFO = b"curiarium/file-grant/v1"
FILE_GRANT_AUDIENCE = "curiarium:file-grant"
FILE_GRANT_TYPE = "file-grant"
FILE_GRANT_SCOPE = "file:read"
FILE_GRANT_TTL_SECONDS = 60
FILE_GRANT_MAX_TTL_SECONDS = 300
# The only extra query parameters a granted URL may carry: `v` is the client's
# cache key, `inline` selects the preview disposition on one route.
FILE_GRANT_QUERY_KEYS = frozenset({"v", "inline"})
KIND_FILE_GRANT = "file_grant"
# The MFA challenge is a terser, narrower credential than an access token: it
# proves "this password was correct" for five minutes and nothing else. It is
# signed with its own subkey so a challenge can never verify as an access token
# (`decode_access_token` uses `AUTH_SECRET` itself) nor as a file grant, which
# is why `require_auth` needs no extra check to reject one.
MFA_TOKEN_TYPE = "mfa"
MFA_TOKEN_TTL_SECONDS = 300
MFA_TOKEN_KEY_INFO = b"curiarium/mfa-challenge/v1"
# A viewer is the least role, so the rank ladder keeps a grant read-only if it
# ever reaches a dependency it was not meant to.
ROLE_FILE_GRANT = "viewer"
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
  """A fresh session's tokens plus what the audit row needs to name the actor.

  `username`, `user_id`, `kind` and `role` are copied from the session row the
  login just created; the login handler stages `login.succeeded` before
  committing, and it must not have to re-derive the principal it just made.
  """

  token: str
  refresh_token: str
  expires_in: int
  username: str
  user_id: Optional[str]
  kind: str
  role: str


def credentials_match(username: str, password: str) -> bool:
  """Compare submitted credentials without leaking timing information."""
  user_ok = hmac.compare_digest((username or "").encode(), (AUTH_USERNAME or "").encode())
  pass_ok = hmac.compare_digest((password or "").encode(), (AUTH_PASSWORD or "").encode())
  return user_ok and pass_ok


def validate_auth_configuration() -> None:
  """Refuse to start with the published sample credentials still in place.

  The sample values are documented in the README, so leaving them active turns
  "auth enabled" into "publicly writable". "auth on" no longer means "password
  login exists": `AUTH_MODE` decides which login paths exist. The mode checks
  come first because an unusable mode is worse than a sample credential.
  """
  # Position is load-bearing: this function is reached before the early return
  # below. conftest sets AUTH_ALLOW_INSECURE_DEFAULTS=1, so anything after that
  # line never fires in the suite, and an unknown mode yields AUTH_ENABLED=False
  # and would early-return anyway.
  problems = []
  if AUTH_MODE not in AUTH_MODES:
    problems.append(
      f"AUTH_MODE is {AUTH_MODE!r}: it must be one of {list(AUTH_MODES)}, or unset for the legacy default (auth on when AUTH_USERNAME and AUTH_PASSWORD are both set)"
    )
  if AUTH_MODE == AUTH_MODE_OIDC and not config.OIDC_ENABLED:
    problems.append(
      "AUTH_MODE=oidc leaves no login path: OIDC_ENABLED is false, so SSO is not "
      "configured and this mode refuses local password sign-in. Set OIDC_ENABLED=1 "
      "and finish the OIDC configuration, or set AUTH_MODE=both to allow local "
      "passwords as well."
    )
  if problems:
    raise RuntimeError("; ".join(problems))
  if not AUTH_ENABLED or AUTH_ALLOW_INSECURE_DEFAULTS:
    return
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


def file_grant_key() -> bytes:
  """Derive the grant-signing subkey, domain-separated from the session key.

  Both credentials are HS256 over the same environment secret, so signing them
  with the same key would make the two formats interchangeable. Deriving a
  subkey with HMAC means a token signed for one purpose cannot ever verify for
  the other - isolation is cryptographic, not a `typ` flag a caller could omit.
  """
  return hmac.new(AUTH_SECRET.encode("utf-8"), FILE_GRANT_KEY_INFO, hashlib.sha256).digest()


def create_file_grant(
  *,
  path: str,
  session_id: Optional[str],
  subject: str,
  inline: Optional[str] = None,
) -> tuple[str, int]:
  """Sign a short-lived, single-path, read-only grant; returns (token, expires_at).

  `path` is the API-relative route path without its query string. The `sid`
  claim is not a copy of the session token's authority: the verifier still
  requires that session to be live, so signing out kills outstanding grants.
  """
  now = int(time.time())
  expires_at = now + FILE_GRANT_TTL_SECONDS
  payload = {
    "aud": FILE_GRANT_AUDIENCE,
    "typ": FILE_GRANT_TYPE,
    "scope": FILE_GRANT_SCOPE,
    "p": path,
    "sid": session_id,
    "sub": subject,
    "iat": now,
    "exp": expires_at,
  }
  if inline is not None:
    payload["inline"] = inline
  return jwt.encode(payload, file_grant_key(), algorithm=AUTH_ALGO), expires_at


def decode_file_grant(token: str) -> dict:
  """Verify a grant's signature, audience, lifetime and fixed claim values.

  Raises `jwt.InvalidTokenError` (so callers can catch `PyJWTError`) rather
  than returning a payload the caller might misuse.
  """
  payload = jwt.decode(
    token,
    file_grant_key(),
    algorithms=[AUTH_ALGO],
    audience=FILE_GRANT_AUDIENCE,
    options={"require": ["aud", "typ", "scope", "p", "sid", "sub", "iat", "exp"]},
  )
  if payload.get("typ") != FILE_GRANT_TYPE:
    raise InvalidTokenError("not a file grant")
  if payload.get("scope") != FILE_GRANT_SCOPE:
    raise InvalidTokenError("file grant scope is not read-only")
  if not payload.get("p"):
    raise InvalidTokenError("file grant has no path")
  try:
    lifetime = int(payload["exp"]) - int(payload["iat"])
  except (TypeError, ValueError):
    raise InvalidTokenError("file grant has a malformed lifetime") from None
  if lifetime > FILE_GRANT_MAX_TTL_SECONDS:
    raise InvalidTokenError("file grant lifetime exceeds the maximum")
  return payload


def mfa_token_key() -> bytes:
  """Derive the challenge-signing subkey, domain-separated like the grant key.

  Sharing `AUTH_SECRET` itself would make a challenge and an access token the
  same format with a different `typ` string; deriving a subkey means neither
  can ever verify as the other, whatever the claims say.
  """
  return hmac.new(AUTH_SECRET.encode("utf-8"), MFA_TOKEN_KEY_INFO, hashlib.sha256).digest()


def create_mfa_challenge(user, *, username: str) -> str:
  """Sign a five-minute "password already checked" ticket for one account.

  `auth.login` deliberately does not mint or consume this: it opens sessions,
  and a challenge exists precisely because no session should exist yet.
  """
  now = int(time.time())
  payload = {
    "sub": user.id,
    "typ": MFA_TOKEN_TYPE,
    "username": username,
    "iat": now,
    "exp": now + MFA_TOKEN_TTL_SECONDS,
  }
  return jwt.encode(payload, mfa_token_key(), algorithm=AUTH_ALGO)


def decode_mfa_challenge(token: str) -> dict:
  """Verify a challenge's signature and lifetime and demand `typ == mfa`.

  Raises `jwt.InvalidTokenError` (so callers catch `PyJWTError`) rather than
  returning a payload a caller could mistake for a session.
  """
  payload = jwt.decode(
    token,
    mfa_token_key(),
    algorithms=[AUTH_ALGO],
    options={"require": ["sub", "typ", "iat", "exp"]},
  )
  if payload.get("typ") != MFA_TOKEN_TYPE:
    raise InvalidTokenError("not an mfa challenge")
  return payload


def mfa_required(user) -> bool:
  """True when this account must complete a second factor after a password.

  A stored seed alone is not enough: an SSO-only account has no local password
  to check first, so its identity provider owns the second factor and the
  challenge check must not fire. A second factor only exists on a password
  login path, so a mode that refuses password sign-in never mints a challenge.
  Kept here (not imported from `mfa`, which imports this module) so
  `auth.login` can stay completely untouched.
  """
  return bool(user is not None and user.totp_secret and user.password_hash) and password_login_allowed()


def login(
  db: Session,
  username: str,
  password: str,
  *,
  user_agent: Optional[str] = None,
  client_ip: Optional[str] = None,
) -> Optional[LoginResult]:
  """Open a session for these credentials, or return None when they do not match.

  The env break-glass admin is only accepted while the users table is empty AND
  the environment password pair is actually configured: a real account always
  wins over the published sample credentials.
  """
  user = accounts.get_user_by_username(db, username)
  if user is None:
    # Order is load-bearing: `credentials_match('', '')` is True, so a blank
    # environment pair would accept an empty form in any mode that forces auth
    # on. The pair must be genuinely set before it is even compared.
    if not break_glass_configured():
      accounts.dummy_verify()
      return None
    if not accounts.users_table_empty(db):
      accounts.dummy_verify()
      return None
    if not credentials_match(username, password):
      return None
    user_id = None
    kind = sessions.BREAK_GLASS_KIND
    session_username = AUTH_USERNAME
  else:
    if not password_login_allowed():
      accounts.dummy_verify()
      return None
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
  role = sessions.role_for(session_row, user)
  token = create_access_token(session_row, role)
  return LoginResult(
    token=token,
    refresh_token=refresh_token,
    expires_in=AUTH_ACCESS_TOKEN_TTL,
    username=session_row.username,
    user_id=session_row.user_id,
    kind=session_row.kind,
    role=role,
  )


def require_auth(
  credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
) -> Optional[AuthContext]:
  """Authenticate the request from the Bearer header; None when auth is off.

  Header only: `?token=` was retired with the file grants. A URL that still
  carries a session token is ignored, so the token cannot keep leaking through
  history, logs and Referer headers.
  """
  if not AUTH_ENABLED:
    return None
  token = credentials.credentials if credentials else None
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


def require_auth_or_file_grant(
  request: Request,
  credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
  sig: Optional[str] = Query(default=None, alias="sig"),
) -> Optional[AuthContext]:
  """Authenticate from the Bearer header, or from a `?sig=` file grant.

  Attached only to the four file-serving routes (`permissions.require_file_read`),
  never to a route that lists, writes or administers: a grant is a read-only
  ticket for exactly one path. A header always wins, so a bad header is a 401
  rather than a silent fall back to the query grant.
  """
  if not AUTH_ENABLED:
    return None
  # Presence of the header settles the authenticator, even when it is malformed:
  # a bad Authorization header is a 401, never a silent fall back to `sig`.
  if request.headers.get("Authorization") is not None:
    return require_auth(credentials=credentials)
  if not sig:
    raise HTTPException(status_code=401, detail="Unauthorized")
  try:
    payload = decode_file_grant(sig)
  except PyJWTError:
    raise HTTPException(status_code=401, detail="Invalid or expired token") from None
  if payload["p"] != request.url.path:
    raise HTTPException(status_code=401, detail="Invalid or expired token")
  for key in request.query_params:
    if key != "sig" and key not in FILE_GRANT_QUERY_KEYS:
      raise HTTPException(status_code=401, detail="Invalid or expired token")
  if request.query_params.get("inline") != payload.get("inline"):
    raise HTTPException(status_code=401, detail="Invalid or expired token")
  session_id = payload.get("sid")
  if not session_id:
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
      role=ROLE_FILE_GRANT,
      kind=KIND_FILE_GRANT,
    )
