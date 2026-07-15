from dataclasses import dataclass
from datetime import datetime
from typing import final

import pytest
from pydantic import HttpUrl
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import FreshnessStatus, SourceName
from grantcompass.domain.programs import RawNotice
from grantcompass.sources.base import SourcePage, SourceTransportError
from grantcompass.sources.collector import Collector
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_programs import NoticeVersionRow, ProgramRow, SourceRunRow


@dataclass(frozen=True, slots=True)
class _FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


@final
class _PagedAdapter:
    name = SourceName.KSTARTUP

    def __init__(self, pages: tuple[SourcePage, ...]) -> None:
        self._pages = pages

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        del page_size
        return self._pages[page - 1]


@final
class _FailingAdapter:
    name = SourceName.KSTARTUP

    def __init__(self, first_page: SourcePage) -> None:
        self._first_page = first_page

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        del page_size
        if page == 1:
            return self._first_page
        raise SourceTransportError(code="upstream_unavailable", message="source unavailable")


def _notice(raw_notice: RawNotice, source_notice_id: str) -> RawNotice:
    return raw_notice.model_copy(
        update={
            "source_notice_id": source_notice_id,
            "detail_url": HttpUrl(f"https://example.invalid/notices/{source_notice_id}"),
        }
    )


@pytest.mark.anyio
async def test_collect_stores_all_pages(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: two source pages containing three distinct notices.
    adapter = _PagedAdapter(
        (
            SourcePage(
                items=(_notice(raw_notice, "K-001"), _notice(raw_notice, "K-002")),
                page=1,
                has_next=True,
                response_hash="page-1",
            ),
            SourcePage(
                items=(_notice(raw_notice, "K-003"),),
                page=2,
                has_next=False,
                response_hash="page-2",
            ),
        )
    )

    # When: the collector consumes the complete adapter pagination sequence.
    result = await Collector(program_repository, _FixedClock(now)).collect(adapter, page_size=2)

    # Then: every notice is stored and the successful run is fresh.
    run = (await db_session.scalars(select(SourceRunRow))).one()
    assert result.stored == 3
    assert result.unchanged == 0
    assert result.failed == 0
    assert result.freshness is FreshnessStatus.FRESH
    assert run.status == "succeeded"
    assert run.item_count == 3


@pytest.mark.anyio
async def test_collect_counts_unchanged_notices(
    program_repository: ProgramRepository,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: one notice already persisted before collection.
    notice = _notice(raw_notice, "K-UNCHANGED")
    _ = await program_repository.upsert_notice(notice, now)
    adapter = _PagedAdapter(
        (SourcePage(items=(notice,), page=1, has_next=False, response_hash="same"),)
    )

    # When: the collector receives the same source content again.
    result = await Collector(program_repository, _FixedClock(now)).collect(adapter)

    # Then: the item is reported as unchanged rather than newly stored.
    assert result.stored == 0
    assert result.unchanged == 1
    assert result.failed == 0


@pytest.mark.anyio
async def test_failure_keeps_committed_data_and_marks_source_stale(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: a source that fails only after one independently storable page.
    page = SourcePage(
        items=(_notice(raw_notice, "K-PARTIAL"),),
        page=1,
        has_next=True,
        response_hash="partial",
    )

    # When: collection crosses the failing page boundary.
    result = await Collector(program_repository, _FixedClock(now)).collect(_FailingAdapter(page))

    # Then: committed data remains visible and the run exposes a stable stale failure.
    program_count = await db_session.scalar(select(func.count(ProgramRow.id)))
    run = (await db_session.scalars(select(SourceRunRow))).one()
    assert program_count == 1
    assert result.stored == 1
    assert result.freshness is FreshnessStatus.STALE
    assert result.error_code == "upstream_unavailable"
    assert result.failed == 1
    assert run.status == "failed"
    assert run.error_code == "upstream_unavailable"
    assert run.item_count == 1


@pytest.mark.anyio
async def test_failed_source_does_not_mutate_other_source_data(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: one Bizinfo notice and an independently failing K-Startup adapter.
    bizinfo = _notice(raw_notice, "B-EXISTING").model_copy(update={"source": SourceName.BIZINFO})
    _ = await program_repository.upsert_notice(bizinfo, now)
    failing_page = SourcePage(items=(), page=1, has_next=True, response_hash="empty")

    # When: K-Startup collection fails in its isolated source run.
    result = await Collector(program_repository, _FixedClock(now)).collect(
        _FailingAdapter(failing_page)
    )

    # Then: the other source notice remains stored and the failure is source-specific.
    bizinfo_count = await db_session.scalar(
        select(func.count(NoticeVersionRow.id)).where(
            NoticeVersionRow.source == SourceName.BIZINFO.value
        )
    )
    assert result.source is SourceName.KSTARTUP
    assert result.freshness is FreshnessStatus.STALE
    assert bizinfo_count == 1
