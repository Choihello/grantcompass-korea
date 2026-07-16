"""Typed parser for the documented Bizinfo JSON response."""

from dataclasses import dataclass
from datetime import date
from re import fullmatch
from typing import ClassVar, assert_never

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, RootModel, ValidationError

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import JsonObject, JsonValue, freeze_json_object
from grantcompass.domain.programs import AttachmentRef, RawNotice
from grantcompass.sources.base import SourceContractError


class _BizinfoItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    notice_id: str = Field(alias="pblancId", min_length=1)
    title: str = Field(alias="pblancNm", min_length=1)
    organization: str | None = Field(default=None, alias="jrsdInsttNm")
    summary: str | None = Field(default=None, alias="bsnsSumryCn")
    application_period: str | None = Field(default=None, alias="reqstBeginEndDe")
    notice_url: HttpUrl = Field(alias="pblancUrl")
    attachment_url: HttpUrl | None = Field(default=None, alias="flpthNm")
    attachment_name: str | None = Field(default=None, alias="fileNm")
    total_count: str | None = Field(default=None, alias="totCnt")


class _Channel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    item: tuple[_BizinfoItem, ...] | _BizinfoItem | None


class _Envelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    channel: _Channel = Field(alias="jsonArray")


class _JsonDocument(RootModel[JsonObject]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


@dataclass(frozen=True, slots=True)
class ParsedBizinfoPage:
    """Canonical notices and validated pagination total from one response."""

    notices: tuple[RawNotice, ...]
    total_count: int


def parse_bizinfo_page(content: bytes) -> ParsedBizinfoPage:
    """Validate typed fields while retaining each complete immutable item."""
    try:
        envelope = _Envelope.model_validate_json(content)
        raw_items = _extract_raw_items(content)
    except ValidationError:
        raise _invalid_response() from None
    items = _normalize_items(envelope.channel.item)
    if len(items) != len(raw_items):
        raise _invalid_response()
    totals = tuple(_parse_total(item.total_count) for item in items)
    known_totals = frozenset(total for total in totals if total is not None)
    if len(known_totals) > 1:
        raise SourceContractError(
            code="bizinfo_inconsistent_total_count",
            message="Bizinfo items disagree about total count",
        )
    total_count = next(iter(known_totals), len(items))
    if total_count < len(items):
        raise _invalid_response()
    notices = tuple(
        _map_notice(item, raw_payload) for item, raw_payload in zip(items, raw_items, strict=True)
    )
    return ParsedBizinfoPage(notices=notices, total_count=total_count)


def _normalize_items(
    items: tuple[_BizinfoItem, ...] | _BizinfoItem | None,
) -> tuple[_BizinfoItem, ...]:
    match items:
        case None:
            return ()
        case _BizinfoItem() as item:
            return (item,)
        case tuple() as many:
            return many
        case _:
            assert_never(items)


def _extract_raw_items(content: bytes) -> tuple[JsonObject, ...]:
    document = _JsonDocument.model_validate_json(content).root
    channel = _required_object(document.get("jsonArray"))
    raw_items = channel.get("item")
    match raw_items:
        case None:
            return ()
        case dict() as item:
            return (item,)
        case list() as items:
            return tuple(_required_object(item) for item in items)
        case str() | int() | float():
            raise _invalid_response()
        case _:
            assert_never(raw_items)


def _required_object(value: JsonValue | None) -> JsonObject:
    match value:
        case dict() as mapping:
            return mapping
        case None | str() | int() | float() | list():
            raise _invalid_response()
        case _:
            assert_never(value)


def _map_notice(item: _BizinfoItem, raw_payload: JsonObject) -> RawNotice:
    start, end = _parse_period(item.application_period)
    attachments: tuple[AttachmentRef, ...] = ()
    if item.attachment_url is not None:
        attachments = (
            AttachmentRef(
                filename=item.attachment_name or "attachment",
                download_url=_require_https(item.attachment_url),
            ),
        )
    return RawNotice(
        source=SourceName.BIZINFO,
        source_notice_id=item.notice_id,
        title=item.title,
        organization=item.organization,
        summary=item.summary,
        application_start=start,
        application_end=end,
        detail_url=_require_https(item.notice_url),
        attachments=attachments,
        raw_payload=freeze_json_object(raw_payload),
    )


def _parse_period(value: str | None) -> tuple[date | None, date | None]:
    if value is None or not value.strip():
        return None, None
    matched = fullmatch(r"\s*(\d{8})\s*~\s*(\d{8})\s*", value)
    if matched is None:
        raise _invalid_period()
    try:
        return _parse_date(matched.group(1)), _parse_date(matched.group(2))
    except ValueError:
        raise _invalid_period() from None


def _parse_date(value: str) -> date:
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")


def _parse_total(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isdecimal():
        raise _invalid_response()
    return int(value)


def _require_https(value: HttpUrl) -> HttpUrl:
    if value.scheme != "https":
        raise SourceContractError(
            code="bizinfo_insecure_url",
            message="Bizinfo notice URLs must use HTTPS",
        )
    return value


def _invalid_response() -> SourceContractError:
    return SourceContractError(
        code="bizinfo_invalid_response",
        message="Bizinfo returned invalid JSON or response structure",
    )


def _invalid_period() -> SourceContractError:
    return SourceContractError(
        code="bizinfo_invalid_period",
        message="Bizinfo application period must use YYYYMMDD ~ YYYYMMDD",
    )
