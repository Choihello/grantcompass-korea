"""Tuned httpx2 client factory for outbound source requests."""

import logging
import re
import socket
from typing import Final, final, override
from urllib.parse import unquote

import httpx2

_QUERY_PAIR: Final = re.compile(r"([?&])([^=&\s]+)=([^&\s\"']*)")
_CREDENTIAL_QUERY_KEYS: Final = frozenset({"servicekey", "crtfckey"})


def _redact_query_pair(match: re.Match[str]) -> str:
    separator, encoded_key, _value = match.groups()
    if unquote(encoded_key).casefold() not in _CREDENTIAL_QUERY_KEYS:
        return match.group(0)
    return f"{separator}{encoded_key}=REDACTED"


def _redact_query_credentials(message: str) -> str:
    return _QUERY_PAIR.sub(_redact_query_pair, message)


@final
class _ServiceKeyFilter(logging.Filter):
    """Redact official-source query credentials without mutable request state."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _redact_query_credentials(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


logging.getLogger("httpx2").addFilter(_ServiceKeyFilter())


def create_async_client() -> httpx2.AsyncClient:
    """Create an owned async client with the project transport defaults."""
    limits = httpx2.Limits(
        max_connections=200,
        max_keepalive_connections=40,
        keepalive_expiry=30.0,
    )
    timeout = httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
    transport = httpx2.AsyncHTTPTransport(
        http2=True,
        retries=3,
        limits=limits,
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    return httpx2.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=True,
    )
