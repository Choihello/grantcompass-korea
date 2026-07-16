from dataclasses import dataclass, replace
from datetime import date, datetime

import pytest

from grantcompass.domain.enums import SourceName
from grantcompass.domain.ids import ProgramId
from grantcompass.storage.repositories import ProgramRepository
from tests.factories import NoticeValues, make_notice


@dataclass(frozen=True, slots=True)
class _PairScenario:
    prefix: str
    first_source: SourceName
    second_source: SourceName
    base: NoticeValues
    changed: NoticeValues
    now: datetime


@pytest.mark.anyio
@pytest.mark.parametrize("field_name", ["title", "organization", "application_end"])
async def test_public_program_view_is_neutral_and_arrival_order_independent(
    program_repository: ProgramRepository,
    now: datetime,
    field_name: str,
) -> None:
    # Given: two program pairs begin exact, then opposite sources publish one conflict.
    base_left = NoticeValues(title=f"가상 A {field_name}")
    base_right = NoticeValues(title=f"가상 B {field_name}")
    changed_left = _changed(base_left, field_name)
    changed_right = _changed(base_right, field_name)
    left = await _ingest_pair(
        program_repository,
        _PairScenario(
            prefix="LEFT",
            first_source=SourceName.KSTARTUP,
            second_source=SourceName.BIZINFO,
            base=base_left,
            changed=changed_left,
            now=now,
        ),
    )
    right = await _ingest_pair(
        program_repository,
        _PairScenario(
            prefix="RIGHT",
            first_source=SourceName.BIZINFO,
            second_source=SourceName.KSTARTUP,
            base=base_right,
            changed=changed_right,
            now=now,
        ),
    )

    # When: both canonical program views are read.
    left_view = await program_repository.get_program(left)
    right_view = await program_repository.get_program(right)

    # Then: the conflicted field is unresolved regardless of source arrival order.
    assert getattr(left_view, field_name) is None
    assert getattr(right_view, field_name) is None
    assert {item.field_name for item in left_view.conflicts} == {field_name}
    assert {item.field_name for item in right_view.conflicts} == {field_name}


async def _ingest_pair(
    repository: ProgramRepository,
    scenario: _PairScenario,
) -> ProgramId:
    first = await repository.upsert_notice(
        make_notice(scenario.first_source, f"{scenario.prefix}-1", scenario.base),
        scenario.now,
    )
    _ = await repository.upsert_notice(
        make_notice(scenario.second_source, f"{scenario.prefix}-2", scenario.base),
        scenario.now,
    )
    _ = await repository.upsert_notice(
        make_notice(scenario.second_source, f"{scenario.prefix}-2", scenario.changed),
        scenario.now,
    )
    return first.program_id


def _changed(base: NoticeValues, field_name: str) -> NoticeValues:
    if field_name == "title":
        return replace(base, title=f"{base.title} 변경")
    if field_name == "organization":
        return replace(base, organization="다른 가상기관")
    return replace(base, application_end=date(2026, 8, 7))
