from pathlib import Path
from typing import Final

import httpx2
import pytest
from pydantic import SecretStr

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import FrozenJsonObject, JsonObject, thaw_json_object
from grantcompass.sources.base import SourceContractError, SourceTransportError
from grantcompass.sources.kstartup import KStartupAdapter

_ENDPOINT: Final = (
    "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
)
_FIXTURES: Final = Path(__file__).parents[1] / "fixtures" / "kstartup"


def _response_transport(filename: str) -> httpx2.MockTransport:
    content = (_FIXTURES / filename).read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(200, content=content, headers={"content-type": "application/json"})

    return httpx2.MockTransport(handler)


@pytest.mark.anyio
async def test_maps_official_response_and_sends_only_contract_parameters() -> None:
    # Given: a saved official response and a caller-owned transport boundary.
    observed: list[httpx2.Request] = []
    content = (_FIXTURES / "announcement_page_1.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        observed.append(request)
        return httpx2.Response(200, content=content, headers={"content-type": "application/json"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("not-a-real-key"))

        # When: the first announcement page is fetched.
        page = await adapter.fetch_page(1, 1)

    # Then: the canonical notice and exact official request contract are exposed.
    notice = page.items[0]
    assert page.page == 1
    assert page.has_next is True
    assert page.response_hash == "4ae89df7630082f4b1104f4fc6750380bba0d4b147c10ed66ad67fa2d743cd9b"
    assert notice.source is SourceName.KSTARTUP
    assert notice.source_notice_id == "202607150001"
    assert notice.title == "2026년 초기창업패키지 창업기업 모집공고"
    assert notice.organization == "창업진흥원"
    assert notice.application_start is not None
    assert notice.application_start.isoformat() == "2026-07-01"
    assert notice.application_end is not None
    assert notice.application_end.isoformat() == "2026-07-31"
    assert notice.detail_url.scheme == "https"
    assert len(notice.attachments) == 1
    expected_payload: JsonObject = {
        "pbanc_sn": "202607150001",
        "biz_pbanc_nm": "2026년 초기창업패키지 창업기업 모집공고",
        "pbanc_ntrp_nm": "창업진흥원",
        "pbanc_rcpt_bgng_dt": "20260701",
        "pbanc_rcpt_end_dt": "20260731",
        "detl_pg_url": (
            "https://www.k-startup.go.kr/web/contents/bizPbanc-ongoing.do?pbancSn=202607150001"
        ),
        "aply_trgt_ctnt": "창업 3년 이내 기업",
        "atch_file_url": "https://www.k-startup.go.kr/file/202607150001.pdf",
        "file_nm": "2026년 초기창업패키지 공고문.pdf",
        "supt_regin": "전국",
        "rcrt_prgs_yn": "Y",
        "metadata": {"channels": ["online", "offline"], "priority": 1},
    }
    assert thaw_json_object(notice.raw_payload) == expected_payload
    metadata = notice.raw_payload["metadata"]
    assert isinstance(metadata, FrozenJsonObject)
    assert metadata["channels"] == ("online", "offline")
    assert '"metadata"' in notice.model_dump_json()
    assert len(observed) == 1
    assert str(observed[0].url).split("?", maxsplit=1)[0] == _ENDPOINT
    assert dict(observed[0].url.params.multi_items()) == {
        "serviceKey": "not-a-real-key",
        "pageNo": "1",
        "numOfRows": "1",
        "returnType": "json",
    }


@pytest.mark.anyio
async def test_api_error_is_not_normalized_to_empty_page() -> None:
    # Given: a valid JSON response carrying an upstream result-code failure.
    async with httpx2.AsyncClient(transport=_response_transport("error.json")) as client:
        adapter = KStartupAdapter(client, SecretStr("secret-that-must-not-leak"))

        # When: the adapter inspects the upstream header.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: a stable contract failure is raised without exposing the secret.
    assert captured.value.code == "kstartup_api_error"
    assert "secret-that-must-not-leak" not in str(captured.value)


@pytest.mark.anyio
async def test_single_item_object_is_normalized_to_one_notice() -> None:
    # Given: the official single-object items variant.
    async with httpx2.AsyncClient(transport=_response_transport("single_item.json")) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the second page is fetched.
        page = await adapter.fetch_page(2, 1)

    # Then: the item becomes a one-element tuple with safe pagination metadata.
    assert len(page.items) == 1
    assert page.items[0].source_notice_id == "202607150002"
    assert page.items[0].attachments == ()
    assert page.has_next is False


@pytest.mark.anyio
async def test_null_items_is_normalized_to_empty_page() -> None:
    # Given: a successful response whose items value is null.
    async with httpx2.AsyncClient(transport=_response_transport("empty.json")) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the empty page is fetched.
        page = await adapter.fetch_page(1, 100)

    # Then: an empty immutable collection is returned without hiding an API error.
    assert page.items == ()
    assert page.has_next is False


@pytest.mark.anyio
async def test_malformed_json_becomes_stable_contract_error() -> None:
    # Given: a 200 response with malformed JSON bytes.
    async with httpx2.AsyncClient(transport=_response_transport("malformed.json")) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the transport body crosses the response boundary.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: callers receive a stable error without raw response content.
    assert captured.value.code == "kstartup_invalid_response"
    assert "resultCode" not in str(captured.value)


@pytest.mark.anyio
async def test_insecure_notice_url_is_rejected() -> None:
    # Given: an otherwise valid saved item with an insecure detail URL.
    content = (
        (_FIXTURES / "announcement_page_1.json")
        .read_bytes()
        .replace(
            b"https://www.k-startup.go.kr/web/contents/",
            b"http://www.k-startup.go.kr/web/contents/",
        )
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(200, content=content)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the insecure URL crosses canonical notice mapping.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(1, 1)

    # Then: the adapter rejects the response with a stable contract code.
    assert captured.value.code == "kstartup_insecure_url"


@pytest.mark.anyio
async def test_http_status_becomes_stable_transport_error() -> None:
    # Given: a caller-owned client returning a non-success HTTP status.
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(503, content=b"upstream unavailable")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the upstream status is inspected.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: the status class is stable and response payload is absent.
    assert captured.value.code == "kstartup_http_status"
    assert str(captured.value) == "K-Startup returned HTTP 503"


@pytest.mark.anyio
async def test_transport_failure_becomes_stable_transport_error() -> None:
    # Given: a caller-owned transport that cannot connect upstream.
    def handler(request: httpx2.Request) -> httpx2.Response:
        detail = "unsafe transport detail"
        raise httpx2.ConnectError(detail, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("secret-that-must-not-leak"))

        # When: the request crosses the failing transport boundary.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: the transport detail and service key are not propagated.
    assert captured.value.code == "kstartup_transport_error"
    assert str(captured.value) == "K-Startup transport failed"
    assert "secret-that-must-not-leak" not in str(captured.value)


@pytest.mark.anyio
async def test_timeout_becomes_stable_transport_error() -> None:
    # Given: a caller-owned transport that times out while reading upstream.
    def handler(request: httpx2.Request) -> httpx2.Response:
        detail = "unsafe timeout detail"
        raise httpx2.ReadTimeout(detail, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("secret-that-must-not-leak"))

        # When: the request crosses the timed-out transport boundary.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: timeout details and the service key are replaced by the stable source error.
    assert captured.value.code == "kstartup_transport_error"
    assert str(captured.value) == "K-Startup transport failed"
    assert "secret-that-must-not-leak" not in str(captured.value)


@pytest.mark.anyio
async def test_insecure_base_url_is_rejected_before_transport() -> None:
    # Given: an HTTP base URL and a transport that records any accidental request.
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, content=b"{}")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        # When: the public adapter boundary receives the insecure base URL.
        with pytest.raises(SourceContractError) as captured:
            _ = KStartupAdapter(
                client,
                SecretStr("secret-that-must-not-leak"),
                base_url="http://example.invalid/service",
            )

    # Then: validation fails before transport and does not reveal the key.
    assert captured.value.code == "kstartup_invalid_base_url"
    assert calls == []
    assert "secret-that-must-not-leak" not in str(captured.value)
    assert "secret-that-must-not-leak" not in repr(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize(("page", "page_size"), [(0, 100), (1, 0), (1, 101)])
async def test_invalid_pagination_is_rejected_before_transport(page: int, page_size: int) -> None:
    # Given: pagination outside the official bounded request contract.
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        raise AssertionError

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the invalid page request reaches the adapter boundary.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(page, page_size)

    # Then: a stable validation code is returned without a network request.
    assert captured.value.code == "kstartup_invalid_pagination"
