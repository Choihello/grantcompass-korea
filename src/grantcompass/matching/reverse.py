"""Evidence-preserving reverse matching across every managed company."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import assert_never, final

from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.cli.profiles import profile_from_row
from grantcompass.domain.cases import ManagedCompanyId
from grantcompass.domain.eligibility import ApplicantProfileId
from grantcompass.domain.enums import FinalStatus
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.reverse import (
    CompanyInputError,
    CompanyInputErrorCode,
    CompanyMatch,
    ReverseMatchingError,
    ReverseMatchingErrorCode,
)
from grantcompass.matching.reverse_input_errors import (
    assessment_input_error,
    profile_input_error,
    program_input_error,
)
from grantcompass.matching.reverse_inputs import (
    MatchContext,
    ReverseCompanyInput,
    load_reverse_inputs,
)
from grantcompass.rules.deterministic import (
    AssessmentInputError,
    DeterministicAssessmentEngine,
)
from grantcompass.storage.assessment_runs import append_assessment
from grantcompass.storage.table_cases import ManagedCompanyRow


@dataclass(frozen=True, slots=True)
class _Candidate:
    row: ManagedCompanyRow
    profile_id: ApplicantProfileId
    profile_name: str | None


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
            inputs = await load_reverse_inputs(self._session, program_id)
            matches = [
                await self._match_company(candidate, inputs.context, assessed_at)
                for candidate in inputs.companies
            ]
        return tuple(sorted(matches, key=_match_key))

    async def _match_company(
        self,
        candidate_input: ReverseCompanyInput,
        context: MatchContext,
        assessed_at: datetime,
    ) -> CompanyMatch:
        row = candidate_input.company
        profile_id = ApplicantProfileId(row.profile_id)
        candidate = _Candidate(row, profile_id, None)
        if candidate_input.profile is None:
            return _unmatched(
                candidate, context, profile_input_error(CliErrorCode.PROFILE_NOT_FOUND)
            )
        try:
            profile = profile_from_row(candidate_input.profile)
        except CliError as error:
            return _unmatched(candidate, context, profile_input_error(error.code))
        candidate = _Candidate(row, profile_id, profile.display_name)
        if context.identity_error is not None:
            return _unmatched(candidate, context, context.identity_error)
        if context.program.errors:
            return _unmatched(candidate, context, program_input_error(context.program.errors))
        try:
            assessment = DeterministicAssessmentEngine().assess(
                profile,
                context.program.rules,
                assessed_at,
                reference_date=context.program.program.reference_date,
            )
        except AssessmentInputError as error:
            return _unmatched(candidate, context, assessment_input_error(error.code))
        persisted = await append_assessment(self._session, assessment)
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
    candidate: _Candidate,
    context: MatchContext,
    code: CompanyInputErrorCode,
) -> CompanyMatch:
    return CompanyMatch(
        ManagedCompanyId(candidate.row.id),
        candidate.profile_id,
        candidate.profile_name,
        candidate.row.owner_name,
        candidate.row.active,
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
