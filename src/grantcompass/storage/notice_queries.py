"""Read-only inspection APIs for merged notice analysis."""

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.programs import ConflictValue, FieldConflict, MergeCandidate
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
