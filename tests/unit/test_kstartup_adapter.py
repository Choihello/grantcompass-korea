from pathlib import Path
from typing import Final

import httpx2
import pytest
from pydantic import SecretStr

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import JsonObject, thaw_json_object
from grantcompass.sources.base import SourceContractError, SourceTransportError
from grantcompass.sources.kstartup import KStartupAdapter

_ENDPOINT: Final = (
    "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
)
_FIXTURES: Final = Path(__file__).parents[1] / "fixtures" / "kstartup"
_CREDENTIAL_MARKER: Final = "secret-that-must-not-leak"


def _fixture_bytes(filename: str) -> bytes:
    return (_FIXTURES / filename).read_bytes()


def _response_transport(filename: str, status_code: int = 200) -> httpx2.MockTransport:
    content = _fixture_bytes(filename)

    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(status_code, content=content)

    return httpx2.MockTransport(handler)


@pytest.mark.anyio
async def test_maps_current_official_response_and_exact_request_contract() -> None:
    # Given: the fictional saved fixture using the current official Swagger shape.
    observed: list[httpx2.Request] = []
    content = _fixture_bytes("announcement_page_1.json")

    def handler(request: httpx2.Request) -> httpx2.Response:
        observed.append(request)
        return httpx2.Response(200, content=content)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("fictional-key"))

        # When: the official first page is fetched.
        page = await adapter.fetch_page(1, 1)

    # Then: canonical fields, raw payload, pagination, and query names match Swagger.
    notice = page.items[0]
    expected_payload: JsonObject = {
        "pbanc_sn": "FICT-2026-001",
        "biz_pbanc_nm": "가상 로컬 창업 실험 지원사업",
        "pbanc_ntrp_nm": "가상창업지원원",
        "sprv_inst": "가상중소기업부",
        "pbanc_ctnt": "가상 지역문제 해결 아이디어의 시장 검증을 지원합니다.",
        "aply_trgt_ctnt": "가상의 예비창업자와 초기기업",
        "pbanc_rcpt_bgng_dt": "20260701",
        "pbanc_rcpt_end_dt": "20260731",
        "biz_aply_url": (
            "https://www.k-startup.go.kr/web/contents/bizPbanc-ongoing.do?pbancSn=FICT-2026-001"
        ),
        "detl_pg_url": ("https://www.k-startup.go.kr/web/contents/apply.do?pbancSn=FICT-2026-001"),
        "supt_regin": "가상지역",
    }
    assert page.page == 1
    assert page.has_next is True
    assert page.response_hash == "c1e0d2256d0cffbc31fc69d00b28457e7208fa8db7cf358bd1cdc9a71aa0684f"
    assert notice.source is SourceName.KSTARTUP
    assert notice.source_notice_id == "FICT-2026-001"
    assert notice.title == "가상 로컬 창업 실험 지원사업"
    assert notice.organization == "가상창업지원원"
    assert notice.summary == "가상 지역문제 해결 아이디어의 시장 검증을 지원합니다."
    assert str(notice.detail_url) == expected_payload["biz_aply_url"]
    assert notice.attachments == ()
    assert thaw_json_object(notice.raw_payload) == expected_payload
    assert len(observed) == 1
    assert str(observed[0].url).split("?", maxsplit=1)[0] == _ENDPOINT
    assert dict(observed[0].url.params.multi_items()) == {
        "serviceKey": "fictional-key",
        "page": "1",
        "perPage": "1",
        "returnType": "json",
    }


@pytest.mark.anyio
async def test_empty_official_data_list_returns_empty_page() -> None:
    # Given: a successful official root with an empty nested data list.
    async with httpx2.AsyncClient(transport=_response_transport("empty.json")) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the empty page is fetched.
        page = await adapter.fetch_page(1, 100)

    # Then: the adapter returns an empty terminal page.
    assert page.items == ()
    assert page.has_next is False


@pytest.mark.anyio
@pytest.mark.parametrize("fixture", ["malformed_root.json", "malformed_data.json"])
async def test_malformed_official_structure_is_rejected(fixture: str) -> None:
    # Given: valid JSON that violates the current official root or nested data shape.
    async with httpx2.AsyncClient(transport=_response_transport(fixture)) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the malformed structure crosses the boundary parser.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: callers receive the stable response-contract failure.
    assert captured.value.code == "kstartup_invalid_response"


@pytest.mark.anyio
async def test_invalid_json_is_rejected() -> None:
    # Given: a 200 response containing invalid JSON bytes.
    async with httpx2.AsyncClient(transport=_response_transport("malformed.json")) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: invalid JSON crosses the boundary parser.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: no raw body is exposed through the stable error.
    assert captured.value.code == "kstartup_invalid_response"
    assert "currentCount" not in str(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [401, 500])
async def test_documented_http_error_is_transport_failure(status_code: int) -> None:
    # Given: a documented official HTTP error status.
    async with httpx2.AsyncClient(
        transport=_response_transport("empty.json", status_code)
    ) as client:
        adapter = KStartupAdapter(client, SecretStr(_CREDENTIAL_MARKER))

        # When: the HTTP response crosses the adapter status boundary.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: status is stable and neither key nor response body is exposed.
    assert captured.value.code == "kstartup_http_status"
    assert str(captured.value) == f"K-Startup returned HTTP {status_code}"
    assert _CREDENTIAL_MARKER not in repr(captured.value)


@pytest.mark.anyio
async def test_timeout_is_stable_transport_failure() -> None:
    # Given: a transport that raises a read timeout containing unsafe detail.
    def handler(request: httpx2.Request) -> httpx2.Response:
        detail = "unsafe timeout detail"
        raise httpx2.ReadTimeout(detail, request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr(_CREDENTIAL_MARKER))

        # When: the official request times out.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: timeout and credential details are replaced by the stable source error.
    assert captured.value.code == "kstartup_transport_error"
    assert str(captured.value) == "K-Startup transport failed"
    assert _CREDENTIAL_MARKER not in repr(captured.value)


@pytest.mark.anyio
async def test_redirect_is_not_followed_even_when_client_default_follows() -> None:
    # Given: a redirecting official endpoint and a client configured to follow redirects.
    observed: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        observed.append(request)
        return httpx2.Response(302, headers={"location": "https://example.invalid/leak"})

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), follow_redirects=True
    ) as client:
        adapter = KStartupAdapter(client, SecretStr(_CREDENTIAL_MARKER))

        # When: the official endpoint returns a redirect.
        with pytest.raises(SourceTransportError) as captured:
            _ = await adapter.fetch_page(1, 100)

    # Then: only the pinned destination is called and the redirect is a stable failure.
    assert captured.value.code == "kstartup_http_status"
    assert len(observed) == 1
    assert observed[0].url.host == "apis.data.go.kr"
    assert _CREDENTIAL_MARKER not in repr(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "base_url",
    [
        "http://apis.data.go.kr/B552735/kisedKstartupService01",
        "https://user:pass@apis.data.go.kr/B552735/kisedKstartupService01",
        "https://apis.data.go.kr:8443/B552735/kisedKstartupService01",
        "https://apis.data.go.kr/B552735/kisedKstartupService01?route=other",
        "https://apis.data.go.kr/B552735/kisedKstartupService01#fragment",
        "https://example.invalid/B552735/kisedKstartupService01",
        "https://apis.data.go.kr/B552735/otherService",
    ],
)
async def test_unpinned_base_is_rejected_before_key_or_transport(base_url: str) -> None:
    # Given: a noncanonical credential destination and a recording transport.
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(200, content=_fixture_bytes("empty.json"))

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        # When: the destination crosses the public constructor boundary.
        with pytest.raises(SourceContractError) as captured:
            _ = KStartupAdapter(client, SecretStr(_CREDENTIAL_MARKER), base_url=base_url)

    # Then: stable validation occurs before any request or secret exposure.
    assert captured.value.code == "kstartup_invalid_base_url"
    assert calls == []
    assert _CREDENTIAL_MARKER not in repr(captured.value)


@pytest.mark.anyio
@pytest.mark.parametrize(("page", "page_size"), [(0, 100), (1, 0), (1, 101)])
async def test_invalid_pagination_is_rejected_before_transport(page: int, page_size: int) -> None:
    # Given: pagination outside the official bounded request contract.
    def handler(request: httpx2.Request) -> httpx2.Response:
        del request
        raise AssertionError

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        adapter = KStartupAdapter(client, SecretStr("key"))

        # When: the invalid request reaches the adapter boundary.
        with pytest.raises(SourceContractError) as captured:
            _ = await adapter.fetch_page(page, page_size)

    # Then: the network is not called and the stable pagination error is returned.
    assert captured.value.code == "kstartup_invalid_pagination"
