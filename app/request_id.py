"""Request ID: a uuid4 created the moment a request arrives, for tracking, logging and auditing.

RequestIdMiddleware is the outermost middleware, so the ID exists before any other code runs.
It is available as:
- get_request_id() anywhere in the request (a ContextVar; Starlette copies the context into the
  threadpool that runs sync endpoints, so services see it too)
- request.state.request_id
- the response header named by request_id.header in app.properties (default X-Request-ID)

UnhandledErrorMiddleware sits inside CORSMiddleware and turns an unhandled error into a JSON 500
that carries the request ID; being inside CORS, that 500 also gets the CORS headers a browser
needs to read it.
"""

import json
import logging
import time
import uuid
from contextvars import ContextVar
from urllib.parse import quote

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """The current request's ID, or None outside a request."""
    return _request_id.get()


def _loggable_path(scope: Scope) -> str:
    """The path percent-encoded again (scope["path"] is decoded), so a client cannot put line
    breaks or other control characters into a log line."""
    return quote(scope.get("path", ""), safe="/")


class RequestIdMiddleware:
    """Pure ASGI middleware: one new uuid4 per HTTP request, the response header, and the
    request's first and last log lines."""

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self.header = header_name.lower().encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = _request_id.set(request_id)
        started = time.perf_counter()
        method, path = scope.get("method", ""), _loggable_path(scope)
        logger.info("Request received: %s %s", method, path)
        status = 500

        async def send_with_header(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != self.header]
                headers.append((self.header, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        except Exception:
            logger.exception("Request failed with an unhandled error: %s %s", method, path)
            raise  # the server logs it too; UnhandledErrorMiddleware has already answered 500
        finally:
            ms = round((time.perf_counter() - started) * 1000)
            logger.info("Request finished: %s %s -> %d in %d ms", method, path, status, ms)
            _request_id.reset(token)


class UnhandledErrorMiddleware:
    """Answers an unhandled error with {"detail": "Internal server error", "request_id": ...}.

    Starlette's own 500 is built outside every middleware, so it would carry neither the request ID
    nor CORS headers. The error is re-raised afterwards so it is still logged; the server then sees
    that a response was already sent and sends nothing more.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            if not response_started:
                body = json.dumps(
                    {"detail": "Internal server error", "request_id": get_request_id()}
                ).encode()
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())],
                })
                await send({"type": "http.response.body", "body": body})
            raise
