"""Persisted operator-visible release failure states."""

from dataclasses import dataclass
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.storage.table_eligibility import ApplicantProfileRow
from grantcompass.storage.table_notice_analysis import FieldConflictRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, SourceRunRow

_SOURCE_503_STALE: Final = "source_503_stale"
_SCAN_PDF_OCR_REQUIRED: Final = "scan_pdf_ocr_required"
_CONFLICTING_DEADLINES: Final = "conflicting_deadlines"
_INCOMPLETE_PROFILE_NEEDS_REVIEW: Final = "incomplete_profile_needs_review"


@dataclass(frozen=True, slots=True)
class FailureEntry:
    """One stable visible ID backed by a current persisted state."""

    id: str
    title: str
    guidance: str


@dataclass(frozen=True, slots=True)
class FailureSnapshot:
    """Complete human-facing failure inventory for one database snapshot."""

    entries: tuple[FailureEntry, ...]
    hidden_failures: tuple[str, ...]

    @classmethod
    def from_inventory(
        cls,
        *,
        candidate_ids: tuple[str, ...],
        visible_entries: tuple[FailureEntry, ...],
    ) -> "FailureSnapshot":
        """Resolve every recognized persisted candidate as visible or hidden."""
        entries_by_id = {entry.id: entry for entry in visible_entries}
        unique_candidates = tuple(dict.fromkeys(candidate_ids))
        entries = tuple(
            entries_by_id[candidate_id]
            for candidate_id in unique_candidates
            if candidate_id in entries_by_id
        )
        hidden = tuple(
            candidate_id for candidate_id in unique_candidates if candidate_id not in entries_by_id
        )
        return cls(entries, hidden)

    @property
    def visible_failure_ids(self) -> tuple[str, ...]:
        """Return stable identifiers in display order."""
        return tuple(entry.id for entry in self.entries)


class FailureHealth(BaseModel):
    """Machine-readable mirror of the human failure inventory."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    visible_failure_ids: tuple[str, ...]
    hidden_failures: tuple[str, ...]


async def load_failure_snapshot(session: AsyncSession) -> FailureSnapshot:
    """Detect supported failures from authoritative persisted rows."""
    candidate_ids: list[str] = []
    if await _latest_source_has_stale_503(session):
        candidate_ids.append(_SOURCE_503_STALE)
    if await _has_ocr_required_attachment(session):
        candidate_ids.append(_SCAN_PDF_OCR_REQUIRED)
    if await _has_deadline_conflict(session):
        candidate_ids.append(_CONFLICTING_DEADLINES)
    if await _has_incomplete_profile(session):
        candidate_ids.append(_INCOMPLETE_PROFILE_NEEDS_REVIEW)
    return FailureSnapshot.from_inventory(
        candidate_ids=tuple(candidate_ids),
        visible_entries=_VISIBLE_FAILURES,
    )


async def _latest_source_has_stale_503(session: AsyncSession) -> bool:
    rows = (await session.scalars(select(SourceRunRow).order_by(SourceRunRow.id.desc()))).all()
    latest: dict[str, SourceRunRow] = {}
    for row in rows:
        _ = latest.setdefault(row.source, row)
    for row in latest.values():
        if row.status != "failed" or row.error_code != "http_503":
            continue
        prior_success = await session.scalar(
            select(SourceRunRow.id)
            .where(
                SourceRunRow.source == row.source,
                SourceRunRow.status == "succeeded",
                SourceRunRow.id < row.id,
            )
            .limit(1)
        )
        retained_notice = await session.scalar(
            select(NoticeVersionRow.id).where(NoticeVersionRow.source == row.source).limit(1)
        )
        if prior_success is not None and retained_notice is not None:
            return True
    return False


async def _has_ocr_required_attachment(session: AsyncSession) -> bool:
    row_id = await session.scalar(
        select(AttachmentRow.id)
        .where(
            AttachmentRow.requires_review.is_(True),
            AttachmentRow.parse_error_code.startswith("ocr_required:"),
        )
        .limit(1)
    )
    return row_id is not None


async def _has_deadline_conflict(session: AsyncSession) -> bool:
    row_id = await session.scalar(
        select(FieldConflictRow.id).where(FieldConflictRow.field_name == "application_end").limit(1)
    )
    return row_id is not None


async def _has_incomplete_profile(session: AsyncSession) -> bool:
    rows = (await session.scalars(select(ApplicantProfileRow))).all()
    return any(
        row.founded_on is None or row.regions_json == "[]" or row.industries_json == "[]"
        for row in rows
    )


_VISIBLE_FAILURES: Final = (
    FailureEntry(
        _SOURCE_503_STALE,
        "공식 출처 503 / stale",
        "이전 공고는 유지하고 출처 자격증명과 재시도 시각을 확인하세요.",
    ),
    FailureEntry(
        _SCAN_PDF_OCR_REQUIRED,
        "스캔 PDF / OCR required",
        "OCR 선택 설치 후 재처리하거나 원문을 직접 검토하세요.",
    ),
    FailureEntry(
        _CONFLICTING_DEADLINES,
        "공고 마감일 conflict",
        "각 공식 출처의 현재 공고를 열어 마감일을 확인하세요.",
    ),
    FailureEntry(
        _INCOMPLETE_PROFILE_NEEDS_REVIEW,
        "프로필 누락 / needs_review",
        "설립일, 지역, 업종을 보완한 뒤 판정을 다시 실행하세요.",
    ),
)


__all__ = [
    "FailureEntry",
    "FailureHealth",
    "FailureSnapshot",
    "load_failure_snapshot",
]
