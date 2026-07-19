from datetime import datetime, timedelta, timezone
from typing import Final

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import (
    AuditErrorCode,
    AuditValidationError,
    CaseId,
    CaseTransition,
)
from grantcompass.domain.enums import CaseStage
from grantcompass.storage.repositories import CaseRepository
from grantcompass.storage.table_cases import AuditEventRow, CaseRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_case
from tests.integration.test_case_audit import ALLOWED_TRANSITIONS

pytestmark = pytest.mark.anyio

REJECTED_TRANSITIONS: Final = tuple(
    (source, target)
    for source in CaseStage
    for target in CaseStage
    if (source, target) not in ALLOWED_TRANSITIONS
)


@pytest.mark.parametrize(("source", "target"), REJECTED_TRANSITIONS)
async def test_every_other_case_transition_is_rejected(
    db_session: AsyncSession,
    source: CaseStage,
    target: CaseStage,
) -> None:
    # Given: a case at a source stage and a target outside the forward graph.
    case = await seed_case(db_session)
    case.stage = source.value
    await db_session.commit()

    # When: the invalid same, backward, skipped, or terminal edge is requested.
    with pytest.raises(AuditValidationError) as captured:
        _ = await CaseRepository(db_session).transition(
            CaseTransition(CaseId(case.id), target, "담당자", "invalid", REFERENCE_TIME)
        )

    # Then: the finite transition code is returned and no audit event exists.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.INVALID_TRANSITION
    assert event_count == 0


@pytest.mark.parametrize(
    ("actor", "reason", "occurred_at", "expected"),
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
async def test_case_transition_validates_attribution_and_utc_time(
    db_session: AsyncSession,
    actor: str,
    reason: str,
    occurred_at: datetime,
    expected: AuditErrorCode,
) -> None:
    # Given: one command with a blank, oversized, naive, or non-UTC boundary value.
    case = await seed_case(db_session)

    # When: the invalid command is submitted.
    with pytest.raises(AuditValidationError) as captured:
        _ = await CaseRepository(db_session).transition(
            CaseTransition(CaseId(case.id), CaseStage.CONTACTED, actor, reason, occurred_at)
        )

    # Then: the exact finite validation code is visible without an audit row.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is expected
    assert event_count == 0


async def test_unknown_case_transition_and_audit_are_finite(db_session: AsyncSession) -> None:
    # Given: a repository with no case matching the requested ID.
    repository = CaseRepository(db_session)

    # When: transition and audit retrieval address the unknown case.
    with pytest.raises(AuditValidationError) as transition_error:
        _ = await repository.transition(
            CaseTransition(CaseId(999), CaseStage.CONTACTED, "actor", "reason", REFERENCE_TIME)
        )
    with pytest.raises(AuditValidationError) as audit_error:
        _ = await repository.audit_events(CaseId(999))

    # Then: both operations expose the same finite not-found code.
    assert transition_error.value.code is AuditErrorCode.CASE_NOT_FOUND
    assert audit_error.value.code is AuditErrorCode.CASE_NOT_FOUND


async def test_malformed_stored_case_stage_is_finite(db_session: AsyncSession) -> None:
    # Given: one legacy case row with an invalid serialized stage.
    case = await seed_case(db_session)
    case.stage = "broken"
    await db_session.commit()

    # When: the row crosses the typed repository boundary.
    with pytest.raises(AuditValidationError) as captured:
        _ = await CaseRepository(db_session).transition(
            CaseTransition(CaseId(case.id), CaseStage.CONTACTED, "actor", "reason", REFERENCE_TIME)
        )

    # Then: malformed storage is surfaced without an audit event.
    assert captured.value.code is AuditErrorCode.MALFORMED_CASE_STAGE


async def test_audit_insert_failure_rolls_back_case_update(db_session: AsyncSession) -> None:
    # Given: a real SQLite trigger rejects the audit insert after the case update.
    case = await seed_case(db_session)
    case_id = CaseId(case.id)
    _ = await db_session.execute(
        text(
            """
            CREATE TRIGGER fail_case_audit BEFORE INSERT ON audit_events
            BEGIN SELECT RAISE(ABORT, 'forced_audit_failure'); END
            """
        )
    )
    await db_session.commit()

    # When: the otherwise valid transition reaches the rejected audit insert.
    with pytest.raises(IntegrityError):
        _ = await CaseRepository(db_session).transition(
            CaseTransition(case_id, CaseStage.CONTACTED, "actor", "reason", REFERENCE_TIME)
        )

    # Then: neither the stage update nor an audit event survives the transaction.
    stored = await db_session.get(CaseRow, int(case_id))
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert stored is not None
    assert stored.stage == CaseStage.RECOMMENDED.value
    assert event_count == 0


async def test_zero_row_optimistic_update_returns_concurrent_change(
    db_session: AsyncSession,
) -> None:
    # Given: SQLite simulates another writer winning by ignoring the optimistic update.
    case = await seed_case(db_session)
    _ = await db_session.execute(
        text(
            """
            CREATE TRIGGER ignore_case_update BEFORE UPDATE ON cases
            BEGIN SELECT RAISE(IGNORE); END
            """
        )
    )
    await db_session.commit()

    # When: the transition observes no row matching its expected write state.
    with pytest.raises(AuditValidationError) as captured:
        _ = await CaseRepository(db_session).transition(
            CaseTransition(CaseId(case.id), CaseStage.CONTACTED, "actor", "reason", REFERENCE_TIME)
        )

    # Then: the finite concurrent-change code is emitted without false audit state.
    event_count = await db_session.scalar(select(func.count(AuditEventRow.id)))
    assert captured.value.code is AuditErrorCode.CONCURRENT_CHANGE
    assert event_count == 0
