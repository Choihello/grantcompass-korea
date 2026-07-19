import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus
from grantcompass.domain.json_types import thaw_json_object
from grantcompass.domain.reviews import (
    AssessmentReviewCommand,
    ConditionOverride,
    RuleAssessmentId,
)
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import RuleAssessmentRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment

pytestmark = pytest.mark.anyio


async def test_second_review_appends_prior_effective_state_oldest_first(
    db_session: AsyncSession,
) -> None:
    # Given: one assessment reviewed first with an explicit unsatisfied override.
    assessment_id = await seed_assessment(db_session)
    item = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment_id))
        )
    ).one()
    repository = AssessmentRepository(db_session)
    first_override = ConditionOverride(
        RuleAssessmentId(item.id),
        EligibilityRuleId(item.rule_id),
        ConditionStatus.UNSATISFIED,
    )
    await db_session.commit()
    _ = await repository.review(
        AssessmentReviewCommand(
            assessment_id, (first_override,), "first-actor", "first-reason", REFERENCE_TIME
        )
    )
    second_override = ConditionOverride(
        RuleAssessmentId(item.id),
        EligibilityRuleId(item.rule_id),
        ConditionStatus.CONDITIONAL,
    )

    # When: a second attributed review changes only the effective override view.
    _ = await repository.review(
        AssessmentReviewCommand(
            assessment_id,
            (second_override,),
            "second-actor",
            "second-reason",
            REFERENCE_TIME + timedelta(minutes=1),
        )
    )
    events = await repository.audit_events(assessment_id)

    # Then: the second before-state equals the first after-state and history remains append-only.
    assert tuple(event.actor_name for event in events) == ("first-actor", "second-actor")
    assert events[0].after_json == events[1].before_json
    assert events[1].after_json is not None
    assert (
        events[1].after_json["reviewed_at"] == (REFERENCE_TIME + timedelta(minutes=1)).isoformat()
    )


async def test_review_audit_json_is_compact_canonical_and_actor_independent(
    db_session: AsyncSession,
) -> None:
    # Given: one automatic assessment and an empty-override verification.
    assessment_id = await seed_assessment(db_session)

    # When: the review and its raw audit row are persisted.
    _ = await AssessmentRepository(db_session).review(
        AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
    )
    row = (await db_session.scalars(select(AuditEventRow))).one()
    event = (await AssessmentRepository(db_session).audit_events(assessment_id))[0]

    # Then: canonical state excludes attribution while the event retains actor and reason.
    assert event.after_json is not None
    assert row.after_json == json.dumps(
        thaw_json_object(event.after_json),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert "actor" not in event.after_json
    assert "reason" not in event.after_json
    assert event.actor_name == "actor"
    assert event.reason == "reason"
