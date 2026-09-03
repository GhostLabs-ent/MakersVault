"""Outcome-aware audit middleware that never inspects request or response bodies."""

from __future__ import annotations

import logging
import uuid

from fastapi import Request
from sqlalchemy.engine import Engine
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import audit_service
from audit_service import audit_action_for_route, audit_context_from_request, result_for_status
from authorization import route_rule


class AuditMiddleware:
    def __init__(self, app: ASGIApp, *, engine: Engine):
        self.app = app
        self.engine = engine
        self.logger = logging.getLogger("makersvault.security")

    def _write_sync(self, request: Request, status_code: int) -> bool:
        try:
            rule = route_rule(request)
        except Exception:
            return True
        route = request.scope.get("route")
        route_path = getattr(route, "path", None)
        if not isinstance(route_path, str):
            return True
        action = audit_action_for_route(request.method, route_path, rule)
        if not action or getattr(request.state, "audit_recorded", False):
            return True
        if getattr(request.state, "audit_attempted", False):
            return False
        request.state.audit_attempted = True
        context = audit_context_from_request(request, action=action)
        try:
            audit_service.record_audit_event(
                self.engine,
                context,
                result=result_for_status(status_code),
                status_code=status_code,
            )
            request.state.audit_recorded = True
            return True
        except Exception:
            self.logger.exception(
                "audit_write_failed correlation_id=%s action=%s status_code=%s",
                context.correlation_id,
                context.action,
                status_code,
            )
            return False

    async def _write(self, request: Request, status_code: int) -> bool:
        return await run_in_threadpool(self._write_sync, request, status_code)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = str(uuid.uuid4())
        scope.setdefault("state", {})["audit_correlation_id"] = correlation_id
        request = Request(scope)
        suppress_downstream_body = False

        async def send_audited(message: Message) -> None:
            nonlocal suppress_downstream_body
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                if not await self._write(request, status_code):
                    body = b'{"detail":"Operation completed but audit recording failed"}'
                    if status_code >= 400:
                        body = b'{"detail":"Audit recording failed"}'
                    preserved = [
                        (name, value)
                        for name, value in message.get("headers", [])
                        if name.lower()
                        in {
                            b"access-control-allow-origin",
                            b"access-control-allow-credentials",
                            b"vary",
                        }
                    ]
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 500,
                            "headers": [
                                *preserved,
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode("ascii")),
                                (b"cache-control", b"private, no-store"),
                                (
                                    b"x-correlation-id",
                                    correlation_id.encode("ascii"),
                                ),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    suppress_downstream_body = True
                    return
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-correlation-id", correlation_id.encode("ascii"))
                )
                message["headers"] = headers
            elif suppress_downstream_body and message["type"] == "http.response.body":
                return
            await send(message)

        try:
            await self.app(scope, receive, send_audited)
        except Exception:
            await self._write(request, 500)
            raise
