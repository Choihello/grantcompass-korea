"""Database input loading for one institutional reverse-matching run."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.program_queries import ProgramQueryRepository, ProgramRules
from grantcompass.domain.enums import SourceName
from grantcompass.domain.ids import NoticeVersionId, ProgramId
from grantcompass.domain.reverse import (
    CompanyInputErrorCode,
    NoticeContentIdentity,
    ReverseMatchingError,
    ReverseMatchingErrorCode,
)
from grantcompass.storage.table_cases import ManagedCompanyRow
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import NoticeVersionRow


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Program rules and current notice identity shared by every candidate."""

    program: ProgramRules
    identities: tuple[NoticeContentIdentity, ...]
    latest_hash: str | None
    identity_error: CompanyInputErrorCode | None


@dataclass(frozen=True, slots=True)
class ReverseInputs:
    """Complete immutable database input for one reverse-matching run."""

    context: MatchContext
    companies: tuple[ManagedCompanyRow, ...]


async def load_reverse_inputs(
    session: AsyncSession,
    program_id: ProgramId,
) -> ReverseInputs:
    """Load program, notice identity, and managed candidates in one transaction."""
    program = await _program_record(session, program_id)
    identities, latest_hash, identity_error = await _content_identities(session, program_id)
    companies = tuple((await session.scalars(select(ManagedCompanyRow))).all())
    return ReverseInputs(
        MatchContext(program, identities, latest_hash, identity_error),
        companies,
    )


async def _program_record(session: AsyncSession, program_id: ProgramId) -> ProgramRules:
    records = await ProgramQueryRepository(session).list_program_rules()
    for record in records:
        if record.program.id == program_id:
            return record
    raise ReverseMatchingError(ReverseMatchingErrorCode.UNKNOWN_PROGRAM)


async def _content_identities(
    session: AsyncSession,
    program_id: ProgramId,
) -> tuple[
    tuple[NoticeContentIdentity, ...],
    str | None,
    CompanyInputErrorCode | None,
]:
    rows = (
        await session.scalars(
            select(NoticeVersionRow)
            .join(
                CurrentNoticeVersionRow,
                CurrentNoticeVersionRow.version_id == NoticeVersionRow.id,
            )
            .where(NoticeVersionRow.program_id == int(program_id))
        )
    ).all()
    if not rows:
        return (), None, CompanyInputErrorCode.MISSING_CURRENT_NOTICE
    try:
        identities = tuple(
            sorted(
                (
                    NoticeContentIdentity(
                        SourceName(row.source),
                        NoticeVersionId(row.id),
                        row.content_hash,
                    )
                    for row in rows
                ),
                key=lambda item: (
                    item.source.value,
                    int(item.notice_version_id),
                    item.content_hash,
                ),
            )
        )
    except ValueError:
        return (), None, CompanyInputErrorCode.MALFORMED_NOTICE_SOURCE
    latest = max(rows, key=lambda row: (row.collected_at, row.id))
    return identities, latest.content_hash, None
