from dataclasses import replace
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
from grantcompass.matching.forward import (
    ChangeImpact,
    DeadlineState,
    MatchingInputError,
    rank_programs,
)
from grantcompass.matching.roadmap import RoadmapItemKind, build_roadmap


def make_program(program_id: int, deadline: date | None = None) -> Program:
    return Program(
        id=ProgramId(program_id),
        canonical_key=f"program-{program_id}",
        title="지원사업",
        organization="기관",
        application_start=None,
        application_end=deadline or date(2026, 8, 31),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def make_assessment(
    status: FinalStatus,
    item_statuses: tuple[ConditionStatus, ...],
) -> AssessmentResult:
    items = tuple(
        RuleAssessment(
            rule_id=EligibilityRuleId(index + 1),
            status=item_status,
            explanation="fixture",
            evidence_ids=(EvidenceId(index + 1),),
            error_id=("unknown_fact" if item_status is ConditionStatus.UNKNOWN else None),
        )
        for index, item_status in enumerate(item_statuses)
    )
    return AssessmentResult(
        id=AssessmentId(7),
        program_id=ProgramId(7),
        profile_id=ApplicantProfileId(9),
        final_status=status,
        review_status=ReviewStatus.REVIEW_REQUIRED,
        rule_version="rules-v1",
        assessed_at=datetime(2026, 7, 1, tzinfo=UTC),
        items=items,
    )


def test_conditional_and_unknown_items_retain_rule_evidence_and_deadline() -> None:
    assessment = make_assessment(
        FinalStatus.NEEDS_REVIEW,
        (ConditionStatus.CONDITIONAL, ConditionStatus.UNKNOWN, ConditionStatus.CONFLICT),
    )
    match = rank_programs((assessment,), (make_program(7),), date(2026, 7, 15))[0]
    roadmap = build_roadmap(match)

    assert roadmap.deadline.state is DeadlineState.OPEN
    assert tuple(item.kind for item in roadmap.items) == (
        RoadmapItemKind.ACTION,
        RoadmapItemKind.QUESTION,
        RoadmapItemKind.QUESTION,
    )
    assert roadmap.items[0].rule_id == EligibilityRuleId(1)
    assert roadmap.items[0].evidence_ids == (EvidenceId(1),)
    assert roadmap.items[1].code == "verify_unknown"
    assert roadmap.items[2].code == "verify_conflict"
    assert roadmap.items[2].program_id == ProgramId(7)


def test_empty_needs_review_is_visible_and_change_impact_does_not_change_status() -> None:
    assessment = make_assessment(FinalStatus.NEEDS_REVIEW, ())
    match = rank_programs((assessment,), (make_program(7),), date(2026, 9, 1))[0]
    impact = ChangeImpact(
        program_id=ProgramId(7),
        changed_fields=("application_end",),
        impacted_assessment_ids=(AssessmentId(7),),
    )
    roadmap = build_roadmap(match, (impact,))

    assert len(roadmap.items) == 1
    assert roadmap.items[0].code == "assessment_needs_review"
    assert roadmap.deadline.state is DeadlineState.EXPIRED
    assert roadmap.reassessment_required is True
    assert roadmap.change_impact == impact
    assert roadmap.assessment.final_status is FinalStatus.NEEDS_REVIEW


def test_eligible_unknown_item_remains_a_question_without_a_fabricated_action() -> None:
    assessment = make_assessment(FinalStatus.ELIGIBLE, (ConditionStatus.UNKNOWN,))
    match = rank_programs((assessment,), (make_program(7),), date(2026, 7, 15))[0]

    roadmap = build_roadmap(match)

    assert tuple(item.kind for item in roadmap.items) == (RoadmapItemKind.QUESTION,)
    assert roadmap.items[0].code == "verify_unknown"


def test_change_impact_references_are_not_silently_ignored() -> None:
    assessment = make_assessment(FinalStatus.ELIGIBLE, ())
    match = rank_programs((assessment,), (make_program(7),), date(2026, 7, 15))[0]
    impact = ChangeImpact(
        program_id=ProgramId(7),
        changed_fields=("title",),
        impacted_assessment_ids=(AssessmentId(999),),
    )

    with pytest.raises(MatchingInputError):
        _ = build_roadmap(match, (impact,))


def test_match_impact_is_canonical_and_legacy_copy_must_match() -> None:
    assessment = make_assessment(FinalStatus.ELIGIBLE, ())
    impact = ChangeImpact(
        program_id=ProgramId(7),
        changed_fields=("title",),
        impacted_assessment_ids=(AssessmentId(7),),
    )
    match = rank_programs((assessment,), (make_program(7),), date(2026, 7, 15))[0]
    canonical_match = replace(match, change_impact=impact)

    roadmap = build_roadmap(canonical_match)

    assert roadmap.change_impact == impact
    assert roadmap.reassessment_required is True
    conflicting = replace(impact, changed_fields=("application_end",))
    with pytest.raises(MatchingInputError) as error:
        _ = build_roadmap(canonical_match, (conflicting,))
    assert error.value.code == "inconsistent_change_impact"
