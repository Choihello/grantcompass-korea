import io
import logging

import anyio
import httpx2
import pytest

from grantcompass.http import create_async_client


@pytest.mark.anyio
async def test_concurrent_http_logs_redact_both_official_service_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: centralized filtering and simultaneous credential-bearing source requests.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("httpx2")
    previous_level = logger.level
    previous_disabled = logger.disabled
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.disabled = False

    async def response(
        transport: httpx2.AsyncHTTPTransport,
        request: httpx2.Request,
    ) -> httpx2.Response:
        del transport
        return httpx2.Response(200, request=request)

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", response)
    async with create_async_client() as client:

        async def request(url: str) -> None:
            _ = await client.get(url)

        try:
            # When: different requests are logged without mutating a process-wide logger level.
            async with anyio.create_task_group() as tasks:
                _ = tasks.start_soon(
                    request,
                    "https://apis.data.go.kr/source?serviceKey=never-log-kstartup&page=1",
                )
                _ = tasks.start_soon(
                    request,
                    "https://www.bizinfo.go.kr/source?crtfcKey=never-log-bizinfo&page=1",
                )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
            logger.disabled = previous_disabled

    # Then: both secrets are absent while non-secret request context remains useful.
    output = stream.getvalue()
    assert "never-log-kstartup" not in output
    assert "never-log-bizinfo" not in output
    assert output.count("REDACTED") == 2
    assert output.count("page=1") == 2
