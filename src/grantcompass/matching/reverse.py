"""Evidence-preserving reverse matching across every managed company."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import assert_never, final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.errors import CliError
from grantcompass.cli.profiles import ProfileRepository
from grantcompass.cli.program_queries import ProgramQueryRepository, ProgramRules
from grantcompass.domain.cases import ManagedCompanyId
from grantcompass.domain.eligibility import ApplicantProfileId
from grantcompass.domain.enums import FinalStatus, SourceName
from grantcompass.domain.ids import NoticeVersionId, ProgramId
from grantcompass.domain.reverse import (
    CompanyInputError,
    CompanyInputErrorCode,
    CompanyMatch,
    NoticeContentIdentity,
    ReverseMatchingError,
    ReverseMatchingErrorCode,
)
from grantcompass.matching.reverse_input_errors import (
    assessment_input_error,
    profile_input_error,
    program_input_error,
)
from grantcompass.rules.deterministic import (
    AssessmentInputError,
    DeterministicAssessmentEngine,
)
from grantcompass.storage.assessment_runs import persist_assessment
from grantcompass.storage.table_cases import ManagedCompanyRow
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import NoticeVersionRow


@dataclass(frozen=True, slots=True)
class _MatchContext:
    program: ProgramRules
    identities: tuple[NoticeContentIdentity, ...]
    latest_hash: str | None
    identity_error: CompanyInputErrorCode | None


@final
class ReverseMatchingService:
    """Assess one program for every managed company without filtering outcomes."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind reverse matching to one caller-owned async unit of work."""
        self._session = session

    async def reverse_match(
        self,
        program_id: ProgramId,
        assessed_at: datetime,
    ) -> tuple[CompanyMatch, ...]:
        """Persist this invocation's complete assessments and return every company."""
        _validate_assessed_at(assessed_at)
        async with self._session.begin():
            program = await self._program_record(program_id)
            identities, latest_hash, identity_error = await self._content_identities(program_id)
            context = _MatchContext(
                program,
                identities,
                latest_hash,
                identity_error,
            )
            rows = (await self._session.scalars(select(ManagedCompanyRow))).all()
            matches = [await self._match_company(row, context, assessed_at) for row in rows]
        return tuple(sorted(matches, key=_match_key))

    async def _program_record(self, program_id: ProgramId) -> ProgramRules:
        records = await ProgramQueryRepository(self._session).list_program_rules()
        for record in records:
            if record.program.id == program_id:
                return record
        raise ReverseMatchingError(ReverseMatchingErrorCode.UNKNOWN_PROGRAM)

    async def _content_identities(
        self,
        program_id: ProgramId,
    ) -> tuple[
        tuple[NoticeContentIdentity, ...],
        str | None,
        CompanyInputErrorCode | None,
    ]:
        rows = (
            await self._session.scalars(
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

    async def _match_company(
        self,
        row: ManagedCompanyRow,
        context: _MatchContext,
        assessed_at: datetime,
    ) -> CompanyMatch:
        profile_id = ApplicantProfileId(row.profile_id)
        try:
            profile = await ProfileRepository(self._session).resolve(str(row.profile_id))
        except CliError as error:
            return _unmatched(
                row,
                profile_id,
                None,
                context,
                profile_input_error(error.code),
            )
        if context.identity_error is not None:
            return _unmatched(
                row,
                profile_id,
                profile.display_name,
                context,
                context.identity_error,
            )
        if context.program.errors:
            return _unmatched(
                row,
                profile_id,
                profile.display_name,
                context,
                program_input_error(context.program.errors),
            )
        try:
            assessment = DeterministicAssessmentEngine().assess(
                profile,
                context.program.rules,
                assessed_at,
            )
        except AssessmentInputError as error:
            return _unmatched(
                row,
                profile_id,
                profile.display_name,
                context,
                assessment_input_error(error.code),
            )
        persisted = await persist_assessment(self._session, assessment)
        return CompanyMatch(
            ManagedCompanyId(row.id),
            profile_id,
            profile.display_name,
            row.owner_name,
            row.active,
            persisted,
            context.identities,
            context.latest_hash,
        )


def _validate_assessed_at(assessed_at: datetime) -> None:
    if assessed_at.utcoffset() is None:
        raise ReverseMatchingError(ReverseMatchingErrorCode.NAIVE_ASSESSED_AT)
    if assessed_at.utcoffset() != timedelta(0):
        raise ReverseMatchingError(ReverseMatchingErrorCode.NON_UTC_ASSESSED_AT)


def _unmatched(
    row: ManagedCompanyRow,
    profile_id: ApplicantProfileId,
    profile_name: str | None,
    context: _MatchContext,
    code: CompanyInputErrorCode,
) -> CompanyMatch:
    return CompanyMatch(
        ManagedCompanyId(row.id),
        profile_id,
        profile_name,
        row.owner_name,
        row.active,
        None,
        context.identities,
        context.latest_hash,
        CompanyInputError(code),
    )


def _match_key(item: CompanyMatch) -> tuple[int, int]:
    if item.assessment is None:
        return 4, int(item.managed_company_id)
    match item.assessment.final_status:
        case FinalStatus.ELIGIBLE:
            rank = 0
        case FinalStatus.CONDITIONAL:
            rank = 1
        case FinalStatus.NEEDS_REVIEW:
            rank = 2
        case FinalStatus.INELIGIBLE:
            rank = 3
        case _:
            assert_never(item.assessment.final_status)
    return rank, int(item.managed_company_id)
