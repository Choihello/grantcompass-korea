from dataclasses import dataclass

import pytest
from starlette.types import Message, Receive, Scope, Send

from grantcompass.documents.download import MAX_ATTACHMENT_BYTES
from grantcompass.web.request_limits import (
    MANUAL_REQUEST_TOO_LARGE,
    MAX_MANUAL_REQUEST_BYTES,
    ManualRequestLimitMiddleware,
)

pytestmark = pytest.mark.anyio


_RECEIVE_AFTER_FAST_REJECTION = "receive must not run after a fast Content-Length rejection"


@dataclass(slots=True)
class _BodyConsumer:
    calls: int = 0

    async def __call__(self, _: Scope, receive: Receive, __: Send) -> None:
        while True:
            self.calls += 1
            message = await receive()
            if not message.get("more_body", False):
                return


def _scope(headers: list[tuple[bytes, bytes]]) -> Scope:
    return {"type": "http", "method": "POST", "path": "/programs/manual", "headers": headers}


async def test_content_length_over_limit_rejects_before_the_app_receives() -> None:
    # Given: a manual registration declares a body beyond the central ceiling.
    app = _BodyConsumer()
    sent: list[Message] = []

    async def receive() -> Message:
        raise AssertionError(_RECEIVE_AFTER_FAST_REJECTION)

    async def send(message: Message) -> None:
        sent.append(message)

    # When: ASGI dispatches the request.
    await ManualRequestLimitMiddleware(app)(
        _scope([(b"content-length", str(MAX_MANUAL_REQUEST_BYTES + 1).encode())]), receive, send
    )

    # Then: the parser/app never receives bytes and the client gets a stable 413.
    assert app.calls == 0
    assert sent[0].get("status") == 413
    assert MANUAL_REQUEST_TOO_LARGE.encode() in sent[1].get("body", b"")


async def test_streaming_overrun_stops_receiving_after_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a client lies about Content-Length then sends an overrun plus one extra chunk.
    monkeypatch.setattr("grantcompass.web.request_limits.MAX_MANUAL_REQUEST_BYTES", 5)
    app = _BodyConsumer()
    sent: list[Message] = []
    messages: tuple[Message, ...] = (
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"456", "more_body": True},
        {"type": "http.request", "body": b"must-not-be-read", "more_body": False},
    )
    iterator = iter(messages)
    received = 0

    async def receive() -> Message:
        nonlocal received
        received += 1
        return next(iterator)

    async def send(message: Message) -> None:
        sent.append(message)

    # When: the guarded parser consumes the declared-small stream.
    await ManualRequestLimitMiddleware(app)(_scope([(b"content-length", b"1")]), receive, send)

    # Then: it rejects at the second chunk and never pulls the remaining body.
    assert received == 2
    assert app.calls == 2
    assert sent[0].get("status") == 413


def test_request_ceiling_allows_attachment_bytes_and_bounded_multipart_overhead() -> None:
    # Given/When: request policy is inspected without a client-provided Content-Length.
    # Then: one maximum legal attachment is not rejected solely for multipart framing bytes.
    assert MAX_MANUAL_REQUEST_BYTES > MAX_ATTACHMENT_BYTES
