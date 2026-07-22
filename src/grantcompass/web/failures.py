"""Persisted operator-visible release failure states."""

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.storage.table_eligibility import ApplicantProfileRow, RuleAssessmentRow
from grantcompass.storage.table_notice_analysis import FieldConflictRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, SourceRunRow

_SOURCE_503_STALE: Final = "source_503_stale"
_SCAN_PDF_OCR_REQUIRED: Final = "scan_pdf_ocr_required"
_CONFLICTING_DEADLINES: Final = "conflicting_deadlines"
_INCOMPLETE_PROFILE_NEEDS_REVIEW: Final = "incomplete_profile_needs_review"
_CANDIDATE_TOKEN: Final = re.compile(r"[a-z0-9][a-z0-9_.-]*\Z")


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
        candidates = frozenset(candidate_ids)
        entries = tuple(entry for entry in visible_entries if entry.id in candidates)
        visible_ids = frozenset(entry.id for entry in entries)
        hidden = tuple(sorted(candidates - visible_ids))
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
    candidate_ids.extend(await _source_failure_candidates(session))
    candidate_ids.extend(await _attachment_failure_candidates(session))
    candidate_ids.extend(await _field_conflict_candidates(session))
    candidate_ids.extend(await _rule_assessment_failure_candidates(session))
    if await _has_incomplete_profile(session):
        candidate_ids.append(_INCOMPLETE_PROFILE_NEEDS_REVIEW)
    return FailureSnapshot.from_inventory(
        candidate_ids=tuple(candidate_ids),
        visible_entries=_VISIBLE_FAILURES,
    )


async def _source_failure_candidates(session: AsyncSession) -> tuple[str, ...]:
    rows = (await session.scalars(select(SourceRunRow).order_by(SourceRunRow.id.desc()))).all()
    latest: dict[str, SourceRunRow] = {}
    for row in rows:
        _ = latest.setdefault(row.source, row)
    candidates: list[str] = []
    for source in sorted(latest):
        row = latest[source]
        if row.status != "failed":
            continue
        if row.error_code == "http_503" and await _has_retained_stale_data(session, row):
            candidates.append(_SOURCE_503_STALE)
        else:
            candidates.append(
                _hidden_candidate("source_run", row.source, row.error_code or "unknown")
            )
    return tuple(candidates)


async def _has_retained_stale_data(session: AsyncSession, row: SourceRunRow) -> bool:
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
    return prior_success is not None and retained_notice is not None


async def _attachment_failure_candidates(session: AsyncSession) -> tuple[str, ...]:
    rows = (
        await session.scalars(
            select(AttachmentRow)
            .where(
                AttachmentRow.requires_review.is_(True),
                AttachmentRow.parse_error_code.is_not(None),
            )
            .order_by(AttachmentRow.parse_error_code, AttachmentRow.id)
        )
    ).all()
    return tuple(
        _SCAN_PDF_OCR_REQUIRED
        if row.parse_error_code is not None and row.parse_error_code.startswith("ocr_required:")
        else _hidden_candidate("attachment_parse", row.parse_error_code or "unknown")
        for row in rows
    )


async def _field_conflict_candidates(session: AsyncSession) -> tuple[str, ...]:
    rows = (
        await session.scalars(select(FieldConflictRow).order_by(FieldConflictRow.field_name))
    ).all()
    return tuple(
        _CONFLICTING_DEADLINES
        if row.field_name == "application_end"
        else _hidden_candidate("field_conflict", row.field_name)
        for row in rows
    )


async def _rule_assessment_failure_candidates(session: AsyncSession) -> tuple[str, ...]:
    error_ids = (
        await session.scalars(
            select(RuleAssessmentRow.error_id)
            .where(RuleAssessmentRow.error_id.is_not(None))
            .order_by(RuleAssessmentRow.error_id)
        )
    ).all()
    return tuple(
        _hidden_candidate("rule_assessment", error_id or "unknown") for error_id in error_ids
    )


def _hidden_candidate(namespace: str, *parts: str) -> str:
    tokens = (_stable_token(namespace), *(_stable_token(part) for part in parts))
    return ":".join(tokens)


def _stable_token(value: str) -> str:
    normalized = value.casefold()
    if _CANDIDATE_TOKEN.fullmatch(normalized) is not None:
        return normalized
    digest = sha256(value.encode()).hexdigest()[:12]
    return f"opaque-{digest}"


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
