from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import AuditErrorCode, AuditValidationError
from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus, ReviewStatus
from grantcompass.domain.ids import AssessmentId
from grantcompass.domain.reviews import (
    AssessmentReviewCommand,
    ConditionOverride,
    RuleAssessmentId,
)
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("actor", "reason", "reviewed_at", "expected"),
    [
        (" ", "reason", REFERENCE_TIME, AuditErrorCode.ACTOR_REQUIRED),
        ("a" * 301, "reason", REFERENCE_TIME, AuditErrorCode.ACTOR_TOO_LONG),
        ("actor", " ", REFERENCE_TIME, AuditErrorCode.REASON_REQUIRED),
        ("actor", "r" * 2_001, REFERENCE_TIME, AuditErrorCode.REASON_TOO_LONG),
        ("actor", "reason", REFERENCE_TIME.replace(tzinfo=None), AuditErrorCode.NAIVE_TIME),
        (
            "actor",
            "reason",
            REFERENCE_TIME.astimezone(timezone(timedelta(hours=9))),
            AuditErrorCode.NON_UTC_TIME,
        ),
    ],
)
async def test_assessment_review_validates_attribution_and_utc_time(
    db_session: AsyncSession,
    actor: str,
    reason: str,
    reviewed_at: datetime,
    expected: AuditErrorCode,
) -> None:
    # Given: an automatic assessment and one invalid attribution or time value.
    assessment_id = await seed_assessment(db_session)

    # When: the invalid review command is submitted.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(assessment_id, (), actor, reason, reviewed_at)
        )

    # Then: one finite validation code is emitted without review progress or audit.
    row = await db_session.get(AssessmentRow, int(assessment_id))
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is expected
    assert row is not None
    assert row.review_status == ReviewStatus.AUTOMATIC.value
    assert event_count == 0


async def test_unknown_assessment_review_and_audit_are_finite(db_session: AsyncSession) -> None:
    # Given: a repository with no matching assessment.
    repository = AssessmentRepository(db_session)
    assessment_id = AssessmentId(999)

    # When: review and history retrieval address the missing assessment.
    with pytest.raises(AuditValidationError) as review_error:
        _ = await repository.review(
            AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
        )
    with pytest.raises(AuditValidationError) as audit_error:
        _ = await repository.audit_events(assessment_id)

    # Then: both operations emit the same finite not-found code.
    assert review_error.value.code is AuditErrorCode.ASSESSMENT_NOT_FOUND
    assert audit_error.value.code is AuditErrorCode.ASSESSMENT_NOT_FOUND


@pytest.mark.parametrize("duplicate_field", ["rule_assessment_id", "rule_id"])
async def test_duplicate_override_identity_is_rejected(
    db_session: AsyncSession,
    duplicate_field: str,
) -> None:
    # Given: two override entries duplicate one persisted identity dimension.
    assessment_id = await seed_assessment(db_session)
    item = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment_id))
        )
    ).one()
    first = ConditionOverride(
        RuleAssessmentId(item.id),
        EligibilityRuleId(item.rule_id),
        ConditionStatus.UNSATISFIED,
    )
    second = (
        ConditionOverride(
            RuleAssessmentId(item.id),
            EligibilityRuleId(item.rule_id + 1),
            ConditionStatus.UNKNOWN,
        )
        if duplicate_field == "rule_assessment_id"
        else ConditionOverride(
            RuleAssessmentId(item.id + 1),
            EligibilityRuleId(item.rule_id),
            ConditionStatus.UNKNOWN,
        )
    )
    await db_session.commit()

    # When: the ambiguous override set is reviewed.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(
                assessment_id, (first, second), "actor", "reason", REFERENCE_TIME
            )
        )

    # Then: duplicate identity is finite and no audit event is appended.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.DUPLICATE_OVERRIDE
    assert event_count == 0


@pytest.mark.parametrize(
    ("rule_assessment_id", "rule_id", "expected"),
    [
        (0, 0, AuditErrorCode.INVALID_OVERRIDE_IDENTITY),
        (999, 999, AuditErrorCode.UNKNOWN_RULE_ASSESSMENT),
    ],
)
async def test_empty_or_unknown_override_identity_is_rejected(
    db_session: AsyncSession,
    rule_assessment_id: int,
    rule_id: int,
    expected: AuditErrorCode,
) -> None:
    # Given: one override carrying an empty or unknown persisted identity.
    assessment_id = await seed_assessment(db_session)
    override = ConditionOverride(
        RuleAssessmentId(rule_assessment_id),
        EligibilityRuleId(rule_id),
        ConditionStatus.UNKNOWN,
    )

    # When: the invalid override is reviewed.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(assessment_id, (override,), "actor", "reason", REFERENCE_TIME)
        )

    # Then: the exact finite identity code is emitted without an audit event.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is expected
    assert event_count == 0


async def test_foreign_rule_assessment_identity_is_rejected(db_session: AsyncSession) -> None:
    # Given: a rule-assessment row belonging to a different automatic assessment.
    assessment_id = await seed_assessment(db_session)
    base = await db_session.get(AssessmentRow, int(assessment_id))
    assert base is not None
    foreign_assessment = AssessmentRow(
        program_id=base.program_id,
        profile_id=base.profile_id,
        final_status=base.final_status,
        review_status=base.review_status,
        rule_version=base.rule_version,
        assessed_at=base.assessed_at,
    )
    db_session.add(foreign_assessment)
    await db_session.flush()
    base_item = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == int(assessment_id))
        )
    ).one()
    foreign_item = RuleAssessmentRow(
        assessment_id=foreign_assessment.id,
        rule_id=base_item.rule_id,
        status=base_item.status,
        explanation=base_item.explanation,
        evidence_ids_json=base_item.evidence_ids_json,
    )
    db_session.add(foreign_item)
    await db_session.commit()
    override = ConditionOverride(
        RuleAssessmentId(foreign_item.id),
        EligibilityRuleId(foreign_item.rule_id),
        ConditionStatus.UNKNOWN,
    )

    # When: the foreign row is submitted against the first assessment.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(assessment_id, (override,), "actor", "reason", REFERENCE_TIME)
        )

    # Then: the foreign identity is rejected without changing automatic rows.
    assert captured.value.code is AuditErrorCode.FOREIGN_RULE_ASSESSMENT


async def test_review_audit_failure_rolls_back_review_progress(db_session: AsyncSession) -> None:
    # Given: a real SQLite trigger rejects the audit append after progress update.
    assessment_id = await seed_assessment(db_session)
    _ = await db_session.execute(
        text(
            """
            CREATE TRIGGER fail_review_audit BEFORE INSERT ON audit_events
            BEGIN SELECT RAISE(ABORT, 'forced_review_audit_failure'); END
            """
        )
    )
    await db_session.commit()

    # When: an otherwise valid empty-override review reaches the failed append.
    with pytest.raises(IntegrityError):
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
        )

    # Then: review progress and audit history both remain unchanged.
    row = await db_session.get(AssessmentRow, int(assessment_id))
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert row is not None
    assert row.review_status == ReviewStatus.AUTOMATIC.value
    assert event_count == 0


async def test_zero_row_review_update_returns_concurrent_change(
    db_session: AsyncSession,
) -> None:
    # Given: SQLite simulates another writer winning by ignoring the progress update.
    assessment_id = await seed_assessment(db_session)
    _ = await db_session.execute(
        text(
            """
            CREATE TRIGGER ignore_review_update BEFORE UPDATE ON assessments
            BEGIN SELECT RAISE(IGNORE); END
            """
        )
    )
    await db_session.commit()

    # When: review progress observes no row matching its expected write state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await AssessmentRepository(db_session).review(
            AssessmentReviewCommand(assessment_id, (), "actor", "reason", REFERENCE_TIME)
        )

    # Then: a finite concurrency code is emitted without false audit state.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.CONCURRENT_CHANGE
    assert event_count == 0
