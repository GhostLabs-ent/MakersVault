import hashlib
import hmac
import os
import time
import uuid
import jwt
from jwt import PyJWTError
from fastapi import HTTPException, Request, Response
from typing import Optional
from urllib.parse import urlparse

from db import engine
from security_config import load_security_config, validate_security_config
from session_service import (
  CreatedBrowserSession,
  SessionPrincipal,
  authenticate_browser_session,
  cookie_policy,
  csrf_matches,
)
from authorization import AccessKind, role_allows, route_rule

SECURITY_CONFIG = load_security_config()
AUTH_USERNAME = SECURITY_CONFIG.username
AUTH_PASSWORD = SECURITY_CONFIG.password
AUTH_SECRET = SECURITY_CONFIG.secret
AUTH_ALGO = "HS256"
HANDOFF_AUDIENCE = "makersvault-bridge"
HANDOFF_ISSUER = "makersvault"
HANDOFF_TOKEN_TTL = 90
AUTH_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def validate_auth_config() -> None:
  validate_security_config(SECURITY_CONFIG)


def _normalize_origin(raw: str) -> Optional[str]:
  try:
    parsed = urlparse((raw or "").strip())
  except ValueError:
    return None
  scheme = parsed.scheme.lower()
  if (
    scheme not in {"http", "https"}
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
  ):
    return None
  try:
    port = parsed.port
  except ValueError:
    return None
  hostname = parsed.hostname.lower()
  if ":" in hostname:
    hostname = f"[{hostname}]"
  default_port = 80 if scheme == "http" else 443
  authority = hostname if port in {None, default_port} else f"{hostname}:{port}"
  return f"{scheme}://{authority}"


def configured_browser_origins() -> set[str]:
  raw = os.getenv("CORS_ORIGINS", "")
  candidates = raw.split(",") if raw else [
    os.getenv("PUBLIC_URL", ""),
    os.getenv("VITE_API_URL", ""),
  ]
  origins = {
    normalized
    for candidate in candidates
    if (normalized := _normalize_origin(candidate)) is not None
  }
  return origins or {"http://localhost:5173"}


def set_browser_session_cookies(
  response: Response,
  created: CreatedBrowserSession,
) -> None:
  policy = cookie_policy()
  max_age = max(1, created.absolute_expires_at - int(time.time()))
  response.set_cookie(
    policy.session_name,
    created.secret,
    max_age=max_age,
    secure=policy.secure,
    httponly=True,
    samesite="lax",
    path="/",
  )
  response.set_cookie(
    policy.csrf_name,
    created.csrf_token,
    max_age=max_age,
    secure=policy.secure,
    httponly=False,
    samesite="lax",
    path="/",
  )


def clear_browser_session_cookies(response: Response) -> None:
  policy = cookie_policy()
  response.delete_cookie(
    policy.session_name,
    secure=policy.secure,
    httponly=True,
    samesite="lax",
    path="/",
  )
  response.delete_cookie(
    policy.csrf_name,
    secure=policy.secure,
    httponly=False,
    samesite="lax",
    path="/",
  )


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
  content_role: Optional[str] = None,
  adapter_id: Optional[str] = None,
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
  if content_role is not None:
    payload["content_role"] = content_role
  if adapter_id is not None:
    payload["adapter_id"] = adapter_id
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
  tool = payload.get("tool")
  if payload.get("typ") != "handoff" or tool not in {"slicer", "engraver", "open"}:
    raise HTTPException(status_code=401, detail="Invalid handoff grant")
  file_kind = payload.get("file_kind")
  if file_kind not in {"primary", "revision_primary", "supporting", "prepared"}:
    raise HTTPException(status_code=401, detail="Invalid handoff grant")
  if tool == "open":
    content_role = payload.get("content_role")
    adapter_id = payload.get("adapter_id")
    if (
      content_role != file_kind
      or content_role not in {"primary", "revision_primary", "supporting", "prepared"}
      or not isinstance(adapter_id, str)
      or not adapter_id
      or len(adapter_id) > 64
      or adapter_id == "other"
      or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in adapter_id)
    ):
      raise HTTPException(status_code=401, detail="Invalid handoff grant")
  elif file_kind not in {"primary", "prepared"} or payload.get("content_role") is not None or payload.get("adapter_id") is not None:
    raise HTTPException(status_code=401, detail="Invalid handoff grant")
  return payload


def require_auth(request: Request) -> Optional[SessionPrincipal]:
  rule = route_rule(request)
  if rule.kind is not AccessKind.SESSION or rule.permission is None:
    raise HTTPException(status_code=403, detail="Unclassified authorization path")
  if not AUTH_ENABLED:
    raise HTTPException(status_code=401, detail="Unauthorized")
  policy = cookie_policy()
  secret = request.cookies.get(policy.session_name)
  principal = authenticate_browser_session(engine, secret or "")
  if principal is None:
    raise HTTPException(status_code=401, detail="Unauthorized")
  if request.method.upper() in UNSAFE_METHODS:
    origin = _normalize_origin(request.headers.get("Origin", ""))
    if origin is None or origin not in configured_browser_origins():
      raise HTTPException(status_code=403, detail="Trusted browser origin required")
    if not csrf_matches(principal, request.headers.get("X-CSRF-Token")):
      raise HTTPException(status_code=403, detail="Valid CSRF token required")
  if not role_allows(principal.role, rule.permission):
    raise HTTPException(status_code=403, detail="Forbidden")
  return principal


require_auth.__makersvault_session_authorizer__ = True
