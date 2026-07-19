import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import AuditErrorCode, AuditValidationError
from grantcompass.domain.enums import FinalStatus
from grantcompass.domain.json_types import FrozenJsonObject
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.matching.reverse import ReverseMatchingService
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow
from tests.integration.task12_fixtures import (
    REFERENCE_TIME,
    program_id,
    seed_assessment,
    seed_managed_company,
    seed_profile,
    seed_program,
    seed_rule,
)

pytestmark = pytest.mark.anyio


async def test_reverse_review_preserves_automatic_error_and_evidence(
    db_session: AsyncSession,
) -> None:
    # Given: one complete rule whose managed profile lacks the required fact.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile = await seed_profile(db_session)
    profile.regions_json = "[]"
    _ = await seed_managed_company(db_session, profile)
    await db_session.commit()

    # When: reverse matching persists UNKNOWN and a worker reviews it unchanged.
    matches = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )
    assessment = matches[0].assessment
    assert assessment is not None
    assert assessment.id is not None
    review = await AssessmentRepository(db_session).review(
        AssessmentReviewCommand(assessment.id, (), "actor", "reason", REFERENCE_TIME)
    )
    stored = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment.id))
        )
    ).one()
    event = (await AssessmentRepository(db_session).audit_events(assessment.id))[0]

    # Then: automatic, durable, review, and audit views retain the same context.
    assert assessment.items[0].error_id == "missing_profile_fact"
    assert stored.error_id == assessment.items[0].error_id
    assert review.conditions[0].error_id == assessment.items[0].error_id
    assert review.conditions[0].evidence_ids == assessment.items[0].evidence_ids
    assert event.after_json is not None
    conditions = event.after_json["automatic_conditions"]
    assert isinstance(conditions, tuple)
    condition = conditions[0]
    assert isinstance(condition, FrozenJsonObject)
    assert condition["error_id"] == assessment.items[0].error_id


@pytest.mark.parametrize(
    "evidence_json",
    ['["1"]', "[true]", "[1.0]", "[0]", "[-1]", "[[]]", "{}", "{"],
)
async def test_review_rejects_non_integer_evidence_identities(
    db_session: AsyncSession,
    evidence_json: str,
) -> None:
    # Given: one automatic condition with untrusted malformed evidence identities.
    assessment_id = await seed_assessment(db_session)
    condition = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment_id))
        )
    ).one()
    condition.evidence_ids_json = evidence_json
    await db_session.commit()

    # When: the stored identities cross the review boundary.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
        )

    # Then: coercion never fabricates a review or audit event.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.MALFORMED_ASSESSMENT
    assert event_count == 0


async def test_review_rejects_inconsistent_automatic_final_status(
    db_session: AsyncSession,
) -> None:
    # Given: the summary says eligible while its only condition says unsatisfied.
    assessment_id = await seed_assessment(db_session)
    condition = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment_id))
        )
    ).one()
    condition.status = "unsatisfied"
    await db_session.commit()

    # When: a review attempts to consume the inconsistent automatic state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
        )

    # Then: no effective result is fabricated from contradictory storage.
    row = await db_session.get(AssessmentRow, int(assessment_id))
    assert captured.value.code is AuditErrorCode.MALFORMED_ASSESSMENT
    assert row is not None
    assert row.final_status == FinalStatus.ELIGIBLE.value
