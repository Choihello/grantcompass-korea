"""Explicit current notice state independent from immutable version creation order."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.programs import canonical_key_from_fields
from grantcompass.storage.notice_snapshots import NoticeSnapshot, parse_snapshot
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import NoticeVersionRow, ProgramRow


@dataclass(frozen=True, slots=True)
class LegacyRefreshState:
    """Non-authoritative legacy row refresh inputs derived from current pointers."""

    program_id: ProgramId
    snapshots: dict[SourceName, NoticeSnapshot]
    detected_at: datetime


async def read_current_version(
    session: AsyncSession,
    source: SourceName,
    source_notice_id: str,
) -> NoticeVersionRow | None:
    """Resolve the explicit current version for one source notice identity."""
    return await session.scalar(
        select(NoticeVersionRow)
        .join(
            CurrentNoticeVersionRow,
            CurrentNoticeVersionRow.version_id == NoticeVersionRow.id,
        )
        .where(
            CurrentNoticeVersionRow.source == source.value,
            CurrentNoticeVersionRow.source_notice_id == source_notice_id,
        )
    )


async def point_to_version(session: AsyncSession, version: NoticeVersionRow) -> None:
    """Create or move the explicit pointer without mutating its immutable version."""
    pointer = await session.scalar(
        select(CurrentNoticeVersionRow).where(
            CurrentNoticeVersionRow.source == version.source,
            CurrentNoticeVersionRow.source_notice_id == version.source_notice_id,
        )
    )
    if pointer is None:
        session.add(
            CurrentNoticeVersionRow(
                source=version.source,
                source_notice_id=version.source_notice_id,
                version_id=version.id,
            )
        )
    else:
        pointer.version_id = version.id


async def load_current_snapshots(
    session: AsyncSession,
    program_id: ProgramId,
) -> dict[SourceName, NoticeSnapshot]:
    """Load only explicitly current snapshots for one canonical program."""
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
    snapshots: dict[SourceName, NoticeSnapshot] = {}
    for row in rows:
        snapshot = parse_snapshot(row.normalized_json)
        if snapshot is not None:
            snapshots[SourceName(row.source)] = snapshot
    return snapshots


async def refresh_legacy_program(session: AsyncSession, state: LegacyRefreshState) -> None:
    """Refresh non-authoritative storage columns only for consensus values."""
    if not state.snapshots:
        return
    program = (
        await session.scalars(select(ProgramRow).where(ProgramRow.id == state.program_id))
    ).one()
    titles = {item.title for item in state.snapshots.values()}
    organizations = {item.organization for item in state.snapshots.values()}
    starts = {item.application_start for item in state.snapshots.values()}
    ends = {item.application_end for item in state.snapshots.values()}
    if len(titles) == 1:
        program.title = next(iter(titles))
    if len(organizations) == 1:
        program.organization = next(iter(organizations))
    if len(starts) == 1:
        program.application_start = next(iter(starts))
    if len(ends) == 1:
        program.application_end = next(iter(ends))
    reference_rows = (
        await session.scalars(
            select(NoticeVersionRow)
            .join(
                CurrentNoticeVersionRow,
                CurrentNoticeVersionRow.version_id == NoticeVersionRow.id,
            )
            .where(NoticeVersionRow.program_id == state.program_id)
            .order_by(
                NoticeVersionRow.reference_date,
                NoticeVersionRow.reference_date_source,
                NoticeVersionRow.source,
                NoticeVersionRow.source_notice_id,
                NoticeVersionRow.id,
            )
        )
    ).all()
    if reference_rows:
        reference = reference_rows[0]
        program.reference_date = reference.reference_date
        program.reference_date_source = reference.reference_date_source
    complete = (
        bool(program.title.strip())
        and bool(program.organization)
        and program.application_end is not None
    )
    if complete:
        new_key = canonical_key_from_fields(
            program.title,
            program.organization,
            program.application_end,
        )
        collision = await session.scalar(
            select(ProgramRow.id).where(
                ProgramRow.canonical_key == new_key,
                ProgramRow.id != state.program_id,
            )
        )
        if collision is None:
            program.canonical_key = new_key
    program.updated_at = state.detected_at
