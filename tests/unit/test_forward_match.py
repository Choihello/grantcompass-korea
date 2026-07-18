from datetime import UTC, date, datetime

import pytest

from grantcompass.domain.documents import EvidenceId
from grantcompass.domain.eligibility import (
    ApplicantProfileId,
    AssessmentResult,
    EligibilityRuleId,
    RuleAssessment,
)
from grantcompass.domain.enums import ConditionStatus, FinalStatus, ReviewStatus
from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.domain.programs import Program
from grantcompass.matching.forward import DeadlineState, MatchingInputError, rank_programs

NOW = datetime(2026, 2, 27, tzinfo=UTC)


def make_program(program_id: int, deadline: date | None) -> Program:
    return Program(
        id=ProgramId(program_id),
        canonical_key=f"program-{program_id}",
        title=f"지원사업 {program_id}",
        organization="기관",
        application_start=None,
        application_end=deadline,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def make_assessment(
    program_id: int,
    status: FinalStatus,
    assessment_id: int,
    condition_status: ConditionStatus = ConditionStatus.SATISFIED,
) -> AssessmentResult:
    item = RuleAssessment(
        rule_id=EligibilityRuleId(program_id),
        status=condition_status,
        explanation="fixture",
        evidence_ids=(EvidenceId(program_id),),
        error_id=None,
    )
    return AssessmentResult(
        id=AssessmentId(assessment_id),
        program_id=ProgramId(program_id),
        profile_id=ApplicantProfileId(99),
        final_status=status,
        review_status=ReviewStatus.AUTOMATIC,
        rule_version="rules-v1",
        assessed_at=NOW,
        items=(item,),
    )


def test_rank_preserves_assessment_and_orders_status_deadline_and_id() -> None:
    programs = (
        make_program(4, date(2026, 2, 26)),
        make_program(3, None),
        make_program(2, date(2026, 2, 28)),
        make_program(1, date(2026, 3, 5)),
    )
    assessments = (
        make_assessment(4, FinalStatus.ELIGIBLE, 104),
        make_assessment(3, FinalStatus.ELIGIBLE, 103),
        make_assessment(2, FinalStatus.ELIGIBLE, 102),
        make_assessment(1, FinalStatus.ELIGIBLE, 101),
    )
    ranked = rank_programs(assessments, programs, date(2026, 2, 27))

    assert tuple(item.program.id for item in ranked) == (
        ProgramId(2),
        ProgramId(1),
        ProgramId(3),
        ProgramId(4),
    )
    assert ranked[0].deadline.state is DeadlineState.OPEN
    assert ranked[0].deadline.days_remaining == 1
    assert ranked[2].deadline.state is DeadlineState.MISSING
    assert ranked[3].deadline.state is DeadlineState.EXPIRED
    assert ranked[0].assessment is assessments[2]
    assert ranked[0].assessment.final_status is FinalStatus.ELIGIBLE
    assert ranked[0].assessment.items == assessments[2].items


def test_rank_is_invariant_to_input_permutation_and_status_buckets() -> None:
    programs = (
        make_program(10, date(2026, 3, 2)),
        make_program(2, date(2026, 3, 2)),
    )
    assessments = (
        make_assessment(10, FinalStatus.ELIGIBLE, 110),
        make_assessment(2, FinalStatus.ELIGIBLE, 102),
    )
    first = rank_programs(assessments, programs, date(2026, 2, 27))
    second = rank_programs(
        tuple(reversed(assessments)),
        tuple(reversed(programs)),
        date(2026, 2, 27),
    )

    assert tuple(item.program.id for item in first) == (ProgramId(2), ProgramId(10))
    assert first == second


def test_rank_rejects_duplicate_and_mismatched_id_sets() -> None:
    duplicate_programs = (make_program(1, None), make_program(1, date(2026, 3, 1)))
    one_assessment = (make_assessment(1, FinalStatus.ELIGIBLE, 1),)

    with pytest.raises(MatchingInputError) as duplicate_error:
        _ = rank_programs(one_assessment, duplicate_programs, date(2026, 2, 27))
    assert duplicate_error.value.code == "duplicate_program_id"

    with pytest.raises(MatchingInputError) as mismatch_error:
        _ = rank_programs(one_assessment, (make_program(2, None),), date(2026, 2, 27))
    assert mismatch_error.value.code == "mismatched_program_ids"


def test_rank_orders_all_status_buckets_and_handles_leap_day_deadlines() -> None:
    programs = tuple(make_program(index, date(2028, 2, 29)) for index in range(1, 5))
    assessments = tuple(
        make_assessment(
            index,
            status,
            100 + index,
        )
        for index, status in enumerate(
            (
                FinalStatus.ELIGIBLE,
                FinalStatus.CONDITIONAL,
                FinalStatus.NEEDS_REVIEW,
                FinalStatus.INELIGIBLE,
            ),
            start=1,
        )
    )

    ranked = rank_programs(assessments, programs, date(2028, 2, 28))

    assert tuple(item.assessment.final_status for item in ranked) == (
        FinalStatus.ELIGIBLE,
        FinalStatus.CONDITIONAL,
        FinalStatus.NEEDS_REVIEW,
        FinalStatus.INELIGIBLE,
    )
    assert ranked[0].deadline.date == date(2028, 2, 29)
    assert ranked[0].deadline.days_remaining == 1
    expired = rank_programs(
        (assessments[0],),
        (programs[0],),
        date(2028, 3, 1),
    )[0]
    assert expired.deadline.state is DeadlineState.EXPIRED


def test_rank_rejects_duplicate_assessment_program_ids() -> None:
    assessments = (
        make_assessment(1, FinalStatus.ELIGIBLE, 101),
        make_assessment(1, FinalStatus.CONDITIONAL, 102),
    )

    with pytest.raises(MatchingInputError) as error:
        _ = rank_programs(assessments, (make_program(1, None),), date(2026, 2, 27))
    assert error.value.code == "duplicate_assessment_program_id"
