from typing import Literal, assert_never

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import AuditErrorCode, AuditValidationError
from grantcompass.domain.ids import AssessmentId
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment

pytestmark = pytest.mark.anyio

type StoredAssessmentCorruption = Literal[
    "final_status",
    "review_status",
    "condition_status",
    "evidence_json",
]


@pytest.mark.parametrize(
    "corruption",
    ["final_status", "review_status", "condition_status", "evidence_json"],
)
async def test_corrupted_assessment_state_is_finite_and_not_reviewed(
    db_session: AsyncSession,
    corruption: StoredAssessmentCorruption,
) -> None:
    # Given: one persisted assessment with a corrupted enum or evidence JSON boundary.
    assessment_id = await seed_assessment(db_session)
    expected_review_status = await _corrupt_assessment(
        db_session,
        assessment_id,
        corruption,
    )

    # When: the untrusted row crosses the attributed review boundary.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(
                assessment_id,
                (),
                "actor",
                "reason",
                REFERENCE_TIME,
            )
        )

    # Then: corruption is finite and neither review progress nor audit history is fabricated.
    row = await db_session.get(AssessmentRow, int(assessment_id))
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.MALFORMED_ASSESSMENT
    assert row is not None
    assert row.review_status == expected_review_status
    assert event_count == 0


async def test_corrupted_audit_json_is_finite_on_history_read(
    db_session: AsyncSession,
) -> None:
    # Given: one completed review whose append-only JSON was corrupted out of band.
    assessment_id = await seed_assessment(db_session)
    repository = AssessmentRepository(db_session)
    _ = await repository.review(
        AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
    )
    event = (await db_session.scalars(select(AuditEventRow))).one()
    event.after_json = "{"
    await db_session.commit()

    # When: typed audit history attempts to parse the corrupted state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await repository.audit_events(assessment_id)

    # Then: the repository exposes one finite corruption code.
    assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT


async def _corrupt_assessment(
    session: AsyncSession,
    assessment_id: AssessmentId,
    corruption: StoredAssessmentCorruption,
) -> str:
    assessment = await session.get(AssessmentRow, int(assessment_id))
    condition = (
        await session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment_id))
        )
    ).one()
    assert assessment is not None
    match corruption:
        case "final_status":
            assessment.final_status = "broken"
        case "review_status":
            assessment.review_status = "broken"
        case "condition_status":
            condition.status = "broken"
        case "evidence_json":
            condition.evidence_ids_json = "{"
        case _:
            assert_never(corruption)
    expected_review_status = assessment.review_status
    await session.commit()
    return expected_review_status
