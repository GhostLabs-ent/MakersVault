import hmac
import os
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError

from config import env_bool

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "super-secret")
AUTH_SECRET = os.getenv("AUTH_SECRET", "changeme-secret")
AUTH_TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL", "43200"))
AUTH_ALGO = "HS256"
AUTH_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)
# Escape hatch for throwaway/dev deployments that intentionally keep the
# published sample credentials. Never set this on a reachable host.
AUTH_ALLOW_INSECURE_DEFAULTS = env_bool("AUTH_ALLOW_INSECURE_DEFAULTS", False)
INSECURE_DEFAULT_PASSWORD = "super-secret"
INSECURE_DEFAULT_SECRET = "changeme-secret"
auth_scheme = HTTPBearer(auto_error=False)


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


def create_token(username: str) -> str:
  now = int(time.time())
  payload = {"sub": username, "iat": now, "exp": now + AUTH_TOKEN_TTL}
  return jwt.encode(payload, AUTH_SECRET, algorithm=AUTH_ALGO)


def require_auth(
  credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
  token_param: Optional[str] = Query(default=None, alias="token"),
):
  if not AUTH_ENABLED:
    return None
  token = credentials.credentials if credentials else token_param
  if not token:
    raise HTTPException(status_code=401, detail="Unauthorized")
  try:
    jwt.decode(token, AUTH_SECRET, algorithms=[AUTH_ALGO])
  except PyJWTError:
    raise HTTPException(status_code=401, detail="Invalid or expired token") from None
  return token
