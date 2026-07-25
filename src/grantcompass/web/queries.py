"""Read-only view queries for the institution workspace."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.freshness import load_one_source_freshness
from grantcompass.domain.enums import FreshnessStatus, SourceName
from grantcompass.storage.table_documents import EvidenceRow, rule_evidence
from grantcompass.storage.table_eligibility import EligibilityRuleRow
from grantcompass.storage.table_notice_analysis import (
    ChangeSetRow,
    CurrentNoticeVersionRow,
)
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, ProgramRow
from grantcompass.web.match_queries import MatchEntry, latest_matches


@dataclass(frozen=True, slots=True)
class ProgramListEntry:
    """One row in the public-notice review ledger."""

    id: int
    title: str
    organization: str
    application_end: date | None
    sources: str
    freshness: str
    badges: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NoticeEntry:
    """One current official source retained for a program."""

    source: str
    detail_url: str
    collected_at: str
    attachments: tuple[AttachmentRow, ...]


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    """One eligibility rule and exact official evidence coordinate."""

    kind: str
    review_status: str
    rule_version: str
    source_url: str | None
    page: int | None
    section_path: str | None


@dataclass(frozen=True, slots=True)
class ProgramDetail:
    """Complete read model for one program dossier."""

    id: int
    title: str
    organization: str
    application_start: date | None
    application_end: date | None
    notices: tuple[NoticeEntry, ...]
    evidence: tuple[EvidenceEntry, ...]
    matches: tuple[MatchEntry, ...]


async def list_programs(
    session: AsyncSession,
    now: datetime,
) -> tuple[ProgramListEntry, ...]:
    """Return current programs with visible freshness and change badges."""
    programs = (await session.scalars(select(ProgramRow).order_by(ProgramRow.id.desc()))).all()
    entries: list[ProgramListEntry] = []
    freshness_by_source: dict[SourceName, FreshnessStatus] = {}
    current = now.astimezone(UTC)
    for program in programs:
        notices = await _current_notices(session, program.id)
        changed = await session.scalar(
            select(ChangeSetRow.id)
            .join(
                CurrentNoticeVersionRow,
                CurrentNoticeVersionRow.version_id == ChangeSetRow.current_version_id,
            )
            .join(
                NoticeVersionRow,
                NoticeVersionRow.id == CurrentNoticeVersionRow.version_id,
            )
            .where(NoticeVersionRow.program_id == program.id)
            .limit(1)
        )
        source_freshness: list[FreshnessStatus] = []
        for notice in notices:
            try:
                source = SourceName(notice.source)
            except ValueError:
                source_freshness.append(FreshnessStatus.STALE)
                continue
            if source not in freshness_by_source:
                freshness_by_source[source] = (
                    await load_one_source_freshness(session, source)
                ).status
            source_freshness.append(freshness_by_source[source])
        badges: list[str] = []
        if current - _as_utc(program.created_at) <= timedelta(days=7):
            badges.append("신규")
        if changed is not None:
            badges.append("변경")
        if program.application_end is not None and program.application_end < current.date():
            badges.append("종료")
        entries.append(
            ProgramListEntry(
                id=program.id,
                title=program.title,
                organization=program.organization or "기관 미상",
                application_end=program.application_end,
                sources=" · ".join(item.source for item in notices) or "출처 없음",
                freshness=(
                    FreshnessStatus.FRESH.value
                    if source_freshness
                    and all(status is FreshnessStatus.FRESH for status in source_freshness)
                    else FreshnessStatus.STALE.value
                ),
                badges=tuple(badges),
            )
        )
    return tuple(entries)


async def get_program_detail(
    session: AsyncSession,
    program_id: int,
    timezone: str,
) -> ProgramDetail | None:
    """Return the evidence-first detail read model for one program."""
    program = await session.get(ProgramRow, program_id)
    if program is None:
        return None
    notices = await _current_notices(session, program.id)
    notice_ids = tuple(item.id for item in notices)
    attachments = (
        tuple(
            (
                await session.scalars(
                    select(AttachmentRow)
                    .where(AttachmentRow.notice_version_id.in_(notice_ids))
                    .order_by(AttachmentRow.id)
                )
            ).all()
        )
        if notice_ids
        else ()
    )
    attachments_by_notice: dict[int, list[AttachmentRow]] = {}
    for attachment in attachments:
        attachments_by_notice.setdefault(attachment.notice_version_id, []).append(attachment)
    rules = (
        await session.scalars(
            select(EligibilityRuleRow)
            .where(EligibilityRuleRow.program_id == program.id)
            .order_by(EligibilityRuleRow.id)
        )
    ).all()
    evidence_entries: list[EvidenceEntry] = []
    for rule in rules:
        evidence = await session.scalar(
            select(EvidenceRow)
            .join(rule_evidence, rule_evidence.c.evidence_id == EvidenceRow.id)
            .where(rule_evidence.c.rule_id == rule.id)
            .order_by(EvidenceRow.id)
            .limit(1)
        )
        evidence_entries.append(
            EvidenceEntry(
                rule.kind,
                rule.review_status,
                rule.rule_version,
                evidence.source_url if evidence else None,
                evidence.page if evidence else None,
                evidence.section_path if evidence else None,
            )
        )
    target_timezone = ZoneInfo(timezone)
    return ProgramDetail(
        id=program.id,
        title=program.title,
        organization=program.organization or "기관 미상",
        application_start=program.application_start,
        application_end=program.application_end,
        notices=tuple(
            NoticeEntry(
                item.source,
                item.detail_url,
                _display_time(item.collected_at, target_timezone),
                tuple(attachments_by_notice.get(item.id, ())),
            )
            for item in notices
        ),
        evidence=tuple(evidence_entries),
        matches=await latest_matches(session, program.id),
    )


async def _current_notices(session: AsyncSession, program_id: int) -> tuple[NoticeVersionRow, ...]:
    return tuple(
        (
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
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _display_time(value: datetime, timezone: ZoneInfo) -> str:
    return _as_utc(value).astimezone(timezone).strftime("%Y-%m-%d %H:%M KST")
