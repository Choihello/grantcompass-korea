from dataclasses import dataclass
from datetime import datetime
from typing import final, override

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.domain.source_runs import SourceRunFailure, SourceRunId, SourceRunSuccess
from grantcompass.sources.base import SourcePage
from grantcompass.sources.collector import Collector
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_programs import SourceRunRow


@dataclass(frozen=True, slots=True)
class _FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


@final
class _EmptyAdapter:
    name = SourceName.KSTARTUP

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        del page_size
        return SourcePage(items=(), page=page, has_next=False, response_hash="empty")


@final
class _CompletionError(RuntimeError):
    pass


@final
class _CompletionFailureRepository(ProgramRepository):
    @override
    async def complete_source_run(
        self,
        run_id: SourceRunId,
        outcome: SourceRunSuccess,
    ) -> None:
        del run_id, outcome
        raise _CompletionError


@final
class _DoubleCompletionFaultRepository(ProgramRepository):
    @override
    async def complete_source_run(
        self,
        run_id: SourceRunId,
        outcome: SourceRunSuccess,
    ) -> None:
        del run_id, outcome
        raise _CompletionError

    @override
    async def fail_source_run(
        self,
        run_id: SourceRunId,
        outcome: SourceRunFailure,
    ) -> None:
        del run_id, outcome
        raise RuntimeError


@pytest.mark.anyio
async def test_completion_error_closes_run_and_propagates(
    db_session: AsyncSession,
    now: datetime,
) -> None:
    # Given: successful page collection whose completion transition will fail.
    repository = _CompletionFailureRepository(db_session)

    # When: the collector attempts to complete the source run.
    with pytest.raises(_CompletionError):
        _ = await Collector(repository, _FixedClock(now)).collect(_EmptyAdapter())

    # Then: the original error propagates after best-effort failed transition.
    run = (await db_session.scalars(select(SourceRunRow))).one()
    assert run.status == "failed"
    assert run.error_code == "internal_collection_error"


@pytest.mark.anyio
async def test_completion_failure_recording_does_not_mask_original(
    db_session: AsyncSession,
    now: datetime,
) -> None:
    # Given: both completion and subsequent failure recording will fail.
    repository = _DoubleCompletionFaultRepository(db_session)

    # When: the collector attempts both terminal transitions.
    with pytest.raises(_CompletionError):
        _ = await Collector(repository, _FixedClock(now)).collect(_EmptyAdapter())

    # Then: the original completion exception remains the propagated outcome.
