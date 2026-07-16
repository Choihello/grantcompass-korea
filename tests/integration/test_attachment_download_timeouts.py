from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import override

import anyio
import httpx2
import pytest
from pydantic import HttpUrl

from grantcompass.documents.download import AttachmentDownloader, DownloadLimits
from grantcompass.documents.errors import DocumentIngestError
from grantcompass.domain.programs import AttachmentRef


@dataclass(frozen=True, slots=True)
class PublicResolver:
    async def resolve(self, host: str) -> tuple[str, ...]:
        _ = host
        return ("93.184.216.34",)


@dataclass(frozen=True, slots=True)
class StalledStream(httpx2.AsyncByteStream):
    closed: list[bool]

    @override
    async def __aiter__(self) -> AsyncIterator[bytes]:
        await anyio.sleep_forever()
        yield b""

    @override
    async def aclose(self) -> None:
        self.closed.append(True)


def _attachment() -> AttachmentRef:
    return AttachmentRef(
        filename="notice.pdf",
        download_url=HttpUrl("https://files.example.test/notice.pdf"),
    )


def _limits() -> DownloadLimits:
    return DownloadLimits(
        connect_timeout_seconds=0.01,
        read_timeout_seconds=0.01,
        fetch_timeout_seconds=0.02,
    )


@pytest.mark.anyio
async def test_downloader_bounds_stalled_send_with_project_deadline() -> None:
    # Given: a caller client with no timeout and a transport stalled before response.
    async def stalled_send(request: httpx2.Request) -> httpx2.Response:
        _ = request
        await anyio.sleep_forever()
        return httpx2.Response(200)

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(stalled_send), timeout=None
    ) as client:
        downloader = AttachmentDownloader(client, PublicResolver(), _limits())

        # When: the project-owned whole-fetch deadline expires.
        with pytest.raises(DocumentIngestError) as caught:
            _ = await downloader.fetch(_attachment())

    # Then: a finite timeout is exposed independently of caller configuration.
    assert caught.value.code == "download_timeout"


@pytest.mark.anyio
async def test_downloader_bounds_stalled_stream_and_closes_response() -> None:
    # Given: a response whose body never yields a first byte.
    stream = StalledStream(closed=[])

    def stalled_read(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/pdf"},
            stream=stream,
            request=request,
        )

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(stalled_read), timeout=None
    ) as client:
        downloader = AttachmentDownloader(client, PublicResolver(), _limits())

        # When: the project-owned read/whole-fetch deadline expires.
        with pytest.raises(DocumentIngestError) as caught:
            _ = await downloader.fetch(_attachment())

    # Then: the timeout is finite and the acquired response is closed.
    assert caught.value.code == "download_timeout"
    assert stream.closed == [True]
