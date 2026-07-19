import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import (
    AuditErrorCode,
    AuditValidationError,
    CaseId,
    CaseTransition,
)
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.storage.repositories import AssessmentRepository, CaseRepository
from grantcompass.storage.table_cases import AuditEventRow, CaseRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment, seed_case

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("before_json", "{"),
        ("before_json", "{}"),
        ("after_json", '{"schema_version":"wrong"}'),
        ("after_json", "{}"),
        ("action", "wrong"),
        ("entity_type", "wrong"),
    ],
)
async def test_history_rejects_malformed_or_wrong_audit_shape(
    db_session: AsyncSession,
    field: str,
    value: str,
) -> None:
    # Given: one assessment event corrupted at its typed audit boundary.
    assessment_id = await seed_assessment(db_session)
    repository = AssessmentRepository(db_session)
    _ = await repository.review(
        AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
    )
    row = (await db_session.scalars(select(AuditEventRow))).one()
    setattr(row, field, value)
    await db_session.commit()

    # When: history parses the untrusted event and state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await repository.audit_events(assessment_id)

    # Then: malformed version, action, entity, and state share one finite code.
    assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT


async def test_second_review_rejects_malformed_prior_state(
    db_session: AsyncSession,
) -> None:
    # Given: the latest completed review has valid JSON with the wrong schema shape.
    assessment_id = await seed_assessment(db_session)
    repository = AssessmentRepository(db_session)
    _ = await repository.review(
        AssessmentReviewCommand(assessment_id, (), "first", "first", REFERENCE_TIME)
    )
    row = (await db_session.scalars(select(AuditEventRow))).one()
    row.after_json = "{}"
    await db_session.commit()

    # When: the malformed prior state would otherwise become the next before-state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await repository.review(
            AssessmentReviewCommand(assessment_id, (), "second", "second", REFERENCE_TIME)
        )

    # Then: no review or audit sibling is fabricated.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert event_count == 1


async def test_assessment_history_read_can_be_followed_by_review(
    db_session: AsyncSession,
) -> None:
    # Given: one automatic assessment and a repository-owned read boundary.
    assessment_id = await seed_assessment(db_session)
    repository = AssessmentRepository(db_session)
    assert await repository.audit_events(assessment_id) == ()

    # When: the same session writes immediately after the history read.
    review = await repository.review(
        AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
    )

    # Then: the write commits instead of colliding with an implicit read transaction.
    assert review.assessment_id == assessment_id


async def test_case_history_read_can_be_followed_by_transition(
    db_session: AsyncSession,
) -> None:
    # Given: one recommended case and a repository-owned empty history read.
    case = await seed_case(db_session)
    repository = CaseRepository(db_session)
    case_id = CaseId(case.id)
    assert await repository.audit_events(case_id) == ()

    # When: the same session transitions immediately after the history read.
    transitioned = await repository.transition(
        CaseTransition(case_id, CaseStage.CONTACTED, "actor", "reason", REFERENCE_TIME)
    )

    # Then: the implicit read transaction no longer blocks the repository write.
    assert transitioned.stage is CaseStage.CONTACTED


async def test_history_read_preserves_caller_owned_transaction(
    db_session: AsyncSession,
) -> None:
    # Given: one case and an explicit caller-owned transaction.
    case = await seed_case(db_session)
    repository = CaseRepository(db_session)

    # When: history is read and the caller mutates state inside its own transaction.
    async with db_session.begin():
        assert await repository.audit_events(CaseId(case.id)) == ()
        row = await db_session.get(CaseRow, case.id)
        assert row is not None
        row.note = "caller-owned"

    # Then: the repository read neither commits nor rolls back the caller's work.
    stored = await db_session.get(CaseRow, case.id)
    assert stored is not None
    assert stored.note == "caller-owned"
