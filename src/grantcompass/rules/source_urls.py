"""Canonical identities for validated HTTP evidence URLs."""

from ipaddress import AddressValueError, IPv4Address, IPv6Address
from typing import Final
from urllib.parse import SplitResult, urlsplit, urlunsplit

HTTP_DEFAULT_PORT: Final = 80
HTTPS_DEFAULT_PORT: Final = 443
_ASCII_SPACE: Final = 32
_ASCII_DELETE: Final = 127
_MAX_DNS_HOST_LENGTH: Final = 253
_MAX_DNS_LABEL_LENGTH: Final = 63
_HEX_DIGITS: Final = frozenset("0123456789abcdefABCDEF")
_UNRESERVED: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def canonical_http_url(value: str) -> str | None:
    """Return a canonical identity only for a raw valid HTTP URL."""
    if _has_forbidden_ascii(value) or not _has_valid_percent_triplets(value):
        return None
    parsed = _parse_raw_http_url(value)
    if parsed is None:
        return None
    split_result, hostname, port = parsed
    canonical_host = _canonical_host(hostname)
    if canonical_host is None:
        return None
    host, is_ipv6 = canonical_host
    rendered_host = f"[{host}]" if is_ipv6 else host
    scheme = split_result.scheme.casefold()
    default_port = (scheme == "http" and port == HTTP_DEFAULT_PORT) or (
        scheme == "https" and port == HTTPS_DEFAULT_PORT
    )
    netloc = rendered_host if port is None or default_port else f"{rendered_host}:{port}"
    path = _normalize_percent_encoding(split_result.path) or "/"
    query = _normalize_percent_encoding(split_result.query)
    return urlunsplit((scheme, netloc, path, query, ""))


def _parse_raw_http_url(value: str) -> tuple[SplitResult, str, int | None] | None:
    raw_scheme, separator, _ = value.partition("://")
    if separator != "://" or raw_scheme.casefold() not in {"http", "https"}:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname
    if hostname is None:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return parsed, hostname, port


def _has_forbidden_ascii(value: str) -> bool:
    return any(
        ord(character) <= _ASCII_SPACE or ord(character) == _ASCII_DELETE for character in value
    )


def _has_valid_percent_triplets(value: str) -> bool:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            return False
        index += 3
    return True


def _normalize_percent_encoding(value: str) -> str:
    normalized: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "%":
            normalized.append(character)
            index += 1
            continue
        escape = value[index + 1 : index + 3]
        decoded = chr(int(escape, 16))
        normalized.append(decoded if decoded in _UNRESERVED else f"%{escape.upper()}")
        index += 3
    return "".join(normalized)


def _canonical_host(hostname: str) -> tuple[str, bool] | None:
    if ":" in hostname:
        return _canonical_ipv6_host(hostname)
    if "." in hostname and all(character in "0123456789." for character in hostname):
        return _canonical_ipv4_host(hostname)
    return _canonical_dns_host(hostname)


def _canonical_ipv6_host(hostname: str) -> tuple[str, bool] | None:
    try:
        return IPv6Address(hostname).compressed.casefold(), True
    except AddressValueError:
        return None


def _canonical_ipv4_host(hostname: str) -> tuple[str, bool] | None:
    try:
        return str(IPv4Address(hostname)), False
    except AddressValueError:
        return None


def _canonical_dns_host(hostname: str) -> tuple[str, bool] | None:
    try:
        ascii_host = hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return None
    host = ascii_host.removesuffix(".")
    if not host or len(host) > _MAX_DNS_HOST_LENGTH:
        return None
    if not all(_is_valid_dns_label(label) for label in host.split(".")):
        return None
    return host, False


def _is_valid_dns_label(label: str) -> bool:
    if not label or len(label) > _MAX_DNS_LABEL_LENGTH:
        return False
    if not label[0].isalnum() or not label[-1].isalnum():
        return False
    if not all(character.isalnum() or character == "-" for character in label):
        return False
    if label.startswith("xn--"):
        try:
            _ = label.encode("ascii").decode("idna")
        except UnicodeError:
            return False
    return True
