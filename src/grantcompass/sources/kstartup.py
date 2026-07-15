"""Official K-Startup announcement source adapter."""

from datetime import date
from hashlib import sha256
from typing import ClassVar, Final, assert_never, final

import httpx2
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    RootModel,
    SecretStr,
    TypeAdapter,
    ValidationError,
)

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import JsonObject, JsonValue, freeze_json_object
from grantcompass.domain.programs import AttachmentRef, RawNotice
from grantcompass.sources.base import SourceContractError, SourcePage, SourceTransportError

_DEFAULT_BASE_URL: Final = "https://apis.data.go.kr/B552735/kisedKstartupService01"
_OPERATION: Final = "getAnnouncementInformation01"
_SUCCESS_CODE: Final = "00"
_MAX_PAGE_SIZE: Final = 100
_DATE_WIDTH: Final = 8


class _Header(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    result_code: str = Field(alias="resultCode")
    result_message: str = Field(default="", alias="resultMsg")


class _HeaderResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    header: _Header


class _HeaderEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    response: _HeaderResponse


class _AnnouncementItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    pbanc_sn: str = Field(min_length=1)
    biz_pbanc_nm: str = Field(min_length=1)
    pbanc_ntrp_nm: str | None = None
    pbanc_rcpt_bgng_dt: str | None = None
    pbanc_rcpt_end_dt: str | None = None
    detl_pg_url: HttpUrl
    aply_trgt_ctnt: str | None = None
    atch_file_url: HttpUrl | None = None
    file_nm: str | None = None


class _Body(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    items: tuple[_AnnouncementItem, ...] | _AnnouncementItem | None
    num_of_rows: int = Field(alias="numOfRows", ge=0)
    page_number: int = Field(alias="pageNo", ge=1)
    total_count: int = Field(alias="totalCount", ge=0)


class _Response(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    header: _Header
    body: _Body


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    response: _Response


class _JsonDocument(RootModel[JsonObject]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


@final
class KStartupAdapter:
    """Fetch announcements from the current official K-Startup API."""

    name = SourceName.KSTARTUP

    def __init__(
        self,
        client: httpx2.AsyncClient,
        service_key: SecretStr,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        """Bind a caller-owned HTTP client and protected service key."""
        try:
            validated_base = TypeAdapter(HttpUrl).validate_python(base_url)
        except ValidationError:
            raise SourceContractError(
                code="kstartup_invalid_base_url",
                message="K-Startup base URL must be a valid HTTPS URL",
            ) from None
        if validated_base.scheme != "https":
            raise SourceContractError(
                code="kstartup_invalid_base_url",
                message="K-Startup base URL must be a valid HTTPS URL",
            )
        self._client = client
        self._service_key = service_key
        self._endpoint = f"{str(validated_base).rstrip('/')}/{_OPERATION}"

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        """Fetch one page of official announcements."""
        if page < 1 or page_size < 1 or page_size > _MAX_PAGE_SIZE:
            raise SourceContractError(
                code="kstartup_invalid_pagination",
                message="K-Startup pagination must use page >= 1 and page size 1..100",
            )
        try:
            response = await self._client.get(
                self._endpoint,
                params={
                    "serviceKey": self._service_key.get_secret_value(),
                    "pageNo": page,
                    "numOfRows": page_size,
                    "returnType": "json",
                },
            )
        except httpx2.TransportError:
            raise SourceTransportError(
                code="kstartup_transport_error",
                message="K-Startup transport failed",
            ) from None
        if not response.is_success:
            raise SourceTransportError(
                code="kstartup_http_status",
                message=f"K-Startup returned HTTP {response.status_code}",
            )
        envelope = _parse_response(response.content)
        body = envelope.response.body
        if body.page_number != page:
            raise SourceContractError(
                code="kstartup_page_mismatch",
                message="K-Startup response page differs from requested page",
            )
        items = _normalize_items(body.items)
        raw_items = _extract_raw_items(response.content)
        if len(items) != len(raw_items):
            raise SourceContractError(
                code="kstartup_item_mismatch",
                message="K-Startup typed and raw item counts differ",
            )
        notices = tuple(
            _map_notice(item, raw_payload)
            for item, raw_payload in zip(items, raw_items, strict=True)
        )
        has_next = body.num_of_rows > 0 and body.page_number * body.num_of_rows < body.total_count
        return SourcePage(
            items=notices,
            page=body.page_number,
            has_next=has_next,
            response_hash=sha256(response.content).hexdigest(),
        )


def _parse_response(content: bytes) -> _Envelope:
    try:
        header = _HeaderEnvelope.model_validate_json(content).response.header
    except ValidationError:
        raise SourceContractError(
            code="kstartup_invalid_response",
            message="K-Startup returned invalid JSON or response structure",
        ) from None
    if header.result_code != _SUCCESS_CODE:
        raise SourceContractError(
            code="kstartup_api_error",
            message=f"K-Startup API rejected the request with code {header.result_code}",
        )
    try:
        return _Envelope.model_validate_json(content)
    except ValidationError:
        raise SourceContractError(
            code="kstartup_invalid_response",
            message="K-Startup returned invalid JSON or response structure",
        ) from None


def _normalize_items(
    items: tuple[_AnnouncementItem, ...] | _AnnouncementItem | None,
) -> tuple[_AnnouncementItem, ...]:
    match items:
        case None:
            return ()
        case _AnnouncementItem() as item:
            return (item,)
        case tuple() as many:
            return many
        case _:
            assert_never(items)


def _extract_raw_items(content: bytes) -> tuple[JsonObject, ...]:
    try:
        document = _JsonDocument.model_validate_json(content).root
        response = _required_object(document.get("response"))
        body = _required_object(response.get("body"))
        raw_items = body.get("items")
    except (ValidationError, SourceContractError):
        raise SourceContractError(
            code="kstartup_invalid_response",
            message="K-Startup returned invalid JSON or response structure",
        ) from None
    match raw_items:
        case None:
            return ()
        case dict() as item:
            return (item,)
        case list() as items:
            return tuple(_required_object(item) for item in items)
        case str() | int() | float():
            raise SourceContractError(
                code="kstartup_invalid_response",
                message="K-Startup items must be an object, array, or null",
            )
        case _:
            assert_never(raw_items)


def _required_object(value: JsonValue | None) -> JsonObject:
    match value:
        case dict() as mapping:
            return mapping
        case None | str() | int() | float() | list():
            raise SourceContractError(
                code="kstartup_invalid_response",
                message="K-Startup response object is missing",
            )
        case _:
            assert_never(value)


def _map_notice(item: _AnnouncementItem, raw_payload: JsonObject) -> RawNotice:
    attachments: tuple[AttachmentRef, ...] = ()
    if item.atch_file_url is not None:
        attachments = (
            AttachmentRef(
                filename=item.file_nm or "attachment",
                download_url=_require_https(item.atch_file_url),
            ),
        )
    return RawNotice(
        source=SourceName.KSTARTUP,
        source_notice_id=item.pbanc_sn,
        title=item.biz_pbanc_nm,
        organization=item.pbanc_ntrp_nm,
        summary=item.aply_trgt_ctnt,
        application_start=_parse_date(item.pbanc_rcpt_bgng_dt),
        application_end=_parse_date(item.pbanc_rcpt_end_dt),
        detail_url=_require_https(item.detl_pg_url),
        attachments=attachments,
        raw_payload=freeze_json_object(raw_payload),
    )


def _parse_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    if len(value) != _DATE_WIDTH or not value.isdecimal():
        raise SourceContractError(
            code="kstartup_invalid_date",
            message="K-Startup date must use YYYYMMDD",
        )
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError:
        raise SourceContractError(
            code="kstartup_invalid_date",
            message="K-Startup date must use YYYYMMDD",
        ) from None


def _require_https(value: HttpUrl) -> HttpUrl:
    if value.scheme != "https":
        raise SourceContractError(
            code="kstartup_insecure_url",
            message="K-Startup notice URLs must use HTTPS",
        )
    return value
