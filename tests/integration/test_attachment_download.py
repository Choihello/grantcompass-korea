from dataclasses import dataclass, field

import anyio
import httpx2
import pytest
from pydantic import HttpUrl

from grantcompass.documents.download import AttachmentDownloader, DownloadLimits
from grantcompass.documents.errors import DocumentIngestError
from grantcompass.domain.programs import AttachmentRef


@dataclass(frozen=True, slots=True)
class StaticResolver:
    addresses: tuple[str, ...]
    hosts: list[str] = field(default_factory=list)

    async def resolve(self, host: str) -> tuple[str, ...]:
        self.hosts.append(host)
        return self.addresses


@dataclass(frozen=True, slots=True)
class SlowResolver:
    async def resolve(self, host: str) -> tuple[str, ...]:
        _ = host
        await anyio.sleep(1)
        return ("93.184.216.34",)


def attachment(url: str = "https://files.example.test/notice.pdf") -> AttachmentRef:
    return AttachmentRef(filename="notice.pdf", download_url=HttpUrl(url))


@pytest.mark.anyio
async def test_downloader_blocks_literal_private_target() -> None:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: httpx2.Response(200)))
    downloader = AttachmentDownloader(client, StaticResolver(("93.184.216.34",)))

    with pytest.raises(DocumentIngestError) as caught:
        _ = await downloader.fetch(attachment("https://127.0.0.1/notice.pdf"))

    assert caught.value.code == "unsafe_download_target"
    await client.aclose()


@pytest.mark.anyio
async def test_downloader_blocks_mixed_ipv4_and_ipv6_dns() -> None:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: httpx2.Response(200)))
    resolver = StaticResolver(("93.184.216.34", "fd00::1"))
    downloader = AttachmentDownloader(client, resolver)

    with pytest.raises(DocumentIngestError) as caught:
        _ = await downloader.fetch(attachment())

    assert caught.value.code == "unsafe_download_target"
    await client.aclose()


@pytest.mark.anyio
async def test_downloader_rechecks_redirect_and_strips_credentials() -> None:
    seen_headers: list[httpx2.Headers] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen_headers.append(request.headers)
        return httpx2.Response(302, headers={"Location": "https://127.0.0.1/private.pdf"})

    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(respond),
        headers={"Authorization": "Bearer secret", "Cookie": "session=secret"},
    )
    downloader = AttachmentDownloader(client, StaticResolver(("93.184.216.34",)))

    with pytest.raises(DocumentIngestError) as caught:
        _ = await downloader.fetch(attachment())

    assert caught.value.code == "unsafe_download_target"
    assert "authorization" not in seen_headers[0]
    assert "cookie" not in seen_headers[0]
    await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("headers", "content", "code"),
    [
        (
            {"Content-Length": "11", "Content-Type": "application/pdf"},
            b"%PDF-12345",
            "attachment_too_large",
        ),
        ({"Content-Type": "application/pdf"}, b"%PDF-123456", "attachment_too_large"),
        ({"Content-Type": "text/plain"}, b"%PDF-1.4", "invalid_attachment_type"),
        ({"Content-Type": "application/pdf"}, b"not-pdf", "invalid_attachment_type"),
    ],
)
async def test_downloader_rejects_size_and_type_mismatch(
    headers: dict[str, str], content: bytes, code: str
) -> None:
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(200, headers=headers, content=content, request=request)
        )
    )
    downloader = AttachmentDownloader(
        client,
        StaticResolver(("93.184.216.34",)),
        DownloadLimits(max_bytes=10),
    )

    with pytest.raises(DocumentIngestError) as caught:
        _ = await downloader.fetch(attachment())

    assert caught.value.code == code
    await client.aclose()


@pytest.mark.anyio
async def test_downloader_classifies_404_as_missing() -> None:
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(404, request=request))
    )
    downloader = AttachmentDownloader(client, StaticResolver(("93.184.216.34",)))

    with pytest.raises(DocumentIngestError) as caught:
        _ = await downloader.fetch(attachment())

    assert caught.value.code == "attachment_missing"
    await client.aclose()


@pytest.mark.anyio
async def test_downloader_maps_dns_timeout_to_safe_failure() -> None:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: httpx2.Response(200)))
    downloader = AttachmentDownloader(
        client,
        SlowResolver(),
        DownloadLimits(dns_timeout_seconds=0.01),
    )

    with pytest.raises(DocumentIngestError) as caught:
        _ = await downloader.fetch(attachment())

    assert caught.value.code == "download_failed"
    await client.aclose()


@pytest.mark.anyio
async def test_downloader_validates_each_redirect_hop() -> None:
    locations = iter(
        [
            "https://cdn-one.example.test/notice.pdf",
            "https://cdn-two.example.test/notice.pdf",
        ]
    )

    def respond(request: httpx2.Request) -> httpx2.Response:
        try:
            return httpx2.Response(302, headers={"Location": next(locations)}, request=request)
        except StopIteration:
            return httpx2.Response(
                200,
                headers={"Content-Type": "application/pdf"},
                content=b"%PDF-1.4",
                request=request,
            )

    resolver = StaticResolver(("93.184.216.34",))
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))

    content = await AttachmentDownloader(client, resolver).fetch(attachment())

    assert content == b"%PDF-1.4"
    assert resolver.hosts == [
        "files.example.test",
        "cdn-one.example.test",
        "cdn-two.example.test",
    ]
    await client.aclose()


@pytest.mark.anyio
async def test_downloader_pins_validated_ip_without_losing_tls_hostname() -> None:
    # Given: validation resolves a public address while a second hostname lookup could rebind.
    observed: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        observed.append(request)
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            content=b"%PDF-1.4",
            request=request,
        )

    resolver = StaticResolver(("93.184.216.34",))
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))

    # When: the validated target crosses the actual transport boundary.
    content = await AttachmentDownloader(client, resolver).fetch(attachment())

    # Then: transport connects to that exact IP while Host/SNI retain certificate identity.
    assert content == b"%PDF-1.4"
    assert len(observed) == 1
    assert observed[0].url.host == "93.184.216.34"
    assert observed[0].headers["host"] == "files.example.test"
    assert observed[0].extensions["sni_hostname"] == "files.example.test"
    assert resolver.hosts == ["files.example.test"]
    await client.aclose()
