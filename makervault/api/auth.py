import hashlib
import hmac
import time
import uuid
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
HANDOFF_AUDIENCE = "makersvault-bridge"
HANDOFF_ISSUER = "makersvault"
HANDOFF_TOKEN_TTL = 90
AUTH_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)
auth_scheme = HTTPBearer(auto_error=False)


def validate_auth_config() -> None:
  validate_security_config(SECURITY_CONFIG)


def create_token(username: str) -> str:
  now = int(time.time())
  payload = {"sub": username, "iat": now, "exp": now + AUTH_TOKEN_TTL}
  return jwt.encode(payload, AUTH_SECRET, algorithm=AUTH_ALGO)


def _handoff_signing_key() -> bytes:
  return hmac.new(
    AUTH_SECRET.encode("utf-8"),
    b"makersvault-v5.1-handoff",
    hashlib.sha256,
  ).digest()


def create_handoff_token(
  asset_id: str,
  file_kind: str,
  file_id: str,
  tool: str,
  filename: str,
  size: int,
) -> str:
  now = int(time.time())
  payload = {
    "iss": HANDOFF_ISSUER,
    "aud": HANDOFF_AUDIENCE,
    "typ": "handoff",
    "sub": asset_id,
    "file_kind": file_kind,
    "file_id": file_id,
    "tool": tool,
    "filename": filename,
    "size": size,
    "jti": str(uuid.uuid4()),
    "iat": now,
    "nbf": now,
    "exp": now + HANDOFF_TOKEN_TTL,
  }
  return jwt.encode(payload, _handoff_signing_key(), algorithm=AUTH_ALGO)


def decode_handoff_token(token: str) -> dict:
  try:
    payload = jwt.decode(
      token,
      _handoff_signing_key(),
      algorithms=[AUTH_ALGO],
      audience=HANDOFF_AUDIENCE,
      issuer=HANDOFF_ISSUER,
      options={
        "require": [
          "aud", "exp", "file_id", "file_kind", "filename", "iat", "iss",
          "jti", "nbf", "size", "sub", "tool", "typ",
        ]
      },
    )
  except PyJWTError as exc:
    raise HTTPException(status_code=401, detail="Invalid or expired handoff grant") from exc
  if payload.get("typ") != "handoff" or payload.get("tool") not in {"slicer", "engraver"}:
    raise HTTPException(status_code=401, detail="Invalid handoff grant")
  if payload.get("file_kind") not in {"primary", "prepared"}:
    raise HTTPException(status_code=401, detail="Invalid handoff grant")
  return payload


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
