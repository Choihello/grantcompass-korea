"""Read-only inspection APIs for merged notice analysis."""

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.domain.ids import NoticeVersionId, ProgramId
from grantcompass.domain.programs import (
    CanonicalProgramView,
    ConflictValue,
    FieldConflict,
    MergeCandidate,
)
from grantcompass.storage.notice_state import load_current_snapshots, read_current_version
from grantcompass.storage.table_notice_analysis import FieldConflictRow, MergeCandidateRow
from grantcompass.storage.table_programs import NoticeVersionRow, ProgramRow

_CONFLICT_VALUES = TypeAdapter(tuple[ConflictValue, ...])


async def read_field_conflicts(
    session: AsyncSession,
    program_id: ProgramId,
) -> tuple[FieldConflict, ...]:
    """Return current typed conflicts for one canonical program."""
    rows = (
        await session.scalars(
            select(FieldConflictRow)
            .where(FieldConflictRow.program_id == program_id)
            .order_by(FieldConflictRow.field_name)
        )
    ).all()
    return tuple(
        FieldConflict(
            program_id=program_id,
            field_name=row.field_name,
            values=_CONFLICT_VALUES.validate_json(row.values_json),
        )
        for row in rows
    )


async def read_merge_candidates(session: AsyncSession) -> tuple[MergeCandidate, ...]:
    """Return all merge-review candidates in deterministic pair order."""
    rows = (
        await session.scalars(
            select(MergeCandidateRow).order_by(
                MergeCandidateRow.left_program_id,
                MergeCandidateRow.right_program_id,
            )
        )
    ).all()
    return tuple(
        MergeCandidate(
            left_program_id=ProgramId(row.left_program_id),
            right_program_id=ProgramId(row.right_program_id),
            title_similarity=row.title_similarity,
            status=row.status,
        )
        for row in rows
    )


async def read_notice_sources(
    session: AsyncSession,
    program_id: ProgramId,
) -> frozenset[SourceName]:
    """Return every official source preserved under one canonical program."""
    sources = (
        await session.scalars(
            select(NoticeVersionRow.source)
            .where(NoticeVersionRow.program_id == program_id)
            .distinct()
        )
    ).all()
    return frozenset(SourceName(value) for value in sources)


async def find_exact_program(
    session: AsyncSession,
    canonical_key: str,
) -> ProgramId | None:
    """Return only an exact three-field conservative merge candidate."""
    value = await session.scalar(
        select(ProgramRow.id).where(ProgramRow.canonical_key == canonical_key)
    )
    return ProgramId(value) if value is not None else None


async def read_current_version_id(
    session: AsyncSession,
    source: SourceName,
    source_notice_id: str,
) -> NoticeVersionId | None:
    """Return the explicit current version ID for one source notice."""
    row = await read_current_version(session, source, source_notice_id)
    return NoticeVersionId(row.id) if row is not None else None


async def read_program_view(
    session: AsyncSession,
    program_id: ProgramId,
) -> CanonicalProgramView:
    """Build a neutral public view from current source consensus and conflicts."""
    snapshots = await load_current_snapshots(session, program_id)
    titles = {item.title for item in snapshots.values()}
    organizations = {item.organization for item in snapshots.values()}
    summaries = {item.summary for item in snapshots.values()}
    starts = {item.application_start for item in snapshots.values()}
    ends = {item.application_end for item in snapshots.values()}
    return CanonicalProgramView(
        id=program_id,
        title=next(iter(titles)) if len(titles) == 1 else None,
        organization=next(iter(organizations)) if len(organizations) == 1 else None,
        summary=next(iter(summaries)) if len(summaries) == 1 else None,
        application_start=next(iter(starts)) if len(starts) == 1 else None,
        application_end=next(iter(ends)) if len(ends) == 1 else None,
        conflicts=await read_field_conflicts(session, program_id),
    )
