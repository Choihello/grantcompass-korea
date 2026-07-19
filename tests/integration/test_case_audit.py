import json
from datetime import timedelta
from typing import Final

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import CaseId, CaseTransition
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.json_types import thaw_json_object
from grantcompass.storage.repositories import CaseRepository
from grantcompass.storage.table_cases import AuditEventRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_case

pytestmark = pytest.mark.anyio

ALLOWED_TRANSITIONS: Final = (
    (CaseStage.RECOMMENDED, CaseStage.CONTACTED),
    (CaseStage.RECOMMENDED, CaseStage.CLOSED),
    (CaseStage.CONTACTED, CaseStage.CONSULTED),
    (CaseStage.CONTACTED, CaseStage.CLOSED),
    (CaseStage.CONSULTED, CaseStage.APPLYING),
    (CaseStage.CONSULTED, CaseStage.CLOSED),
    (CaseStage.APPLYING, CaseStage.SUBMITTED),
    (CaseStage.APPLYING, CaseStage.CLOSED),
    (CaseStage.SUBMITTED, CaseStage.SELECTED),
    (CaseStage.SUBMITTED, CaseStage.NOT_SELECTED),
    (CaseStage.SUBMITTED, CaseStage.CLOSED),
    (CaseStage.SELECTED, CaseStage.CLOSED),
    (CaseStage.NOT_SELECTED, CaseStage.CLOSED),
)


async def test_case_transition_writes_one_immutable_audit_event(
    db_session: AsyncSession,
) -> None:
    # Given: one recommended institutional support case.
    case = await seed_case(db_session)
    repository = CaseRepository(db_session)

    # When: the assigned worker records a valid contacted transition.
    transitioned = await repository.transition(
        CaseTransition(
            case_id=CaseId(case.id),
            stage=CaseStage.CONTACTED,
            actor="담당자",
            reason="전화 안내",
            occurred_at=REFERENCE_TIME,
        )
    )

    # Then: the case and canonical before/after audit state are committed together.
    events = await repository.audit_events(CaseId(case.id))
    assert transitioned.stage is CaseStage.CONTACTED
    assert len(events) == 1
    assert events[0].before_json is not None
    assert events[0].after_json is not None
    assert events[0].before_json["stage"] == CaseStage.RECOMMENDED.value
    assert events[0].after_json["stage"] == CaseStage.CONTACTED.value


@pytest.mark.parametrize(("source", "target"), ALLOWED_TRANSITIONS)
async def test_every_allowed_case_transition_commits_exactly_once(
    db_session: AsyncSession,
    source: CaseStage,
    target: CaseStage,
) -> None:
    # Given: one support case at each valid source stage.
    case = await seed_case(db_session)
    case.stage = source.value
    await db_session.commit()

    # When: the case advances along one declared edge.
    result = await CaseRepository(db_session).transition(
        CaseTransition(CaseId(case.id), target, "담당자", "상담 진행", REFERENCE_TIME)
    )

    # Then: exactly one target state and one audit event are visible.
    events = await CaseRepository(db_session).audit_events(CaseId(case.id))
    assert result.stage is target
    assert tuple(event.action for event in events) == ("transition",)


async def test_case_audit_json_is_canonical_and_complete(db_session: AsyncSession) -> None:
    # Given: one recommended case with assignee and note metadata.
    case = await seed_case(db_session)

    # When: a valid transition is committed.
    _ = await CaseRepository(db_session).transition(
        CaseTransition(CaseId(case.id), CaseStage.CONTACTED, "담당자", "전화 안내", REFERENCE_TIME)
    )

    # Then: raw storage is compact canonical JSON and the typed state retains every field.
    row = (await db_session.scalars(select(AuditEventRow))).one()
    event = (await CaseRepository(db_session).audit_events(CaseId(case.id)))[0]
    assert event.before_json is not None
    assert event.after_json is not None
    assert row.before_json == json.dumps(
        thaw_json_object(event.before_json),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert set(event.before_json) == {
        "schema_version",
        "entity_id",
        "stage",
        "assignee_name",
        "note",
        "updated_at",
    }
    assert event.actor_name == "담당자"
    assert event.reason == "전화 안내"


async def test_case_audit_events_are_oldest_first(db_session: AsyncSession) -> None:
    # Given: one case advanced through two valid stages at injected instants.
    case = await seed_case(db_session)
    repository = CaseRepository(db_session)
    _ = await repository.transition(
        CaseTransition(CaseId(case.id), CaseStage.CONTACTED, "a", "first", REFERENCE_TIME)
    )
    later = REFERENCE_TIME + timedelta(minutes=1)

    # When: the second transition is committed and history is read.
    _ = await repository.transition(
        CaseTransition(CaseId(case.id), CaseStage.CONSULTED, "b", "second", later)
    )
    events = await repository.audit_events(CaseId(case.id))

    # Then: immutable event IDs and reasons preserve append order.
    assert tuple(event.reason for event in events) == ("first", "second")
    assert tuple(int(event.id) for event in events) == tuple(
        sorted(int(event.id) for event in events)
    )
