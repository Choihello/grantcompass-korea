from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.config import Settings
from grantcompass.documents.ingest import DocumentIngestor
from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import RawNotice
from grantcompass.domain.source_runs import SourceRunFailure, SourceRunSuccess
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_eligibility import ApplicantProfileRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow
from grantcompass.storage.tables import Base
from grantcompass.web.app import create_app, dispose_app
from grantcompass.web.failures import FailureHealth, load_failure_snapshot
from tests.cli_fixtures import FixedClock

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"


@dataclass(frozen=True, slots=True)
class FailureHarness:
    app: FastAPI
    client: httpx2.AsyncClient


def _notice(source: SourceName, notice_id: str, deadline: date) -> RawNotice:
    return RawNotice(
        source=source,
        source_notice_id=notice_id,
        title="명백한 합성 실패표면 지원사업",
        organization="명백한 합성 지원기관",
        summary="실패 상태 검증 전용 합성 공고",
        application_start=date(2026, 7, 1),
        application_end=deadline,
        detail_url=HttpUrl(f"https://example.invalid/{source.value}/{notice_id}"),
        raw_payload=freeze_json_object({"fixture": "synthetic-failure"}),
    )


async def _seed_failures(database_url: str) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 7, 22, 9, tzinfo=UTC)
    async with session_factory() as session:
        repository = ProgramRepository(session)
        first = await repository.upsert_notice(
            _notice(SourceName.KSTARTUP, "SYNTH-K-503", date(2026, 8, 1)),
            now - timedelta(days=2),
        )
        successful_run_id = await repository.start_source_run(
            SourceName.KSTARTUP, now - timedelta(days=2)
        )
        await repository.complete_source_run(
            successful_run_id,
            SourceRunSuccess(
                finished_at=now - timedelta(days=2),
                item_count=1,
                response_hash="1" * 64,
            ),
        )
        _ = await repository.upsert_notice(
            _notice(SourceName.BIZINFO, "SYNTH-B-CONFLICT", date(2026, 8, 1)),
            now - timedelta(days=2),
        )
        _ = await repository.upsert_notice(
            _notice(
                SourceName.BIZINFO,
                "SYNTH-B-CONFLICT",
                date(2026, 8, 8),
            ),
            now - timedelta(days=1),
        )
        run_id = await repository.start_source_run(SourceName.KSTARTUP, now)
        await repository.fail_source_run(
            run_id,
            SourceRunFailure(
                finished_at=now,
                item_count=0,
                response_hash=None,
                error_code="http_503",
                error_message="synthetic upstream unavailable",
            ),
        )
        notice = await session.get(NoticeVersionRow, int(first.notice_version_id))
        assert notice is not None
        attachment = AttachmentRow(
            notice_version_id=notice.id,
            filename="synthetic-scan.pdf",
            download_url="https://example.invalid/synthetic-scan.pdf",
            media_type="application/pdf",
            content_hash=None,
            local_path=None,
            parse_status="pending",
        )
        session.add(attachment)
        await session.flush()
        _ = await DocumentIngestor(session).ingest(
            attachment.id,
            (FIXTURES / "scanned-page.pdf").read_bytes(),
            attachment.filename,
        )
        session.add(
            ApplicantProfileRow(
                display_name="명백한 합성 미완성기업",
                founded_on=None,
                regions_json="[]",
                representative_birth_year=None,
                industries_json="[]",
                performance_json="{}",
                benefit_history_json="[]",
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


@pytest.fixture
async def failure_client(tmp_path: Path) -> AsyncIterator[FailureHarness]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'failures.db'}"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    await _seed_failures(database_url)
    app = create_app(Settings(database_url=database_url), FixedClock())
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://failures.test",
    ) as client:
        yield FailureHarness(app, client)
    await dispose_app(app)


async def test_stale_source_scan_pdf_conflict_and_missing_profile_are_visible(
    failure_client: FailureHarness,
) -> None:
    # Given: persisted 503, scan-only PDF, deadline conflict, and incomplete profile states.
    # When: an operator opens both the human and machine-readable failure surfaces.
    page = await failure_client.client.get("/programs/failure-scenario")
    health = await failure_client.client.get("/health/failures")

    # Then: every stable failure ID is visible and none are silently hidden.
    expected = {
        "source_503_stale",
        "scan_pdf_ocr_required",
        "conflicting_deadlines",
        "incomplete_profile_needs_review",
    }
    assert page.status_code == 200
    assert all(item in page.text for item in expected)
    assert health.status_code == 200
    payload = FailureHealth.model_validate_json(health.content)
    assert set(payload.visible_failure_ids) == expected
    assert payload.hidden_failures == ()


async def test_503_without_retained_success_is_not_reported_as_stale(
    db_session: AsyncSession,
    now: datetime,
) -> None:
    # Given: a latest 503 source run with no successful run and no retained source notice.
    repository = ProgramRepository(db_session)
    run_id = await repository.start_source_run(SourceName.KSTARTUP, now)
    await repository.fail_source_run(
        run_id,
        SourceRunFailure(
            finished_at=now,
            item_count=0,
            response_hash=None,
            error_code="http_503",
            error_message="synthetic first-run outage",
        ),
    )

    # When: the persisted failure inventory is resolved.
    snapshot = await load_failure_snapshot(db_session)

    # Then: a first-run outage is not misrepresented as retained stale data.
    assert "source_503_stale" not in snapshot.visible_failure_ids
    assert snapshot.hidden_failures == ("source_run:kstartup:http_503",)
