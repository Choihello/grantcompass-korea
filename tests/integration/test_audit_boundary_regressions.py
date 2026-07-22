import json

import pytest
from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import (
    AuditErrorCode,
    AuditValidationError,
    CaseId,
    CaseTransition,
)
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.json_types import JsonObject, JsonValue
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.storage.repositories import AssessmentRepository, CaseRepository
from grantcompass.storage.table_cases import AuditEventRow, CaseRow
from grantcompass.storage.table_eligibility import AssessmentRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_assessment, seed_case

pytestmark = pytest.mark.anyio

_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


def _set_corrupted_state_value(state: JsonObject, field: str, value: JsonValue) -> None:
    match field:
        case "condition_status":
            nested_field = "status"
        case "evidence_ids" | "error_id":
            nested_field = field
        case _:
            state[field] = value
            return
    conditions = state["automatic_conditions"]
    assert isinstance(conditions, list)
    condition = conditions[0]
    assert isinstance(condition, dict)
    condition[nested_field] = value


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
            AssessmentReviewCommand(assessment_id, (), "second", "second", REFERENCE_TIME, 1)
        )

    # Then: no review or audit sibling is fabricated.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert event_count == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("assessment_id", 999),
        ("review_revision", 999),
        ("automatic_final_status", "ineligible"),
        ("condition_status", "unsatisfied"),
        ("evidence_ids", [999]),
        ("error_id", "corrupt_error"),
    ],
)
async def test_second_review_rejects_schema_valid_prior_context_corruption(
    db_session: AsyncSession,
    field: str,
    value: JsonValue,
) -> None:
    # Given: one valid review whose after-state is corrupted without breaking its schema.
    assessment_id = await seed_assessment(db_session)
    repository = AssessmentRepository(db_session)
    _ = await repository.review(
        AssessmentReviewCommand(assessment_id, (), "first", "first", REFERENCE_TIME)
    )
    row = (await db_session.scalars(select(AuditEventRow))).one()
    state: JsonObject = _JSON_OBJECT.validate_json(row.after_json or "{}", strict=True)
    _set_corrupted_state_value(state, field, value)
    row.after_json = json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    await db_session.commit()

    # When: a second review attempts to reuse the corrupted state as its before-state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await repository.review(
            AssessmentReviewCommand(assessment_id, (), "second", "second", REFERENCE_TIME, 1)
        )

    # Then: the semantic corruption is finite and the review transaction fully rolls back.
    assessment = await db_session.get(AssessmentRow, int(assessment_id))
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert assessment is not None
    assert assessment.review_status == "reviewed"
    assert assessment.review_revision == 1
    assert event_count == 1


async def test_supported_wrong_assessment_entity_type_is_discovered_and_rejected(
    db_session: AsyncSession,
) -> None:
    # Given: an assessment review whose supported entity type is corrupted to case.
    assessment_id = await seed_assessment(db_session)
    repository = AssessmentRepository(db_session)
    _ = await repository.review(
        AssessmentReviewCommand(assessment_id, (), "first", "first", REFERENCE_TIME)
    )
    row = (await db_session.scalars(select(AuditEventRow))).one()
    row.entity_type = "case"
    await db_session.commit()

    # When: history and a follow-up review consume the corrupted row.
    with pytest.raises(AuditValidationError) as history_error:
        _ = await repository.audit_events(assessment_id)
    with pytest.raises(AuditValidationError) as review_error:
        _ = await repository.review(
            AssessmentReviewCommand(assessment_id, (), "second", "second", REFERENCE_TIME, 1)
        )

    # Then: the wrong supported pair is visible as malformed and no sibling is fabricated.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert history_error.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert review_error.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert event_count == 1


async def test_intended_action_query_ignores_other_entity_action_with_same_id(
    db_session: AsyncSession,
) -> None:
    # Given: an unrelated case action shares the assessment numeric identifier.
    assessment_id = await seed_assessment(db_session)
    case_state = {
        "schema_version": 1,
        "entity_id": int(assessment_id),
        "stage": CaseStage.RECOMMENDED.value,
        "assignee_name": None,
        "note": None,
        "updated_at": REFERENCE_TIME.isoformat(),
    }
    db_session.add(
        AuditEventRow(
            entity_type="case",
            entity_id=str(int(assessment_id)),
            action="transition",
            actor_name="case",
            reason="case",
            before_json=json.dumps(case_state, separators=(",", ":"), sort_keys=True),
            after_json=json.dumps(case_state, separators=(",", ":"), sort_keys=True),
            created_at=REFERENCE_TIME,
        )
    )
    await db_session.commit()
    repository = AssessmentRepository(db_session)

    # When: the assessment review and history use their intended action discriminator.
    _ = await repository.review(
        AssessmentReviewCommand(assessment_id, (), "assessment", "assessment", REFERENCE_TIME)
    )
    events = await repository.audit_events(assessment_id)

    # Then: only the review action is treated as assessment history.
    assert tuple(event.action for event in events) == ("review",)


async def test_supported_wrong_case_entity_type_is_discovered_and_rejected(
    db_session: AsyncSession,
) -> None:
    # Given: a case transition whose supported entity type is corrupted to assessment.
    case = await seed_case(db_session)
    case_id = CaseId(case.id)
    repository = CaseRepository(db_session)
    _ = await repository.transition(
        CaseTransition(case_id, CaseStage.CONTACTED, "first", "first", REFERENCE_TIME)
    )
    row = (await db_session.scalars(select(AuditEventRow))).one()
    row.entity_type = "assessment"
    await db_session.commit()

    # When: case history is read and a follow-up transition is requested.
    with pytest.raises(AuditValidationError) as history_error:
        _ = await repository.audit_events(case_id)
    with pytest.raises(AuditValidationError) as transition_error:
        _ = await repository.transition(
            CaseTransition(case_id, CaseStage.CONSULTED, "second", "second", REFERENCE_TIME)
        )

    # Then: the corruption is surfaced and no transition sibling is fabricated.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert history_error.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert transition_error.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert event_count == 1


async def test_case_transition_rejects_schema_valid_after_state_mismatch(
    db_session: AsyncSession,
) -> None:
    # Given: a case after-state with a valid but stale stage.
    case = await seed_case(db_session)
    case_id = CaseId(case.id)
    repository = CaseRepository(db_session)
    _ = await repository.transition(
        CaseTransition(case_id, CaseStage.CONTACTED, "first", "first", REFERENCE_TIME)
    )
    row = (await db_session.scalars(select(AuditEventRow))).one()
    state: JsonObject = _JSON_OBJECT.validate_json(row.after_json or "{}", strict=True)
    state["stage"] = "recommended"
    row.after_json = json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    await db_session.commit()

    # When: the next valid transition would reuse the current case row as its before-state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await repository.transition(
            CaseTransition(CaseId(case.id), CaseStage.CONSULTED, "second", "second", REFERENCE_TIME)
        )

    # Then: the mismatch is finite and both current state and history remain unchanged.
    stored = await db_session.get(CaseRow, int(case_id))
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.MALFORMED_AUDIT
    assert stored is not None
    assert stored.stage == CaseStage.CONTACTED.value
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
