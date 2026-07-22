"""Canonical data shared by HTML and PDF consultation dossiers."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import CaseId
from grantcompass.reports.review_state import CurrentReviewState, load_current_review
from grantcompass.storage.table_cases import AuditEventRow, CaseRow, ManagedCompanyRow
from grantcompass.storage.table_documents import EvidenceRow
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    RuleAssessmentRow,
)
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import NoticeVersionRow, ProgramRow

_EVIDENCE_IDS = TypeAdapter(tuple[int, ...])


@dataclass(frozen=True, slots=True)
class SourceLine:
    """One official source snapshot displayed in a consultation dossier."""

    source: str
    detail_url: str
    collected_at: str
    freshness: str


@dataclass(frozen=True, slots=True)
class ConditionLine:
    """One automatic condition and its durable evidence location."""

    automatic_status: str
    override_status: str | None
    effective_status: str
    explanation: str
    source_url: str | None
    page: int | None
    section_path: str | None


@dataclass(frozen=True, slots=True)
class AuditLine:
    """One immutable attributed change displayed oldest-first."""

    action: str
    actor: str
    reason: str
    before_state: str
    after_state: str
    occurred_at: str


@dataclass(frozen=True, slots=True)
class ConsultationData:
    """Shared HTML and PDF data for one institutional support case."""

    case_id: int
    program_id: int
    program_title: str
    company_name: str
    assignee: str
    case_stage: str
    case_note: str
    assessed_at: str
    rule_version: str
    automatic_result: str
    effective_result: str
    review_status: str
    reviewer: str
    review_reason: str
    sources: tuple[SourceLine, ...]
    conditions: tuple[ConditionLine, ...]
    audit: tuple[AuditLine, ...]


async def load_consultation_data(
    session: AsyncSession,
    case_id: CaseId,
    now: datetime,
    timezone: ZoneInfo,
) -> ConsultationData:
    """Build one neutral case dossier from canonical persisted rows."""
    case = await session.get(CaseRow, int(case_id))
    if case is None:
        raise NoResultFound
    managed = await session.get(ManagedCompanyRow, case.managed_company_id)
    program = await session.get(ProgramRow, case.program_id)
    if managed is None or program is None:
        raise NoResultFound
    profile = await session.get(ApplicantProfileRow, managed.profile_id)
    if profile is None:
        raise NoResultFound
    assessments = tuple(
        (
            await session.scalars(
                select(AssessmentRow)
                .where(
                    AssessmentRow.program_id == program.id,
                    AssessmentRow.profile_id == profile.id,
                )
                .order_by(AssessmentRow.assessed_at, AssessmentRow.id)
            )
        ).all()
    )
    assessment = assessments[-1] if assessments else None
    review = await load_current_review(session, assessment) if assessment else None
    return ConsultationData(
        case_id=case.id,
        program_id=program.id,
        program_title=program.title,
        company_name=profile.display_name,
        assignee=case.assignee_name or "미지정",
        case_stage=case.stage,
        case_note=case.note or "-",
        assessed_at=_display_time(assessment.assessed_at, timezone) if assessment else "미판정",
        rule_version=assessment.rule_version if assessment else "-",
        automatic_result=assessment.final_status if assessment else "미판정",
        effective_result=review.effective_final_status if review else "미판정",
        review_status=assessment.review_status if assessment else "미검토",
        reviewer=review.reviewer if review else "-",
        review_reason=review.reason if review else "-",
        sources=await _source_lines(session, program.id, now, timezone),
        conditions=await _condition_lines(session, assessment, review),
        audit=await _audit_lines(session, case.id, assessments, timezone),
    )


async def _source_lines(
    session: AsyncSession, program_id: int, now: datetime, timezone: ZoneInfo
) -> tuple[SourceLine, ...]:
    rows = (
        await session.scalars(
            select(NoticeVersionRow)
            .join(
                CurrentNoticeVersionRow,
                CurrentNoticeVersionRow.version_id == NoticeVersionRow.id,
            )
            .where(NoticeVersionRow.program_id == program_id)
            .order_by(NoticeVersionRow.source, NoticeVersionRow.source_notice_id)
        )
    ).all()
    current = now.astimezone(UTC)
    return tuple(
        SourceLine(
            source=row.source,
            detail_url=row.detail_url,
            collected_at=_display_time(row.collected_at, timezone),
            freshness=(
                "fresh" if current - _as_utc(row.collected_at) <= timedelta(hours=24) else "stale"
            ),
        )
        for row in rows
    )


async def _condition_lines(
    session: AsyncSession,
    assessment: AssessmentRow | None,
    review: CurrentReviewState | None,
) -> tuple[ConditionLine, ...]:
    if assessment is None:
        return ()
    rows = (
        await session.scalars(
            select(RuleAssessmentRow)
            .where(RuleAssessmentRow.assessment_id == assessment.id)
            .order_by(RuleAssessmentRow.id)
        )
    ).all()
    lines: list[ConditionLine] = []
    for row in rows:
        evidence_ids = _EVIDENCE_IDS.validate_json(row.evidence_ids_json)
        evidence = await session.get(EvidenceRow, evidence_ids[0]) if evidence_ids else None
        override = review.override_for(row.id) if review else None
        lines.append(
            ConditionLine(
                automatic_status=row.status,
                override_status=override,
                effective_status=override or row.status,
                explanation=row.explanation,
                source_url=evidence.source_url if evidence else None,
                page=evidence.page if evidence else None,
                section_path=evidence.section_path if evidence else None,
            )
        )
    return tuple(lines)


async def _audit_lines(
    session: AsyncSession,
    case_id: int,
    assessments: tuple[AssessmentRow, ...],
    timezone: ZoneInfo,
) -> tuple[AuditLine, ...]:
    assessment_ids = tuple(str(item.id) for item in assessments)
    assessment_filter = (
        and_(
            AuditEventRow.entity_type == "assessment",
            AuditEventRow.entity_id.in_(assessment_ids),
        )
        if assessment_ids
        else AuditEventRow.id < 0
    )
    rows = (
        await session.scalars(
            select(AuditEventRow)
            .where(
                or_(
                    and_(
                        AuditEventRow.entity_type == "case",
                        AuditEventRow.entity_id == str(case_id),
                    ),
                    assessment_filter,
                )
            )
            .order_by(AuditEventRow.created_at, AuditEventRow.id)
        )
    ).all()
    return tuple(
        AuditLine(
            action=row.action,
            actor=row.actor_name,
            reason=row.reason,
            before_state=row.before_json or "-",
            after_state=row.after_json or "-",
            occurred_at=_display_time(row.created_at, timezone),
        )
        for row in rows
    )


def _display_time(value: datetime, timezone: ZoneInfo) -> str:
    return _as_utc(value).astimezone(timezone).strftime("%Y-%m-%d %H:%M KST")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["ConsultationData", "load_consultation_data"]
