"""One request id per request: read or generate, expose on state, echo on the response.

The id is what ties an audit row to the request that caused it, so it has to
exist before any route dependency runs. A pure ASGI middleware is the only place
that sees every request, public ones (`/login` has no permission dependency)
included; a per-route dependency would not.

`X-Request-ID` is untrusted input: a value that does not match `ALLOWED` (junk,
500 characters, a control byte) is replaced with a generated id, so a hostile
client cannot choose what lands in the audit table or the logs. Absent is normal
and gets a generated id too; the value is always echoed back, including on 4xx
and 5xx, so a client can quote it in a bug report.
"""

import re
import uuid
from typing import Optional

from fastapi import Request

HEADER = "X-Request-ID"
ALLOWED = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
STATE_KEY = "request_id"

_ENCODED_HEADER = HEADER.lower().encode("latin-1")


def get(request: Request) -> str:
    """The id this request was assigned; "-" only if the middleware never ran."""
    return getattr(request.state, STATE_KEY, "-")


def _value_from_headers(headers) -> Optional[str]:
    """The first sane X-Request-ID header, or None when absent or hostile."""
    for name, value in headers:
        if name.lower() == _ENCODED_HEADER:
            candidate = value.decode("latin-1")
            if ALLOWED.fullmatch(candidate):
                return candidate
            return None
    return None


def _has_header(headers) -> bool:
    return any(name.lower() == _ENCODED_HEADER for name, _value in headers)


class RequestIDMiddleware:
    """Assign the id on the request scope and echo it on every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        value = _value_from_headers(scope.get("headers") or []) or uuid.uuid4().hex
        scope.setdefault("state", {})[STATE_KEY] = value

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                # Never clobber a header the application set under this name.
                if not _has_header(headers):
                    headers.append((_ENCODED_HEADER, value.encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_request_id)
