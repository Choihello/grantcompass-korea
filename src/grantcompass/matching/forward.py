"""Deterministic presentation ranking over immutable assessment outcomes."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum, unique
from typing import ClassVar, Final, Literal, override

from grantcompass.domain.eligibility import AssessmentResult
from grantcompass.domain.enums import FinalStatus
from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.domain.programs import Program

__all__ = [
    "ChangeImpact",
    "Deadline",
    "DeadlineState",
    "MatchingInputError",
    "MatchingInputErrorCode",
    "ProgramMatch",
    "rank_programs",
    "validate_change_impacts",
]

type MatchingInputErrorCode = Literal[
    "duplicate_program_id",
    "duplicate_assessment_program_id",
    "mismatched_program_ids",
    "duplicate_change_impact",
    "unknown_impact_program_id",
    "unknown_impact_assessment_id",
]

_DUPLICATE_PROGRAM_ID: Final[MatchingInputErrorCode] = "duplicate_program_id"
_DUPLICATE_ASSESSMENT_PROGRAM_ID: Final[MatchingInputErrorCode] = "duplicate_assessment_program_id"
_MISMATCHED_PROGRAM_IDS: Final[MatchingInputErrorCode] = "mismatched_program_ids"
_DUPLICATE_CHANGE_IMPACT: Final[MatchingInputErrorCode] = "duplicate_change_impact"
_UNKNOWN_IMPACT_PROGRAM_ID: Final[MatchingInputErrorCode] = "unknown_impact_program_id"
_UNKNOWN_IMPACT_ASSESSMENT_ID: Final[MatchingInputErrorCode] = "unknown_impact_assessment_id"
_STATUS_RANKS: Final[dict[FinalStatus, int]] = {
    FinalStatus.ELIGIBLE: 0,
    FinalStatus.CONDITIONAL: 1,
    FinalStatus.NEEDS_REVIEW: 2,
    FinalStatus.INELIGIBLE: 3,
}


@unique
class DeadlineState(StrEnum):
    """Typed state of a program application deadline."""

    OPEN = "open"
    MISSING = "missing"
    EXPIRED = "expired"


_DEADLINE_RANKS: Final[dict[DeadlineState, int]] = {
    DeadlineState.OPEN: 0,
    DeadlineState.MISSING: 1,
    DeadlineState.EXPIRED: 2,
}


@dataclass(frozen=True, slots=True)
class Deadline:
    """Immutable application deadline state used by matching and reporting."""

    state: DeadlineState
    date: date | None
    days_remaining: int | None


@dataclass(frozen=True, slots=True)
class ChangeImpact:
    """Display-only notice change metadata attached to an assessment."""

    program_id: ProgramId
    changed_fields: tuple[str, ...]
    impacted_assessment_ids: tuple[AssessmentId, ...]


@dataclass(frozen=True, slots=True)
class ProgramMatch:
    """One program paired with its original assessment and deadline state."""

    program: Program
    assessment: AssessmentResult
    deadline: Deadline
    change_impact: ChangeImpact | None = None


class MatchingInputError(Exception):
    """Finite error for duplicate or unresolved matching inputs."""

    __slots__: ClassVar[tuple[str, ...]] = ("code",)

    code: MatchingInputErrorCode

    def __init__(self, code: MatchingInputErrorCode) -> None:
        """Create an exception carrying the finite machine code."""
        super().__init__(code)
        self.code = code

    @override
    def __str__(self) -> str:
        return self.code


def rank_programs(
    assessments: tuple[AssessmentResult, ...] | list[AssessmentResult],
    programs: tuple[Program, ...] | list[Program],
    today: date,
) -> tuple[ProgramMatch, ...]:
    """Rank programs without changing any stored eligibility value."""
    program_by_id = _index_programs(programs)
    assessment_by_id = _index_assessments(assessments)
    if set(program_by_id) != set(assessment_by_id):
        raise MatchingInputError(_MISMATCHED_PROGRAM_IDS)
    matches = tuple(
        ProgramMatch(
            program=program_by_id[program_id],
            assessment=assessment_by_id[program_id],
            deadline=_deadline_for(program_by_id[program_id], today),
        )
        for program_id in program_by_id
    )
    return tuple(sorted(matches, key=_ranking_key))


def validate_change_impacts(
    match: ProgramMatch,
    impacts: tuple[ChangeImpact, ...] | list[ChangeImpact],
) -> ChangeImpact | None:
    """Resolve one matching change impact or raise a finite input error."""
    if len(impacts) > 1:
        raise MatchingInputError(_DUPLICATE_CHANGE_IMPACT)
    if not impacts:
        return None
    impact = impacts[0]
    if impact.program_id != match.program.id:
        raise MatchingInputError(_UNKNOWN_IMPACT_PROGRAM_ID)
    assessment_id = match.assessment.id
    if (
        assessment_id is None
        or not impact.impacted_assessment_ids
        or len(set(impact.impacted_assessment_ids)) != len(impact.impacted_assessment_ids)
        or any(impacted_id != assessment_id for impacted_id in impact.impacted_assessment_ids)
    ):
        raise MatchingInputError(_UNKNOWN_IMPACT_ASSESSMENT_ID)
    return impact


def _index_programs(programs: tuple[Program, ...] | list[Program]) -> dict[ProgramId, Program]:
    indexed: dict[ProgramId, Program] = {}
    for program in programs:
        if program.id in indexed:
            raise MatchingInputError(_DUPLICATE_PROGRAM_ID)
        indexed[program.id] = program
    return indexed


def _index_assessments(
    assessments: tuple[AssessmentResult, ...] | list[AssessmentResult],
) -> dict[ProgramId, AssessmentResult]:
    indexed: dict[ProgramId, AssessmentResult] = {}
    for assessment in assessments:
        if assessment.program_id in indexed:
            raise MatchingInputError(_DUPLICATE_ASSESSMENT_PROGRAM_ID)
        indexed[assessment.program_id] = assessment
    return indexed


def _deadline_for(program: Program, today: date) -> Deadline:
    application_end = program.application_end
    if application_end is None:
        return Deadline(DeadlineState.MISSING, None, None)
    days_remaining = (application_end - today).days
    if days_remaining < 0:
        return Deadline(DeadlineState.EXPIRED, application_end, days_remaining)
    return Deadline(DeadlineState.OPEN, application_end, days_remaining)


def _ranking_key(match: ProgramMatch) -> tuple[int, int, int, int]:
    return (
        _status_rank(match.assessment.final_status),
        _deadline_rank(match.deadline.state),
        _deadline_days(match.deadline),
        int(match.program.id),
    )


def _status_rank(status: FinalStatus) -> int:
    return _STATUS_RANKS[status]


def _deadline_rank(state: DeadlineState) -> int:
    return _DEADLINE_RANKS[state]


def _deadline_days(deadline: Deadline) -> int:
    if deadline.state is DeadlineState.OPEN and deadline.days_remaining is not None:
        return deadline.days_remaining
    return 0
