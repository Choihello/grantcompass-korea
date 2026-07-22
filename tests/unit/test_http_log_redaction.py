import io
import logging
from collections.abc import Iterator

import anyio
import httpx2
import pytest

from grantcompass.http import create_async_client


@pytest.fixture
def httpx2_log_capture() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("httpx2")
    previous_level = logger.level
    previous_disabled = logger.disabled
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.disabled = previous_disabled


@pytest.mark.anyio
async def test_concurrent_http_logs_redact_both_official_service_keys(
    monkeypatch: pytest.MonkeyPatch,
    httpx2_log_capture: io.StringIO,
) -> None:
    # Given: centralized filtering and simultaneous credential-bearing source requests.
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

    # Then: both secrets are absent while non-secret request context remains useful.
    output = httpx2_log_capture.getvalue()
    assert "never-log-kstartup" not in output
    assert "never-log-bizinfo" not in output
    assert output.count("REDACTED") == 2
    assert output.count("page=1") == 2


def test_formatted_url_argument_redacts_encoded_and_mixed_case_keys(
    httpx2_log_capture: io.StringIO,
) -> None:
    # Given: a LogRecord whose URL argument uses encoded and mixed-case credential keys.
    logger = logging.getLogger("httpx2")
    url = httpx2.URL(
        "https://example.invalid/source?%73ErViCeKeY=encoded-secret&CrTfCkEy=case-secret&page=7"
    )
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "request %s",
        (url,),
        None,
    )

    # When: standard logging handles the formatted record.
    logger.handle(record)

    # Then: message and argument storage lose both secrets while public query data remains.
    assert record.args == ()
    assert "encoded-secret" not in record.getMessage()
    assert "case-secret" not in record.getMessage()
    assert record.getMessage().count("REDACTED") == 2
    assert "page=7" in record.getMessage()
    assert "encoded-secret" not in httpx2_log_capture.getvalue()


def test_noncredential_url_argument_is_preserved(
    httpx2_log_capture: io.StringIO,
) -> None:
    # Given: a non-secret URL argument.
    logger = logging.getLogger("httpx2")
    url = httpx2.URL("https://example.invalid/source?page=9&public=value")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "request %s",
        (url,),
        None,
    )

    # When: standard logging handles the record.
    logger.handle(record)

    # Then: the original arguments and useful message remain unchanged.
    assert record.args == (url,)
    assert "page=9&public=value" in httpx2_log_capture.getvalue()
