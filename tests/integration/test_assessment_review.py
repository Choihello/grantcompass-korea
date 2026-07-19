from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import AssessmentReviewCommand
from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus, FinalStatus, ReviewStatus
from grantcompass.domain.reviews import ConditionOverride, RuleAssessmentId
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment

pytestmark = pytest.mark.anyio


async def test_empty_override_review_preserves_automatic_result_and_appends_audit(
    db_session: AsyncSession,
) -> None:
    # Given: one immutable automatic assessment.
    assessment_id = await seed_assessment(db_session)
    repository = AssessmentRepository(db_session)

    # When: a worker verifies it without changing any condition.
    review = await repository.review(
        AssessmentReviewCommand(
            assessment_id=assessment_id,
            overrides=(),
            actor="담당자",
            reason="증빙 확인",
            reviewed_at=REFERENCE_TIME,
        )
    )

    # Then: review progress and one attributed audit event are visible.
    events = await repository.audit_events(assessment_id)
    assert review.review_status is ReviewStatus.REVIEWED
    assert review.automatic_final_status is review.effective_final_status
    assert review.overrides == ()
    assert len(events) == 1


async def test_nonempty_override_preserves_every_automatic_field(
    db_session: AsyncSession,
) -> None:
    # Given: one eligible automatic condition and its immutable evidence identity.
    assessment_id = await seed_assessment(db_session)
    automatic_row = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment_id))
        )
    ).one()
    original = await db_session.get(AssessmentRow, int(assessment_id))
    assert original is not None
    original_values = (
        original.final_status,
        original.rule_version,
        original.assessed_at,
        automatic_row.status,
        automatic_row.explanation,
        automatic_row.evidence_ids_json,
    )
    override = ConditionOverride(
        RuleAssessmentId(automatic_row.id),
        EligibilityRuleId(automatic_row.rule_id),
        ConditionStatus.UNSATISFIED,
    )
    await db_session.commit()

    # When: a worker attributes one explicit condition override.
    review = await AssessmentRepository(db_session).review(
        AssessmentReviewCommand(
            assessment_id,
            (override,),
            "담당자",
            "등록증 확인",
            REFERENCE_TIME + timedelta(minutes=1),
        )
    )

    # Then: effective state changes while every automatic database value remains unchanged.
    stored = await db_session.get(AssessmentRow, int(assessment_id))
    stored_item = await db_session.get(RuleAssessmentRow, automatic_row.id)
    assert stored is not None
    assert stored_item is not None
    assert review.automatic_final_status is FinalStatus.ELIGIBLE
    assert review.effective_final_status is FinalStatus.INELIGIBLE
    assert review.conditions[0].automatic_status is ConditionStatus.SATISFIED
    assert review.conditions[0].override_status is ConditionStatus.UNSATISFIED
    assert review.conditions[0].effective_status is ConditionStatus.UNSATISFIED
    assert stored.review_status == ReviewStatus.REVIEWED.value
    assert (
        stored.final_status,
        stored.rule_version,
        stored.assessed_at,
        stored_item.status,
        stored_item.explanation,
        stored_item.evidence_ids_json,
    ) == original_values
