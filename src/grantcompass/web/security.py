"""Local web trust-boundary middleware."""

from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest, digest
from secrets import token_urlsafe
from typing import Final, final
from urllib.parse import parse_qs

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSRF_COOKIE: Final = "grantcompass_csrf"
_CSRF_FIELD = b'name="csrf_token"\r\n\r\n'
_FRAME_POLICY = "frame-ancestors 'none'"


@final
class SecurityBoundaryMiddleware:
    """Enforce same-origin signed form mutations and response framing policy."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: tuple[str, ...],
        signing_secret: bytes,
    ) -> None:
        """Bind one configured local-origin and signing boundary."""
        self._app = app
        self._allowed_origins = frozenset(allowed_origins)
        self._signing_secret = signing_secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Validate one ASGI request and secure its response."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        cookie_token = _cookie_value(headers.get("cookie", ""), CSRF_COOKIE)
        if cookie_token is not None and _valid_token(cookie_token, self._signing_secret):
            token = cookie_token
        else:
            token = _new_token(self._signing_secret)
        scope.setdefault("state", {})["csrf_token"] = token
        body = b""
        if scope["method"] == "POST":
            if headers.get("origin") not in self._allowed_origins:
                await _plain_response(send, 403, b"origin_not_allowed")
                return
            body = await _read_body(receive)
            submitted = headers.get("x-csrf-token") or _form_token(
                headers.get("content-type", ""),
                body,
            )
            if submitted is None:
                await _plain_response(send, 403, b"csrf_invalid")
                return
            if not compare_digest(submitted, token) or not _valid_token(
                submitted,
                self._signing_secret,
            ):
                await _plain_response(send, 403, b"csrf_invalid")
                return
            receive = _replay(body)

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Content-Security-Policy"] = _FRAME_POLICY
                response_headers["X-Frame-Options"] = "DENY"
                if cookie_token != token:
                    response_headers.append(
                        "Set-Cookie",
                        f"{CSRF_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict",
                    )
            await send(message)

        await self._app(scope, receive, secure_send)


def _new_token(secret: bytes) -> str:
    nonce = token_urlsafe(32)
    signature = urlsafe_b64encode(digest(secret, nonce.encode(), sha256)).rstrip(b"=").decode()
    return f"{nonce}.{signature}"


def _valid_token(token: str | None, secret: bytes) -> bool:
    if token is None:
        return False
    try:
        nonce, signature = token.split(".", 1)
    except ValueError:
        return False
    expected = urlsafe_b64encode(digest(secret, nonce.encode(), sha256)).rstrip(b"=").decode()
    return compare_digest(signature, expected)


def _cookie_value(raw_cookie: str, name: str) -> str | None:
    for item in raw_cookie.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator and key == name:
            return value
    return None


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    more_body = True
    while more_body:
        message = await receive()
        match message:
            case {"type": "http.request", "body": bytes(body), "more_body": bool(more)}:
                chunks.append(body)
                more_body = more
            case {"type": "http.request", "body": bytes(body)}:
                chunks.append(body)
                more_body = False
            case {"type": "http.request"}:
                more_body = False
            case _:
                continue
    return b"".join(chunks)


def _replay(body: bytes) -> Receive:
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _form_token(content_type: str, body: bytes) -> str | None:
    if content_type.startswith("application/x-www-form-urlencoded"):
        values = parse_qs(body.decode("utf-8", errors="strict"), keep_blank_values=True).get(
            "csrf_token"
        )
        return values[0] if values else None
    if content_type.startswith("multipart/form-data"):
        start = body.find(_CSRF_FIELD)
        if start < 0:
            return None
        value_start = start + len(_CSRF_FIELD)
        value_end = body.find(b"\r\n", value_start)
        if value_end < 0:
            return None
        return body[value_start:value_end].decode("ascii", errors="strict")
    return None


async def _plain_response(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"content-security-policy", _FRAME_POLICY.encode()),
                (b"x-frame-options", b"DENY"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


__all__ = ["CSRF_COOKIE", "SecurityBoundaryMiddleware"]
