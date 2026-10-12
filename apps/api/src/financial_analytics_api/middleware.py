from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from financial_analytics_api.context import bind_request_context, reset_request_context

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
logger = logging.getLogger(__name__)


def _safe_identifier(candidate: str | None) -> str | None:
    if candidate is not None and SAFE_ID_PATTERN.fullmatch(candidate):
        return candidate
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = MutableHeaders(scope=scope)
        request_id = _safe_identifier(request_headers.get(REQUEST_ID_HEADER)) or str(uuid4())
        correlation_id = _safe_identifier(request_headers.get(CORRELATION_ID_HEADER)) or request_id
        scope.setdefault("state", {})["request_id"] = request_id
        scope["state"]["correlation_id"] = correlation_id
        tokens = bind_request_context(request_id, correlation_id)
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
                response_headers[CORRELATION_ID_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http_request",
                    "http_method": scope["method"],
                    "http_status": status_code,
                },
            )
            reset_request_context(tokens)


ASGIMiddleware = Callable[[Scope, Receive, Send], Awaitable[None]]
