from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx2
import pytest
from pydantic import HttpUrl
from sqlalchemy import func, select

from grantcompass.cli.database import initialize_database
from grantcompass.cli.profiles import ProfileRepository
from grantcompass.cli.schemas import ProfileCreateInput
from grantcompass.cli.search import search_programs
from grantcompass.cli.sync import SourceSelection, synchronize_sources
from grantcompass.domain.enums import ConditionStatus, ReviewStatus, SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import AttachmentRef, ProgramId, RawNotice
from grantcompass.matching.reverse import ReverseMatchingService
from grantcompass.sources.base import SourcePage
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.manual_notices import ManualNoticeCommand
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_cases import ManagedCompanyRow
from grantcompass.storage.table_documents import EvidenceRow
from grantcompass.storage.table_eligibility import EligibilityRuleRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, ProgramRow
from tests.cli_fixtures import FixedClock, make_dependencies

pytestmark = pytest.mark.anyio
DOCUMENT_FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"
ANNOUNCEMENT_DATE = date(2026, 1, 1)
COLLECTED_AT = datetime(2026, 1, 15, 9, tzinfo=UTC)
LATE_INVOCATION = datetime(2030, 7, 15, 12, tzinfo=UTC)


@dataclass(slots=True)
class OneNoticeAdapter:
    notice: RawNotice
    name: SourceName = SourceName.BIZINFO

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        del page_size
        return SourcePage(
            items=(self.notice,), page=page, has_next=False, response_hash="page-hash"
        )


def _notice(source: SourceName, notice_id: str, *, announcement_date: date | None) -> RawNotice:
    return RawNotice(
        source=source,
        source_notice_id=notice_id,
        title=f"Clean database program {notice_id}",
        organization="Synthetic public institution",
        summary="Deterministic eligibility document",
        announcement_date=announcement_date,
        application_start=date(2026, 1, 1),
        application_end=date(2031, 12, 31),
        detail_url=HttpUrl(f"https://example.invalid/notices/{notice_id}"),
        attachments=(
            AttachmentRef(
                filename="eligibility.hwpx",
                download_url=HttpUrl("https://93.184.216.34/eligibility.hwpx"),
                media_type="application/hwp+zip",
            ),
        ),
        raw_payload=freeze_json_object({"notice_id": notice_id}),
    )


def _notice_with_attachment_batch(size: int) -> RawNotice:
    notice = _notice(
        SourceName.BIZINFO,
        "official-batch-progress",
        announcement_date=ANNOUNCEMENT_DATE,
    )
    return notice.model_copy(
        update={
            "attachments": tuple(
                AttachmentRef(
                    filename=f"eligibility-{index:02d}.hwpx",
                    download_url=HttpUrl(f"https://93.184.216.34/eligibility-{index:02d}.hwpx"),
                    media_type="application/hwp+zip",
                )
                for index in range(size)
            )
        }
    )


async def _create_profile_and_company(database_url: str) -> int:
    engine = create_engine(database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            profile = await ProfileRepository(session).create(
                ProfileCreateInput(
                    display_name="Reference-date founder",
                    founded_on=date(2023, 1, 2),
                    regions=("서울특별시",),
                    industries=("software",),
                ),
                COLLECTED_AT,
            )
            assert profile.id is not None
            async with session.begin():
                session.add(
                    ManagedCompanyRow(
                        profile_id=int(profile.id),
                        owner_name="Institution owner",
                        active=True,
                    )
                )
            return int(profile.id)
    finally:
        await engine.dispose()


async def _assert_searchable(database_url: str, profile_id: int) -> None:
    bundle = await search_programs(database_url, str(profile_id), LATE_INVOCATION)
    assert len(bundle.output.results) == 1
    result = bundle.output.results[0]
    assert result.input_errors == ()
    assert result.review_status is ReviewStatus.REVIEW_REQUIRED
    assert len(result.conditions) == 1
    assert result.conditions[0].status is ConditionStatus.SATISFIED
    assert result.conditions[0].evidence_ids
    assert result.evidence


async def test_clean_manual_upload_reaches_rules_evidence_founder_and_institution_search(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'manual-clean.db'}"
    await initialize_database(database_url)
    notice = _notice(SourceName.MANUAL, "manual-clean", announcement_date=None)
    content = (DOCUMENT_FIXTURES / "eligibility-table.hwpx").read_bytes()
    engine = create_engine(database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            result = await ProgramRepository(session).create_manual_notice(
                ManualNoticeCommand(
                    notice=notice,
                    collected_at=COLLECTED_AT,
                    actor="Institution reviewer",
                    reason="Clean database acceptance",
                    document_content=content,
                    document_filename="eligibility.hwpx",
                )
            )
            program_id = int(result.program_id)
            rule = (await session.scalars(select(EligibilityRuleRow))).one()
            evidence = (await session.scalars(select(EvidenceRow))).one()
            block_text = await session.scalar(
                select(EvidenceRow.quote).where(EvidenceRow.id == evidence.id)
            )
            program = (await session.scalars(select(ProgramRow))).one()
            version = (await session.scalars(select(NoticeVersionRow))).one()
            assert rule.review_status == ReviewStatus.REVIEW_REQUIRED.value
            assert rule.source_document_id == evidence.document_id
            assert block_text == "업력 3년 이내"
            assert evidence.source_url == str(notice.detail_url)
            assert program.reference_date == COLLECTED_AT.date()
            assert program.reference_date_source == "collected_at_fallback"
            assert version.announcement_date is None
            assert version.reference_date == COLLECTED_AT.date()
            assert version.reference_date_source == "collected_at_fallback"
    finally:
        await engine.dispose()

    profile_id = await _create_profile_and_company(database_url)
    await _assert_searchable(database_url, profile_id)
    reverse_engine = create_engine(database_url)
    try:
        factory = create_session_factory(reverse_engine)
        async with factory() as session:
            matches = await ReverseMatchingService(session).reverse_match(
                ProgramId(program_id),
                LATE_INVOCATION,
            )
            assert len(matches) == 1
            assert matches[0].assessment is not None
            assert matches[0].assessment.items[0].status is ConditionStatus.SATISFIED
    finally:
        await reverse_engine.dispose()


async def test_clean_official_sync_downloads_and_analyzes_before_search(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'official-clean.db'}"
    await initialize_database(database_url)
    notice = _notice(SourceName.BIZINFO, "official-clean", announcement_date=ANNOUNCEMENT_DATE)
    document = (DOCUMENT_FIXTURES / "eligibility-table.hwpx").read_bytes()

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/hwp+zip"},
            content=document,
            request=request,
        )

    def client_factory() -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(respond))

    dependencies = make_dependencies(
        database_url,
        (OneNoticeAdapter(notice),),
        bizinfo_key="synthetic-key",
        client_factory=client_factory,
    )
    dependencies = type(dependencies)(
        settings_provider=dependencies.settings_provider,
        clock=FixedClock(COLLECTED_AT),
        adapter_factory=dependencies.adapter_factory,
        client_factory=dependencies.client_factory,
    )

    output = await synchronize_sources(dependencies, SourceSelection.BIZINFO)

    assert output.results[0].stored == 1
    engine = create_engine(database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            attachment = (await session.scalars(select(AttachmentRow))).one()
            program = (await session.scalars(select(ProgramRow))).one()
            assert attachment.parse_status == "parsed"
            assert await session.scalar(select(func.count(EligibilityRuleRow.id))) == 1
            assert await session.scalar(select(func.count(EvidenceRow.id))) == 1
            assert program.reference_date == ANNOUNCEMENT_DATE
            assert program.reference_date_source == "announcement_date"
    finally:
        await engine.dispose()

    profile_id = await _create_profile_and_company(database_url)
    await _assert_searchable(database_url, profile_id)


async def test_reanalysis_removes_generated_rules_instead_of_leaving_stale_search_data(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'reanalysis.db'}"
    await initialize_database(database_url)
    notice = _notice(SourceName.MANUAL, "manual-reanalysis", announcement_date=None)
    first = (DOCUMENT_FIXTURES / "eligibility-table.hwpx").read_bytes()
    replacement = (DOCUMENT_FIXTURES / "merged-cells.hwpx").read_bytes()
    engine = create_engine(database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            repository = ProgramRepository(session)
            for content, reason in ((first, "initial parse"), (replacement, "replacement parse")):
                _ = await repository.create_manual_notice(
                    ManualNoticeCommand(
                        notice,
                        COLLECTED_AT,
                        "Institution reviewer",
                        reason,
                        content,
                        "eligibility.hwpx",
                    )
                )
            attachment = (await session.scalars(select(AttachmentRow))).one()
            assert await session.scalar(select(func.count(EligibilityRuleRow.id))) == 0
            assert await session.scalar(select(func.count(EvidenceRow.id))) == 0
            assert attachment.parse_status == "parsed"
            assert attachment.parse_error_code == "no_rule_candidates"
            assert attachment.requires_review is True
    finally:
        await engine.dispose()


async def test_official_attachment_download_failure_is_durable_and_visible(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'official-failure.db'}"
    await initialize_database(database_url)
    notice = _notice(SourceName.BIZINFO, "official-failure", announcement_date=ANNOUNCEMENT_DATE)

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, request=request)

    dependencies = make_dependencies(
        database_url,
        (OneNoticeAdapter(notice),),
        bizinfo_key="synthetic-key",
        client_factory=lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    _ = await synchronize_sources(dependencies, SourceSelection.BIZINFO)

    engine = create_engine(database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            attachment = (await session.scalars(select(AttachmentRow))).one()
            assert attachment.parse_status == "failed"
            assert attachment.parse_error_code == "download_failed"
            assert attachment.requires_review is True
    finally:
        await engine.dispose()


async def test_official_attachment_batches_advance_past_failed_rows_without_pending_starvation(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'official-batch-progress.db'}"
    await initialize_database(database_url)
    notice = _notice_with_attachment_batch(21)
    document = (DOCUMENT_FIXTURES / "eligibility-table.hwpx").read_bytes()
    observed_paths: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        observed_paths.append(request.url.path)
        if request.url.path.endswith("eligibility-20.hwpx"):
            return httpx2.Response(
                200,
                headers={"Content-Type": "application/hwp+zip"},
                content=document,
                request=request,
            )
        return httpx2.Response(503, request=request)

    dependencies = make_dependencies(
        database_url,
        (OneNoticeAdapter(notice),),
        bizinfo_key="synthetic-key",
        client_factory=lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )

    _ = await synchronize_sources(dependencies, SourceSelection.BIZINFO)
    first_batch = tuple(observed_paths)
    _ = await synchronize_sources(dependencies, SourceSelection.BIZINFO)
    second_batch = tuple(observed_paths[len(first_batch) :])

    assert first_batch == tuple(f"/eligibility-{index:02d}.hwpx" for index in range(20))
    assert len(second_batch) == 20
    assert second_batch[0] == "/eligibility-20.hwpx"

    engine = create_engine(database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            rows = (await session.scalars(select(AttachmentRow).order_by(AttachmentRow.id))).all()
            assert (rows[-1].filename, rows[-1].parse_status) == (
                "eligibility-20.hwpx",
                "parsed",
            )
            assert sum(row.parse_status == "failed" for row in rows) == 20
            assert all(row.parse_status != "pending" for row in rows)
            assert await session.scalar(select(func.count(EligibilityRuleRow.id))) == 1
            assert await session.scalar(select(func.count(EvidenceRow.id))) == 1
    finally:
        await engine.dispose()


async def test_failed_current_notice_never_falls_back_to_historical_generated_rules(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'current-rules-failed.db'}"
    await initialize_database(database_url)
    source_id = "current-rules-failed"
    base = _notice(SourceName.BIZINFO, source_id, announcement_date=ANNOUNCEMENT_DATE)
    variants = tuple(
        base.model_copy(
            update={
                "attachments": (
                    AttachmentRef(
                        filename=f"eligibility-{variant}.hwpx",
                        download_url=HttpUrl(f"https://93.184.216.34/eligibility-{variant}.hwpx"),
                        media_type="application/hwp+zip",
                    ),
                ),
                "raw_payload": freeze_json_object({"variant": variant}),
            }
        )
        for variant in ("a", "b")
    )
    payloads = {
        "/eligibility-a.hwpx": (DOCUMENT_FIXTURES / "eligibility-table.hwpx").read_bytes(),
        "/eligibility-b.hwpx": (DOCUMENT_FIXTURES / "merged-cells.hwpx").read_bytes(),
    }

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/hwp+zip"},
            content=payloads[request.url.path],
            request=request,
        )

    profile_id = await _create_profile_and_company(database_url)
    for notice in variants:
        dependencies = make_dependencies(
            database_url,
            (OneNoticeAdapter(notice),),
            bizinfo_key="synthetic-key",
            client_factory=lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        )
        _ = await synchronize_sources(dependencies, SourceSelection.BIZINFO)

    search = await search_programs(database_url, str(profile_id), LATE_INVOCATION)
    assert len(search.output.results) == 1
    assert search.output.results[0].input_errors == ("missing_rules",)
    assert search.output.results[0].conditions == ()

    engine = create_engine(database_url)
    try:
        factory = create_session_factory(engine)
        async with factory() as session:
            program_id = int((await session.scalars(select(ProgramRow.id))).one())
            await session.rollback()
            reverse = await ReverseMatchingService(session).reverse_match(
                ProgramId(program_id),
                LATE_INVOCATION,
            )
            assert reverse[0].assessment is None
            assert reverse[0].input_error is not None
    finally:
        await engine.dispose()


async def test_recurrence_uses_only_each_current_version_in_forward_and_reverse_matching(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'current-rules-recurrence.db'}"
    await initialize_database(database_url)
    source_id = "current-rules-recurrence"
    base = _notice(SourceName.BIZINFO, source_id, announcement_date=ANNOUNCEMENT_DATE)
    variants = {
        "a": base.model_copy(
            update={
                "attachments": (
                    AttachmentRef(
                        filename="eligibility-a.hwpx",
                        download_url=HttpUrl("https://93.184.216.34/eligibility-a.hwpx"),
                        media_type="application/hwp+zip",
                    ),
                ),
                "raw_payload": freeze_json_object({"variant": "a"}),
            }
        ),
        "b": base.model_copy(
            update={
                "attachments": (
                    AttachmentRef(
                        filename="eligibility-b.hwpx",
                        download_url=HttpUrl("https://93.184.216.34/eligibility-b.hwpx"),
                        media_type="application/hwp+zip",
                    ),
                ),
                "raw_payload": freeze_json_object({"variant": "b"}),
            }
        ),
    }
    payloads = {
        "/eligibility-a.hwpx": (DOCUMENT_FIXTURES / "eligibility-table.hwpx").read_bytes(),
        "/eligibility-b.hwpx": (
            Path(__file__).parents[1] / "fixtures" / "benchmark" / "documents" / "case-05.hwpx"
        ).read_bytes(),
    }

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/hwp+zip"},
            content=payloads[request.url.path],
            request=request,
        )

    profile_id = await _create_profile_and_company(database_url)
    observed: list[ConditionStatus] = []
    for variant in ("a", "b", "a", "b"):
        dependencies = make_dependencies(
            database_url,
            (OneNoticeAdapter(variants[variant]),),
            bizinfo_key="synthetic-key",
            client_factory=lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
        )
        _ = await synchronize_sources(dependencies, SourceSelection.BIZINFO)
        search = await search_programs(database_url, str(profile_id), LATE_INVOCATION)
        observed.append(search.output.results[0].conditions[0].status)

        engine = create_engine(database_url)
        try:
            factory = create_session_factory(engine)
            async with factory() as session:
                program_id = int((await session.scalars(select(ProgramRow.id))).one())
                await session.rollback()
                reverse = await ReverseMatchingService(session).reverse_match(
                    ProgramId(program_id),
                    LATE_INVOCATION,
                )
                assert reverse[0].assessment is not None
                assert reverse[0].assessment.items[0].status is observed[-1]
        finally:
            await engine.dispose()

    assert observed == [
        ConditionStatus.SATISFIED,
        ConditionStatus.UNSATISFIED,
        ConditionStatus.SATISFIED,
        ConditionStatus.UNSATISFIED,
    ]


async def test_production_parse_persists_official_urls_and_promotes_dual_source_conflict(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'official-conflict.db'}"
    await initialize_database(database_url)
    source_id = "official-conflict"
    base = _notice(SourceName.KSTARTUP, source_id, announcement_date=ANNOUNCEMENT_DATE)
    notices = (
        base.model_copy(
            update={
                "detail_url": HttpUrl("https://official-a.example/notices/a"),
                "attachments": (
                    AttachmentRef(
                        filename="eligibility-a.hwpx",
                        download_url=HttpUrl("https://93.184.216.34/eligibility-a.hwpx"),
                        media_type="application/hwp+zip",
                    ),
                ),
                "raw_payload": freeze_json_object({"source": "a"}),
            }
        ),
        base.model_copy(
            update={
                "source": SourceName.BIZINFO,
                "detail_url": HttpUrl("https://official-b.example/notices/b"),
                "attachments": (
                    AttachmentRef(
                        filename="eligibility-b.hwpx",
                        download_url=HttpUrl("https://93.184.216.34/eligibility-b.hwpx"),
                        media_type="application/hwp+zip",
                    ),
                ),
                "raw_payload": freeze_json_object({"source": "b"}),
            }
        ),
    )
    payloads = {
        "/eligibility-a.hwpx": (DOCUMENT_FIXTURES / "eligibility-table.hwpx").read_bytes(),
        "/eligibility-b.hwpx": (
            Path(__file__).parents[1] / "fixtures" / "benchmark" / "documents" / "case-05.hwpx"
        ).read_bytes(),
    }

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"Content-Type": "application/hwp+zip"},
            content=payloads[request.url.path],
            request=request,
        )

    dependencies = make_dependencies(
        database_url,
        (
            OneNoticeAdapter(notices[0], SourceName.KSTARTUP),
            OneNoticeAdapter(notices[1], SourceName.BIZINFO),
        ),
        kstartup_key="synthetic-key-a",
        bizinfo_key="synthetic-key-b",
        client_factory=lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    _ = await synchronize_sources(dependencies, SourceSelection.ALL)
    profile_id = await _create_profile_and_company(database_url)

    search = await search_programs(database_url, str(profile_id), LATE_INVOCATION)

    assert len(search.output.results) == 1
    result = search.output.results[0]
    assert tuple(item.status for item in result.conditions) == (
        ConditionStatus.CONFLICT,
        ConditionStatus.CONFLICT,
    )
    assert {item.source_url for item in result.evidence} == {
        "https://official-a.example/notices/a",
        "https://official-b.example/notices/b",
    }


async def test_failed_attachment_retry_batches_rotate_fairly_across_forty_five_rows(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'official-retry-rotation.db'}"
    await initialize_database(database_url)
    notice = _notice_with_attachment_batch(45)
    observed_paths: list[str] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        observed_paths.append(request.url.path)
        return httpx2.Response(503, request=request)

    dependencies = make_dependencies(
        database_url,
        (OneNoticeAdapter(notice),),
        bizinfo_key="synthetic-key",
        client_factory=lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    for _ in range(3):
        _ = await synchronize_sources(dependencies, SourceSelection.BIZINFO)

    assert observed_paths[:20] == [f"/eligibility-{index:02d}.hwpx" for index in range(20)]
    assert observed_paths[20:40] == [f"/eligibility-{index:02d}.hwpx" for index in range(20, 40)]
    assert observed_paths[40:45] == [f"/eligibility-{index:02d}.hwpx" for index in range(40, 45)]
