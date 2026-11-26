"""
Per-request id: generated (or accepted from ``X-Request-ID``), echoed in
the response header, attached to every log line, and returned in error
bodies so a client report can be matched to the server log.

Implemented as a pure ASGI middleware, outermost in the stack, so it also
catches unhandled exceptions and turns them into a generic 500 that still
carries the request id (rather than Starlette's plain-text 500).
"""

import json
import logging
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

logger = logging.getLogger(__name__)


def get_request_id() -> str:
    return _request_id.get()


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode():
            candidate = value.decode("latin-1")
            # Echoed into headers and logs: accept only a safe shape.
            return candidate if _SAFE_REQUEST_ID.match(candidate) else None
    return None


def error_body(code: str, message: str) -> dict[str, str]:
    return {"detail": message, "code": code, "request_id": get_request_id()}


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = _request_id.set(request_id)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("Unhandled error")
            if response_started:
                raise
            body = json.dumps(
                error_body("internal_error", "Internal server error.")
            ).encode()
            await send_with_request_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
        finally:
            _request_id.reset(token)


class RequestIdLogFilter(logging.Filter):
    """Adds ``record.request_id`` for the log format."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
