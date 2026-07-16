from pathlib import Path
from typing import Final

import httpx2
import pytest
from pydantic import SecretStr

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import JsonObject, thaw_json_object
from grantcompass.sources.base import SourceContractError, SourceTransportError
from grantcompass.sources.bizinfo import BizinfoAdapter

_ENDPOINT: Final = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
_FIXTURE: Final = Path(__file__).parents[1] / "fixtures" / "bizinfo" / "page_1.json"


@pytest.mark.anyio
async def test_maps_official_json_and_sends_exact_pagination_contract() -> None:
    # Given: a saved representative response at a caller-owned transport boundary.
    observed: list[httpx2.Request] = []
    content = _FIXTURE.read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        observed.append(request)
        return httpx2.Response(200, content=content, headers={"content-type": "application/json"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("not-a-real-key"))

        # When: one bounded page is fetched.
        page = await adapter.fetch_page(1, 2)

    # Then: official fields, complete raw data, and exact parameters are retained.
    notice = page.items[0]
    assert page.page == 1
    assert page.has_next is True
    assert len(page.response_hash) == 64
    assert notice.source is SourceName.BIZINFO
    assert notice.source_notice_id == "PBLN_000000000100001"
    assert notice.title == "가상 로컬 창업 실험 지원사업"
    assert notice.organization == "가상중소기업부"
    assert notice.summary == "가상 초기기업의 지역문제 해결 실험을 지원합니다."
    assert notice.application_start is not None
    assert notice.application_start.isoformat() == "2026-07-01"
    assert notice.application_end is not None
    assert notice.application_end.isoformat() == "2026-07-31"
    assert len(notice.attachments) == 1
    assert notice.attachments[0].filename == "가상 로컬 창업 실험 공고문.pdf"
    raw: JsonObject = thaw_json_object(notice.raw_payload)
    assert raw["hashTags"] == "가상,창업"
    assert raw["totCnt"] == "3"
    assert len(observed) == 1
    assert str(observed[0].url).split("?", maxsplit=1)[0] == _ENDPOINT
    assert dict(observed[0].url.params.multi_items()) == {
        "crtfcKey": "not-a-real-key",
        "dataType": "json",
        "pageIndex": "1",
        "pageUnit": "2",
    }


@pytest.mark.anyio
async def test_single_item_object_and_total_count_are_supported() -> None:
    # Given: the documented single-object item variant.
    content = (
        b'{"jsonArray":{"item":{"pblancId":"PBLN_1","pblancNm":"One",'
        b'"jrsdInsttNm":"Org","bsnsSumryCn":"Summary",'
        b'"reqstBeginEndDe":"20260701 ~ 20260731",'
        b'"pblancUrl":"https://www.bizinfo.go.kr/one","totCnt":"1"}}}'
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(200, content=content)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("key"))

        # When: the single item is fetched.
        page = await adapter.fetch_page(1, 100)

    # Then: it is normalized and pagination terminates safely.
    assert len(page.items) == 1
    assert page.items[0].source_notice_id == "PBLN_1"
    assert page.has_next is False


@pytest.mark.anyio
async def test_null_item_is_an_empty_page() -> None:
    # Given: a successful envelope whose item is null.
    content = b'{"jsonArray":{"item":null}}'

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(200, content=content)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("key"))

        # When: the page is fetched.
        page = await adapter.fetch_page(1, 100)

    # Then: absence is explicit and not confused with a transport failure.
    assert page.items == ()
    assert page.has_next is False


@pytest.mark.anyio
async def test_inconsistent_total_count_is_rejected() -> None:
    # Given: multiple items that disagree about the source total count.
    content = _FIXTURE.read_bytes().replace(b'"totCnt": "3"', b'"totCnt": "4"', 1)

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(200, content=content)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("key"))

        # When: inconsistent pagination metadata crosses the contract boundary.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(1, 2)

    # Then: pagination fails closed with a stable code.
    assert captured.value.code == "bizinfo_inconsistent_total_count"


@pytest.mark.anyio
async def test_invalid_period_is_rejected() -> None:
    # Given: an item with a non-contract application period.
    content = _FIXTURE.read_bytes().replace(b"20260701 ~ 20260731", b"not-a-valid-period")

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(200, content=content)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("key"))

        # When: the period is mapped.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(1, 2)

    # Then: the response is rejected rather than silently dropping dates.
    assert captured.value.code == "bizinfo_invalid_period"


@pytest.mark.anyio
async def test_http_and_transport_failures_are_stable_and_secret_safe() -> None:
    # Given: an upstream HTTP failure and a protected credential.
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(503, content=b"unsafe upstream body")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("secret-that-must-not-leak"))

        # When: the failed status crosses the adapter boundary.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: callers see a stable diagnostic without response or credential content.
    assert captured.value.code == "bizinfo_http_status"
    assert str(captured.value) == "Bizinfo returned HTTP 503"
    assert "secret-that-must-not-leak" not in repr(captured.value)


@pytest.mark.anyio
async def test_transport_exception_is_stable_and_secret_safe() -> None:
    # Given: a caller-owned transport whose unsafe detail is not contract data.
    def handler(request: httpx2.Request) -> httpx2.Response:
        detail = "unsafe transport detail"
        raise httpx2.ConnectError(detail, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("secret-that-must-not-leak"))

        # When: the request fails before a response exists.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: transport and credential details are replaced by a stable failure.
    assert captured.value.code == "bizinfo_transport_error"
    assert str(captured.value) == "Bizinfo transport failed"
    assert "secret-that-must-not-leak" not in repr(captured.value)


@pytest.mark.anyio
async def test_redirect_is_not_followed_when_client_default_follows() -> None:
    # Given: the official destination redirects while the caller client follows by default.
    observed: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        observed.append(request)
        return httpx2.Response(302, headers={"location": "https://example.invalid/leak"})

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), follow_redirects=True
    ) as client:
        adapter = BizinfoAdapter(client, SecretStr("secret-that-must-not-leak"))

        # When: the redirect crosses the credential-bearing request boundary.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: no redirect receives the credential and the status is stable.
    assert captured.value.code == "bizinfo_http_status"
    assert len(observed) == 1
    assert observed[0].url.host == "www.bizinfo.go.kr"
    assert "secret-that-must-not-leak" not in repr(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "base_url",
    [
        "http://www.bizinfo.go.kr/uss/rss/bizinfoApi.do",
        "https://user:pass@www.bizinfo.go.kr/uss/rss/bizinfoApi.do",
        "https://www.bizinfo.go.kr:8443/uss/rss/bizinfoApi.do",
        "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do?route=other",
        "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do#fragment",
        "https://example.invalid/uss/rss/bizinfoApi.do",
        "https://www.bizinfo.go.kr/uss/rss/other.do",
    ],
)
async def test_invalid_base_and_pagination_fail_before_transport(base_url: str) -> None:
    # Given: an insecure endpoint and a transport that records accidental use.
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, content=b"{}")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        # When: constructor validation receives the insecure endpoint.
        with pytest.raises(SourceContractError) as captured:
            _ = BizinfoAdapter(client, SecretStr("key"), base_url=base_url)

    # Then: validation is stable and no request occurs.
    assert captured.value.code == "bizinfo_invalid_base_url"
    assert calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(("page", "page_size"), [(0, 100), (1, 0), (1, 101)])
async def test_invalid_pagination_fails_before_transport(page: int, page_size: int) -> None:
    # Given: pagination outside the bounded official request contract.
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, content=b"{}")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = BizinfoAdapter(client, SecretStr("key"))

        # When: invalid pagination reaches the adapter boundary.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(page, page_size)

    # Then: a stable validation failure occurs before transport.
    assert captured.value.code == "bizinfo_invalid_pagination"
    assert calls == []
