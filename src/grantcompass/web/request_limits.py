"""Finite ASGI request-body limits for manual notice registration."""

from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from grantcompass.documents.download import MAX_ATTACHMENT_BYTES

MANUAL_REQUEST_TOO_LARGE: Final = "manual_request_too_large"
_MULTIPART_OVERHEAD_BYTES: Final = 1024 * 1024
MAX_MANUAL_REQUEST_BYTES: Final = MAX_ATTACHMENT_BYTES + _MULTIPART_OVERHEAD_BYTES
_MANUAL_PATH: Final = "/programs/manual"


class _ScopeFields(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    type: str = ""
    method: str = ""
    path: str = ""
    headers: tuple[tuple[bytes, bytes], ...] = ()


class _RequestMessage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    type: str = ""
    body: bytes = b""


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
            try:
                request_message = _RequestMessage.model_validate(message)
            except ValidationError:
                return message
            if request_message.type == "http.request":
                received += len(request_message.body)
                if received > MAX_MANUAL_REQUEST_BYTES:
                    raise _RequestTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLargeError:
            await _send_too_large(scope, receive, send)


def _is_manual_post(scope: Scope) -> bool:
    try:
        fields = _ScopeFields.model_validate(scope)
    except ValidationError:
        return False
    return fields.type == "http" and fields.method == "POST" and fields.path == _MANUAL_PATH


def _declared_too_large(scope: Scope) -> bool:
    try:
        fields = _ScopeFields.model_validate(scope)
    except ValidationError:
        return False
    for name, value in fields.headers:
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
