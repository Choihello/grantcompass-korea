import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.assessment_store import persist_assessments
from grantcompass.cli.profiles import ProfileRepository
from grantcompass.cli.program_queries import ProgramQueryRepository
from grantcompass.domain.json_types import FrozenJsonObject
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.rules.deterministic import DeterministicAssessmentEngine
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_eligibility import RuleAssessmentRow
from tests.integration.task12_fixtures import (
    REFERENCE_TIME,
    seed_profile,
    seed_program,
    seed_rule,
)

pytestmark = pytest.mark.anyio


async def test_personal_persistence_retains_condition_error_id(
    db_session: AsyncSession,
) -> None:
    # Given: Task 11 assesses a persisted profile with one missing required fact.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile_row = await seed_profile(db_session)
    profile_row.regions_json = "[]"
    await db_session.commit()
    profile = await ProfileRepository(db_session).resolve(str(profile_row.id))
    record = (await ProgramQueryRepository(db_session).list_program_rules())[0]
    assessment = DeterministicAssessmentEngine().assess(profile, record.rules, REFERENCE_TIME)

    # When: the personal caller uses the assessment persistence boundary.
    persisted = await persist_assessments(db_session, (assessment,))
    row = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(
                RuleAssessmentRow.assessment_id == int(persisted[0].id or 0)
            )
        )
    ).one()

    # Then: the stable machine error identity reaches durable storage unchanged.
    assert row.error_id == assessment.items[0].error_id


async def test_personal_persistence_and_review_share_error_context(
    db_session: AsyncSession,
) -> None:
    # Given: the personal persistence caller stores an assessment with a missing fact error.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile_row = await seed_profile(db_session)
    profile_row.regions_json = "[]"
    await db_session.commit()
    profile = await ProfileRepository(db_session).resolve(str(profile_row.id))
    record = (await ProgramQueryRepository(db_session).list_program_rules())[0]
    assessment = DeterministicAssessmentEngine().assess(profile, record.rules, REFERENCE_TIME)

    # When: the shared durable result is consumed by the institutional review repository.
    persisted = await persist_assessments(db_session, (assessment,))
    persisted_id = persisted[0].id
    assert persisted_id is not None
    review = await AssessmentRepository(db_session).review(
        AssessmentReviewCommand(persisted_id, (), "actor", "reason", REFERENCE_TIME)
    )
    event = (await AssessmentRepository(db_session).audit_events(persisted_id))[0]

    # Then: the shared row and audit state retain the same machine error identity.
    assert review.conditions[0].error_id == assessment.items[0].error_id
    assert event.after_json is not None
    conditions = event.after_json["automatic_conditions"]
    assert isinstance(conditions, tuple)
    condition = conditions[0]
    assert isinstance(condition, FrozenJsonObject)
    assert condition["error_id"] == assessment.items[0].error_id
