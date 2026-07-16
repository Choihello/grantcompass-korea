from dataclasses import dataclass
from datetime import date

from pydantic import HttpUrl

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import RawNotice


@dataclass(frozen=True, slots=True)
class NoticeValues:
    title: str = "가상 초기창업 지원사업"
    organization: str | None = "가상창업지원원"
    application_end: date | None = date(2026, 7, 31)
    summary: str = "가상 초기기업 지원"


_DEFAULT_NOTICE_VALUES = NoticeValues()


def make_notice(
    source: SourceName,
    notice_id: str,
    values: NoticeValues = _DEFAULT_NOTICE_VALUES,
) -> RawNotice:
    return RawNotice(
        source=source,
        source_notice_id=notice_id,
        title=values.title,
        organization=values.organization,
        summary=values.summary,
        application_start=date(2026, 7, 1),
        application_end=values.application_end,
        detail_url=HttpUrl(f"https://example.invalid/{source.value}/{notice_id}"),
        raw_payload=freeze_json_object({"id": notice_id, "summary": values.summary}),
    )
