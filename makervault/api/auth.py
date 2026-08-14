import time
import jwt
from jwt import PyJWTError
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional

from security_config import load_security_config, validate_security_config

SECURITY_CONFIG = load_security_config()
AUTH_USERNAME = SECURITY_CONFIG.username
AUTH_PASSWORD = SECURITY_CONFIG.password
AUTH_SECRET = SECURITY_CONFIG.secret
AUTH_TOKEN_TTL = SECURITY_CONFIG.token_ttl
AUTH_ALGO = "HS256"
AUTH_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)
auth_scheme = HTTPBearer(auto_error=False)


def validate_auth_config() -> None:
  validate_security_config(SECURITY_CONFIG)


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
    raise HTTPException(status_code=401, detail="Invalid or expired token")
  return token
