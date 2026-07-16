from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path

import anyio
import pytest
from anyio.lowlevel import checkpoint
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grantcompass.domain.enums import SourceName
from grantcompass.domain.programs import IngestResult
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import NoticeVersionRow, ProgramRow
from grantcompass.storage.tables import Base
from tests.factories import make_notice

type Worker = Callable[[], Coroutine[None, None, None]]


@pytest.mark.anyio
async def test_concurrent_first_ingest_returns_one_winner_to_both_callers(
    tmp_path: Path,
    now: datetime,
) -> None:
    # Given: two independent sessions poised to ingest the same first source notice.
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    start = anyio.Event()
    results: list[IngestResult] = []
    worker = _worker(session_factory, start, results, now)

    # When: both independent transactions start together.
    async with anyio.create_task_group() as task_group:
        _ = task_group.start_soon(worker)
        _ = task_group.start_soon(worker)
        await checkpoint()
        start.set()

    # Then: callers succeed against one program, source version, and current pointer.
    async with session_factory() as verification:
        program_count = await verification.scalar(select(func.count(ProgramRow.id)))
        version_count = await verification.scalar(select(func.count(NoticeVersionRow.id)))
        current_count = await verification.scalar(select(func.count(CurrentNoticeVersionRow.id)))
    await engine.dispose()
    assert len(results) == 2
    assert len({item.program_id for item in results}) == 1
    assert len({item.notice_version_id for item in results}) == 1
    assert program_count == 1
    assert version_count == 1
    assert current_count == 1


def _worker(
    session_factory: async_sessionmaker[AsyncSession],
    start: anyio.Event,
    results: list[IngestResult],
    now: datetime,
) -> Worker:
    async def run() -> None:
        await start.wait()
        async with session_factory() as session:
            result = await ProgramRepository(session).upsert_notice(
                make_notice(SourceName.KSTARTUP, "K-CONCURRENT"), now
            )
            results.append(result)

    return run
