"""Finite ASGI request-body limits for manual notice registration."""

from typing import Final, cast

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from grantcompass.documents.download import MAX_ATTACHMENT_BYTES

MANUAL_REQUEST_TOO_LARGE: Final = "manual_request_too_large"
_MULTIPART_OVERHEAD_BYTES: Final = 1024 * 1024
MAX_MANUAL_REQUEST_BYTES: Final = MAX_ATTACHMENT_BYTES + _MULTIPART_OVERHEAD_BYTES
_MANUAL_PATH: Final = "/programs/manual"
_HEADER_PAIR_SIZE: Final = 2


class _RequestTooLargeError(Exception):
    pass


class ManualRequestLimitMiddleware:
    """Reject oversized manual multipart bodies before Starlette parses them."""

    def __init__(self, app: ASGIApp) -> None:
        """Store the downstream ASGI application."""
        self.app: ASGIApp = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Guard receive messages before manual form parsing begins."""
        if not _is_manual_post(scope):
            await self.app(scope, receive, send)
            return
        if _declared_too_large(scope):
            await _send_too_large(scope, receive, send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                body = cast("object", message.get("body", b""))
                if isinstance(body, bytes):
                    received += len(body)
                if received > MAX_MANUAL_REQUEST_BYTES:
                    raise _RequestTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLargeError:
            await _send_too_large(scope, receive, send)


def _is_manual_post(scope: Scope) -> bool:
    scope_type = cast("object", scope.get("type"))
    method = cast("object", scope.get("method"))
    path = cast("object", scope.get("path"))
    return scope_type == "http" and method == "POST" and path == _MANUAL_PATH


def _declared_too_large(scope: Scope) -> bool:
    raw_headers = cast("object", scope.get("headers"))
    if not isinstance(raw_headers, list):
        return False
    headers = cast("list[object]", raw_headers)
    for raw_header in headers:
        if not isinstance(raw_header, tuple):
            continue
        header = cast("tuple[object, ...]", raw_header)
        if len(header) != _HEADER_PAIR_SIZE:
            continue
        name, value = header
        if not isinstance(name, bytes) or not isinstance(value, bytes):
            continue
        if name == b"content-length":
            try:
                return int(value) > MAX_MANUAL_REQUEST_BYTES
            except ValueError:
                return False
    return False


async def _send_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse(MANUAL_REQUEST_TOO_LARGE, status_code=413)(scope, receive, send)


__all__ = [
    "MANUAL_REQUEST_TOO_LARGE",
    "MAX_MANUAL_REQUEST_BYTES",
    "ManualRequestLimitMiddleware",
]
