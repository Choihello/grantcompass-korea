"""SSRF-resistant bounded attachment downloader using a caller-owned client."""

import socket
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import PurePath
from typing import Final, Protocol
from urllib.parse import unquote, urljoin, urlsplit
from zipfile import BadZipFile, ZipFile

import anyio
import httpx2
from anyio.to_thread import run_sync

from grantcompass.documents.errors import DocumentIngestError, DocumentIngestErrorCode
from grantcompass.domain.programs import AttachmentRef

MAX_ATTACHMENT_BYTES: Final = 50 * 1024 * 1024
REDIRECT_CODES: Final = frozenset({301, 302, 303, 307, 308})
SAFE_REQUEST_HEADERS: Final = {"Accept": "application/pdf, application/hwp+zip"}
HWPX_MIMETYPE: Final = b"application/hwp+zip"
HTTP_OK: Final = 200
HTTP_NOT_FOUND: Final = 404
CONTROL_CHARACTER_LIMIT: Final = 32
MAX_FILENAME_LENGTH: Final = 255
ATTACHMENT_MISSING: Final[DocumentIngestErrorCode] = "attachment_missing"
ATTACHMENT_TOO_LARGE: Final[DocumentIngestErrorCode] = "attachment_too_large"
DOWNLOAD_FAILED: Final[DocumentIngestErrorCode] = "download_failed"
DOWNLOAD_TIMEOUT: Final[DocumentIngestErrorCode] = "download_timeout"
INVALID_ATTACHMENT_TYPE: Final[DocumentIngestErrorCode] = "invalid_attachment_type"
REDIRECT_LIMIT: Final[DocumentIngestErrorCode] = "redirect_limit"
REDIRECT_LOOP: Final[DocumentIngestErrorCode] = "redirect_loop"
UNSAFE_DOWNLOAD_TARGET: Final[DocumentIngestErrorCode] = "unsafe_download_target"


@dataclass(frozen=True, slots=True)
class DownloadLimits:
    """Hard byte, redirect, DNS, transport, and whole-fetch budgets."""

    max_bytes: int = MAX_ATTACHMENT_BYTES
    max_redirects: int = 3
    dns_timeout_seconds: float = 5.0
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    fetch_timeout_seconds: float = 60.0


DEFAULT_DOWNLOAD_LIMITS: Final = DownloadLimits()


class DnsResolver(Protocol):
    """Resolve every target hop to all candidate network addresses."""

    async def resolve(self, host: str) -> tuple[str, ...]:
        """Return every address advertised for the host within a bounded time."""
        ...


class SystemDnsResolver:
    """AnyIO thread-bound system resolver for production downloads."""

    async def resolve(self, host: str) -> tuple[str, ...]:
        """Resolve without blocking the caller's async runtime."""

        def lookup() -> tuple[str, ...]:
            records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            addresses: set[str] = set()
            for record in records:
                value = record[4][0]
                if isinstance(value, str):
                    addresses.add(value)
            return tuple(sorted(addresses))

        return await run_sync(lookup, abandon_on_cancel=True)


class AttachmentDownloader:
    """Fetch official PDF/HWPX bytes across manually validated HTTPS hops.

    DNS is revalidated for every redirect. The transport still resolves the hostname
    independently, so deployments needing DNS-rebinding resistance must pin the validated
    address in a custom transport or enforce equivalent egress controls.
    """

    def __init__(
        self,
        client: httpx2.AsyncClient,
        resolver: DnsResolver,
        limits: DownloadLimits = DEFAULT_DOWNLOAD_LIMITS,
    ) -> None:
        """Bind a caller-owned client, resolver, and immutable safety limits."""
        self._client: httpx2.AsyncClient = client
        self._resolver: DnsResolver = resolver
        self._limits: DownloadLimits = limits

    async def fetch(self, attachment: AttachmentRef) -> bytes:
        """Download exact bytes without forwarding caller credentials or headers."""
        try:
            with anyio.fail_after(self._limits.fetch_timeout_seconds):
                return await self._fetch_with_redirects(attachment)
        except TimeoutError:
            raise DocumentIngestError(DOWNLOAD_TIMEOUT) from None

    async def _fetch_with_redirects(self, attachment: AttachmentRef) -> bytes:
        filename = self._sanitize_filename(attachment.filename)
        expected_extension = PurePath(filename).suffix.casefold()
        if expected_extension not in {".pdf", ".hwpx"}:
            raise DocumentIngestError(INVALID_ATTACHMENT_TYPE)
        url = str(attachment.download_url)
        visited: set[str] = set()
        redirects = 0
        while True:
            normalized_url = await self._validate_target(url, expected_extension)
            if normalized_url in visited:
                raise DocumentIngestError(REDIRECT_LOOP)
            visited.add(normalized_url)
            response = await self._send(normalized_url)
            try:
                if response.status_code == HTTP_NOT_FOUND:
                    raise DocumentIngestError(ATTACHMENT_MISSING)
                if response.status_code in REDIRECT_CODES:
                    if redirects >= self._limits.max_redirects:
                        raise DocumentIngestError(REDIRECT_LIMIT)
                    location = self._headers(response).get("location")
                    if location is None:
                        raise DocumentIngestError(DOWNLOAD_FAILED)
                    redirects += 1
                    url = urljoin(normalized_url, location)
                    continue
                if response.status_code != HTTP_OK:
                    raise DocumentIngestError(DOWNLOAD_FAILED)
                self._validate_response_headers(response, expected_extension)
                content = await self._read_bounded(response)
                self._validate_magic(content, expected_extension)
                return content
            finally:
                with anyio.CancelScope(shield=True):
                    await response.aclose()

    async def _send(self, url: str) -> httpx2.Response:
        request = httpx2.Request("GET", url, headers=SAFE_REQUEST_HEADERS)
        timeout = httpx2.Timeout(
            connect=self._limits.connect_timeout_seconds,
            read=self._limits.read_timeout_seconds,
            write=self._limits.read_timeout_seconds,
            pool=self._limits.connect_timeout_seconds,
        )
        request.extensions["timeout"] = timeout.as_dict()
        try:
            return await self._client.send(
                request,
                stream=True,
                auth=None,
                follow_redirects=False,
            )
        except httpx2.TimeoutException:
            raise DocumentIngestError(DOWNLOAD_TIMEOUT) from None
        except httpx2.TransportError:
            raise DocumentIngestError(DOWNLOAD_FAILED) from None

    async def _validate_target(self, url: str, expected_extension: str) -> str:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise DocumentIngestError(UNSAFE_DOWNLOAD_TARGET) from None
        decoded_path = unquote(parsed.path)
        valid_path = (
            bool(parsed.path)
            and not any(
                character.isspace() or ord(character) < CONTROL_CHARACTER_LIMIT
                for character in decoded_path
            )
            and "\\" not in decoded_path
        )
        if (
            parsed.scheme.casefold() != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or bool(parsed.fragment)
            or not valid_path
            or PurePath(decoded_path).suffix.casefold() != expected_extension
        ):
            raise DocumentIngestError(UNSAFE_DOWNLOAD_TARGET)
        try:
            host = parsed.hostname.encode("idna").decode("ascii")
        except UnicodeError:
            raise DocumentIngestError(UNSAFE_DOWNLOAD_TARGET) from None
        addresses = await self._addresses(host)
        if not addresses or any(not address.is_global for address in addresses):
            raise DocumentIngestError(UNSAFE_DOWNLOAD_TARGET)
        return parsed.geturl()

    async def _addresses(self, host: str) -> tuple[IPv4Address | IPv6Address, ...]:
        try:
            return (ip_address(host),)
        except ValueError:
            try:
                with anyio.fail_after(self._limits.dns_timeout_seconds):
                    values = await self._resolver.resolve(host)
            except (OSError, TimeoutError):
                raise DocumentIngestError(DOWNLOAD_FAILED) from None
            try:
                return tuple(ip_address(value) for value in values)
            except ValueError:
                raise DocumentIngestError(UNSAFE_DOWNLOAD_TARGET) from None

    def _validate_response_headers(
        self,
        response: httpx2.Response,
        expected_extension: str,
    ) -> None:
        headers = self._headers(response)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                raise DocumentIngestError(DOWNLOAD_FAILED) from None
            if declared_size < 0 or declared_size > self._limits.max_bytes:
                raise DocumentIngestError(ATTACHMENT_TOO_LARGE)
        media_type = headers.get("content-type", "").split(";", 1)[0].casefold()
        expected_media = {
            ".pdf": {"application/pdf"},
            ".hwpx": {"application/hwp+zip", "application/zip"},
        }[expected_extension]
        if media_type not in expected_media:
            raise DocumentIngestError(INVALID_ATTACHMENT_TYPE)

    async def _read_bounded(self, response: httpx2.Response) -> bytes:
        parts: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._limits.max_bytes:
                raise DocumentIngestError(ATTACHMENT_TOO_LARGE)
            parts.append(chunk)
        return b"".join(parts)

    @staticmethod
    def _headers(response: httpx2.Response) -> Mapping[str, str]:
        return response.headers

    @staticmethod
    def _validate_magic(content: bytes, extension: str) -> None:
        if extension == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise DocumentIngestError(INVALID_ATTACHMENT_TYPE)
            return
        try:
            with ZipFile(BytesIO(content)) as archive:
                info = archive.getinfo("mimetype")
                if info.file_size > len(HWPX_MIMETYPE):
                    raise DocumentIngestError(INVALID_ATTACHMENT_TYPE)
                with archive.open(info) as mimetype_file:
                    mimetype = mimetype_file.read(len(HWPX_MIMETYPE) + 1)
                if mimetype != HWPX_MIMETYPE:
                    raise DocumentIngestError(INVALID_ATTACHMENT_TYPE)
        except (BadZipFile, KeyError):
            raise DocumentIngestError(INVALID_ATTACHMENT_TYPE) from None

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        candidate = filename.strip()
        if (
            not candidate
            or PurePath(candidate).name != candidate
            or len(candidate) > MAX_FILENAME_LENGTH
            or any(character.isspace() and character != " " for character in candidate)
        ):
            raise DocumentIngestError(INVALID_ATTACHMENT_TYPE)
        return candidate
