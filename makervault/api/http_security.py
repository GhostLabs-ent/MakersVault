import re
from typing import Iterable, Mapping, Optional
from urllib.parse import urlparse

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


API_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=()",
    "X-Frame-Options": "DENY",
}

_HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$", re.IGNORECASE)


def _normalize_host(value: str, *, allow_wildcard: bool) -> Optional[str]:
    candidate = (value or "").strip().lower().rstrip(".")
    if not candidate:
        return None
    if candidate == "*":
        return "*" if allow_wildcard else None
    wildcard = candidate.startswith("*.")
    if wildcard:
        if not allow_wildcard:
            return None
        candidate = candidate[2:]
    if any(character in candidate for character in ("/", "\\", "@", "?", "#")):
        return None
    try:
        parsed = urlparse(candidate if "://" in candidate else f"//{candidate}")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if (
        not hostname
        or parsed.username
        or parsed.password
        or (port is not None and not 1 <= port <= 65535)
    ):
        return None
    try:
        hostname.encode("idna")
    except UnicodeError:
        return None
    if ":" not in hostname and not _HOSTNAME.fullmatch(hostname):
        return None
    return f"*.{hostname}" if wildcard else hostname


def resolve_trusted_hosts(environ: Mapping[str, str]) -> list[str]:
    explicit = environ.get("TRUSTED_HOSTS", "").strip()
    configured: list[str] = []
    if explicit:
        for raw in explicit.split(","):
            host = _normalize_host(raw, allow_wildcard=True)
            if not host:
                raise RuntimeError(f"Invalid TRUSTED_HOSTS entry: {raw.strip() or '<empty>'}")
            configured.append(host)
    else:
        public_url = environ.get("PUBLIC_URL", "").strip()
        if public_url:
            try:
                parsed = urlparse(public_url)
            except ValueError as exc:
                raise RuntimeError("PUBLIC_URL must contain a valid HTTP(S) URL") from exc
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise RuntimeError("PUBLIC_URL must contain a valid HTTP(S) URL")
            configured.append(parsed.hostname.lower().rstrip("."))

    if not configured:
        return ["*"]
    return list(dict.fromkeys([*configured, "localhost", "127.0.0.1", "::1"]))


def host_is_allowed(host_header: str, allowed_hosts: Iterable[str]) -> bool:
    candidate = _normalize_host(host_header, allow_wildcard=False)
    if not candidate:
        return False
    for allowed in allowed_hosts:
        normalized = allowed.lower().rstrip(".")
        if normalized == "*" or candidate == normalized:
            return True
        if normalized.startswith("*.") and candidate.endswith(normalized[1:]):
            return True
    return False


class HostPolicyMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: list[str]):
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            host = Headers(scope=scope).get("host", "")
            if not host_is_allowed(host, self.allowed_hosts):
                response = PlainTextResponse("Invalid host header", status_code=400)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {name.lower() for name, _ in headers}
                for name, value in API_SECURITY_HEADERS.items():
                    encoded_name = name.lower().encode("latin-1")
                    if encoded_name not in existing:
                        headers.append((encoded_name, value.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
