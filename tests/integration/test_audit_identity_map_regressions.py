import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from grantcompass.domain.cases import (
    AuditErrorCode,
    AuditValidationError,
    CaseId,
    CaseTransition,
)
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.repositories import AssessmentRepository, CaseRepository
from grantcompass.storage.table_cases import AuditEventRow, CaseRow
from grantcompass.storage.table_eligibility import (
    AssessmentRow,
    RuleAssessmentRow,
)
from grantcompass.storage.tables import Base
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment, seed_case

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("mutation", ["status", "error_id", "evidence_ids_json"])
async def test_assessment_review_refreshes_cached_automatic_state(
    tmp_path: Path,
    mutation: str,
) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'assessment-cache.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as seed_session:
            assessment_id = await seed_assessment(seed_session)
        async with factory() as reviewer:
            assessment = await reviewer.get(AssessmentRow, int(assessment_id))
            conditions = (
                await reviewer.scalars(
                    select(RuleAssessmentRow).where(
                        RuleAssessmentRow.assessment_id == int(assessment_id)
                    )
                )
            ).all()
            assert assessment is not None
            assert len(conditions) == 1
            await reviewer.commit()
            _ = await AssessmentRepository(reviewer).review(
                AssessmentReviewCommand(assessment_id, (), "first", "first", REFERENCE_TIME)
            )

            async with factory() as external:
                external_assessment = await external.get(AssessmentRow, int(assessment_id))
                external_rule = await external.get(RuleAssessmentRow, conditions[0].id)
                assert external_assessment is not None
                assert external_rule is not None
                if mutation == "status":
                    external_rule.status = "conditional"
                    external_assessment.final_status = "conditional"
                elif mutation == "error_id":
                    external_rule.error_id = "external-error"
                else:
                    external_rule.evidence_ids_json = json.dumps([99], separators=(",", ":"))
                await external.commit()

            with pytest.raises(AuditValidationError) as captured:
                _ = await AssessmentRepository(reviewer).review(
                    AssessmentReviewCommand(
                        assessment_id,
                        (),
                        "second",
                        "second",
                        REFERENCE_TIME + timedelta(minutes=1),
                        1,
                    )
                )
        async with factory() as verification:
            stored = await verification.get(AssessmentRow, int(assessment_id))
            event_count = await verification.scalar(select(func.count(AuditEventRow.id)))
        assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT
        assert stored is not None
        assert stored.review_revision == 1
        assert event_count == 1
    finally:
        await engine.dispose()


async def test_case_transition_refreshes_cached_identity_fields(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'case-cache.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as seed_session:
            case = await seed_case(seed_session)
        async with factory() as reviewer:
            cached = await reviewer.get(CaseRow, case.id)
            assert cached is not None
            await reviewer.commit()
            _ = await CaseRepository(reviewer).transition(
                CaseTransition(
                    CaseId(case.id),
                    CaseStage.CONTACTED,
                    "first",
                    "first",
                    REFERENCE_TIME,
                )
            )

            async with factory() as external:
                external_case = await external.get(CaseRow, case.id)
                assert external_case is not None
                external_case.note = "외부 변경"
                await external.commit()

            with pytest.raises(AuditValidationError) as captured:
                _ = await CaseRepository(reviewer).transition(
                    CaseTransition(
                        CaseId(case.id),
                        CaseStage.CONSULTED,
                        "second",
                        "second",
                        REFERENCE_TIME + timedelta(minutes=1),
                    )
                )
        async with factory() as verification:
            stored = await verification.get(CaseRow, case.id)
            event_count = await verification.scalar(select(func.count(AuditEventRow.id)))
        assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT
        assert stored is not None
        assert stored.stage == CaseStage.CONTACTED.value
        assert stored.note == "외부 변경"
        assert event_count == 1
    finally:
        await engine.dispose()


async def test_stale_assessment_revision_precedes_malformed_audit(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'assessment-stale.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as seed_session:
            assessment_id = await seed_assessment(seed_session)
            _ = await AssessmentRepository(seed_session).review(
                AssessmentReviewCommand(assessment_id, (), "initial", "initial", REFERENCE_TIME)
            )
        async with factory() as winner, factory() as stale:
            winner_row = await winner.get(AssessmentRow, int(assessment_id))
            stale_row = await stale.get(AssessmentRow, int(assessment_id))
            assert winner_row is not None
            assert stale_row is not None
            await winner.commit()
            await stale.commit()
            _ = await AssessmentRepository(winner).review(
                AssessmentReviewCommand(
                    assessment_id,
                    (),
                    "winner",
                    "winner",
                    REFERENCE_TIME + timedelta(minutes=1),
                    1,
                )
            )
            async with factory() as corruptor:
                latest = (
                    await corruptor.scalars(select(AuditEventRow).order_by(AuditEventRow.id.desc()))
                ).first()
                assert latest is not None
                latest.after_json = "{}"
                await corruptor.commit()

            with pytest.raises(AuditValidationError) as captured:
                _ = await AssessmentRepository(stale).review(
                    AssessmentReviewCommand(
                        assessment_id,
                        (),
                        "stale",
                        "stale",
                        REFERENCE_TIME + timedelta(minutes=2),
                        1,
                    )
                )
        async with factory() as verification:
            event_count = await verification.scalar(select(func.count(AuditEventRow.id)))
        assert captured.value.code is AuditErrorCode.CONCURRENT_CHANGE
        assert event_count == 2
    finally:
        await engine.dispose()


async def test_stale_case_stage_precedes_malformed_audit(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'case-stale.db'}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as seed_session:
            case = await seed_case(seed_session)
            case_id = CaseId(case.id)
            _ = await CaseRepository(seed_session).transition(
                CaseTransition(case_id, CaseStage.CONTACTED, "initial", "initial", REFERENCE_TIME)
            )
        async with factory() as winner, factory() as stale:
            winner_row = await winner.get(CaseRow, case.id)
            stale_row = await stale.get(CaseRow, case.id)
            assert winner_row is not None
            assert stale_row is not None
            await winner.commit()
            await stale.commit()
            _ = await CaseRepository(winner).transition(
                CaseTransition(
                    case_id,
                    CaseStage.CONSULTED,
                    "winner",
                    "winner",
                    REFERENCE_TIME + timedelta(minutes=1),
                )
            )
            async with factory() as corruptor:
                latest = (
                    await corruptor.scalars(select(AuditEventRow).order_by(AuditEventRow.id.desc()))
                ).first()
                assert latest is not None
                latest.after_json = "{}"
                await corruptor.commit()

            with pytest.raises(AuditValidationError) as captured:
                _ = await CaseRepository(stale).transition(
                    CaseTransition(
                        case_id,
                        CaseStage.CONSULTED,
                        "stale",
                        "stale",
                        REFERENCE_TIME + timedelta(minutes=2),
                    )
                )
        async with factory() as verification:
            event_count = await verification.scalar(select(func.count(AuditEventRow.id)))
        assert captured.value.code is AuditErrorCode.CONCURRENT_CHANGE
        assert event_count == 2
    finally:
        await engine.dispose()
