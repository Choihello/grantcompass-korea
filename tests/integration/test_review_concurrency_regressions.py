from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from grantcompass.domain.cases import AuditErrorCode, AuditValidationError
from grantcompass.domain.enums import ReviewStatus
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import AssessmentRow
from grantcompass.storage.tables import Base
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment

pytestmark = pytest.mark.anyio


async def test_two_stale_second_reviewers_cannot_create_sibling_history(
    tmp_path: Path,
) -> None:
    # Given: one reviewed assessment cached at the same revision in two real sessions.
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'review-race.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as seed_session:
            assessment_id = await seed_assessment(seed_session)
            _ = await AssessmentRepository(seed_session).review(
                AssessmentReviewCommand(assessment_id, (), "initial", "initial", REFERENCE_TIME)
            )
        async with factory() as left, factory() as right:
            left_cached = await left.get(AssessmentRow, int(assessment_id))
            right_cached = await right.get(AssessmentRow, int(assessment_id))
            assert left_cached is not None
            assert right_cached is not None
            await left.commit()
            await right.commit()

            # When: one cached reviewer wins and the other submits its stale revision.
            _ = await AssessmentRepository(left).review(
                AssessmentReviewCommand(
                    assessment_id,
                    (),
                    "winner",
                    "winner",
                    REFERENCE_TIME + timedelta(minutes=1),
                    1,
                )
            )
            with pytest.raises(AuditValidationError) as captured:
                _ = await AssessmentRepository(right).review(
                    AssessmentReviewCommand(
                        assessment_id,
                        (),
                        "stale",
                        "stale",
                        REFERENCE_TIME + timedelta(minutes=2),
                        1,
                    )
                )

        # Then: the stale write is finite and only one linear second review exists.
        async with factory() as verification:
            row = await verification.get(AssessmentRow, int(assessment_id))
            events = tuple(
                (await verification.scalars(select(AuditEventRow).order_by(AuditEventRow.id))).all()
            )
        assert captured.value.code is AuditErrorCode.CONCURRENT_CHANGE
        assert row is not None
        assert row.review_status == ReviewStatus.REVIEWED.value
        assert row.review_revision == 2
        assert tuple(event.actor_name for event in events) == ("initial", "winner")
    finally:
        await engine.dispose()


async def test_review_audit_snapshots_form_revision_chain(tmp_path: Path) -> None:
    # Given: one automatic assessment in a real isolated database.
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'revision-chain.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session:
            assessment_id = await seed_assessment(session)
            repository = AssessmentRepository(session)

            # When: two attributed reviews append sequentially.
            _ = await repository.review(
                AssessmentReviewCommand(assessment_id, (), "first", "first", REFERENCE_TIME)
            )
            _ = await repository.review(
                AssessmentReviewCommand(
                    assessment_id,
                    (),
                    "second",
                    "second",
                    REFERENCE_TIME + timedelta(minutes=1),
                    1,
                )
            )
            events = await repository.audit_events(assessment_id)

        # Then: every before/after state carries the exact linear revision.
        assert events[0].before_json is not None
        assert events[0].after_json is not None
        assert events[1].before_json is not None
        assert events[1].after_json is not None
        assert events[0].before_json["review_revision"] == 0
        assert events[0].after_json["review_revision"] == 1
        assert events[1].before_json == events[0].after_json
        assert events[1].after_json["review_revision"] == 2
    finally:
        await engine.dispose()
