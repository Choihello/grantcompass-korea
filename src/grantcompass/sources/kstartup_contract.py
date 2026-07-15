"""Current official K-Startup Swagger response boundary."""

from dataclasses import dataclass
from datetime import date
from typing import ClassVar, Final, assert_never

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, RootModel, ValidationError

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import JsonObject, JsonValue, freeze_json_object
from grantcompass.domain.programs import RawNotice
from grantcompass.sources.base import SourceContractError

_DATE_WIDTH: Final = 8


class _AnnouncementItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    pbanc_sn: str = Field(min_length=1)
    biz_pbanc_nm: str = Field(min_length=1)
    pbanc_ntrp_nm: str | None = None
    sprv_inst: str | None = None
    pbanc_ctnt: str | None = None
    aply_trgt_ctnt: str | None = None
    pbanc_rcpt_bgng_dt: str | None = None
    pbanc_rcpt_end_dt: str | None = None
    biz_aply_url: HttpUrl
    detl_pg_url: HttpUrl | None = None


class _DataEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    data: tuple[_AnnouncementItem, ...]


class _ResponseEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    current_count: int = Field(alias="currentCount", ge=0)
    data: _DataEnvelope
    match_count: int = Field(alias="matchCount", ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(alias="perPage", ge=1, le=100)
    total_count: int = Field(alias="totalCount", ge=0)


class _JsonDocument(RootModel[JsonObject]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


@dataclass(frozen=True, slots=True)
class ParsedKStartupPage:
    """Canonical notices and pagination parsed from one official response."""

    notices: tuple[RawNotice, ...]
    page: int
    per_page: int
    total_count: int


def parse_kstartup_page(content: bytes) -> ParsedKStartupPage:
    """Parse official response bytes while retaining every item field."""
    try:
        envelope = _ResponseEnvelope.model_validate_json(content)
        raw_items = _extract_raw_items(content)
    except (ValidationError, SourceContractError):
        raise _invalid_response() from None
    items = envelope.data.data
    if envelope.current_count != len(items) or len(items) != len(raw_items):
        raise _invalid_response()
    notices = tuple(
        _map_notice(item, raw_item) for item, raw_item in zip(items, raw_items, strict=True)
    )
    return ParsedKStartupPage(
        notices=notices,
        page=envelope.page,
        per_page=envelope.per_page,
        total_count=envelope.total_count,
    )


def _extract_raw_items(content: bytes) -> tuple[JsonObject, ...]:
    document = _JsonDocument.model_validate_json(content).root
    data_envelope = _required_object(document.get("data"))
    items = _required_list(data_envelope.get("data"))
    return tuple(_required_object(item) for item in items)


def _required_object(value: JsonValue | None) -> JsonObject:
    match value:
        case dict() as mapping:
            return mapping
        case None | str() | int() | float() | list():
            raise _invalid_response()
        case _:
            assert_never(value)


def _required_list(value: JsonValue | None) -> list[JsonValue]:
    match value:
        case list() as items:
            return items
        case None | str() | int() | float() | dict():
            raise _invalid_response()
        case _:
            assert_never(value)


def _map_notice(item: _AnnouncementItem, raw_payload: JsonObject) -> RawNotice:
    return RawNotice(
        source=SourceName.KSTARTUP,
        source_notice_id=item.pbanc_sn,
        title=item.biz_pbanc_nm,
        organization=item.pbanc_ntrp_nm,
        summary=item.pbanc_ctnt,
        application_start=_parse_date(item.pbanc_rcpt_bgng_dt),
        application_end=_parse_date(item.pbanc_rcpt_end_dt),
        detail_url=_require_https(item.biz_aply_url),
        attachments=(),
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


def _invalid_response() -> SourceContractError:
    return SourceContractError(
        code="kstartup_invalid_response",
        message="K-Startup returned invalid JSON or response structure",
    )
