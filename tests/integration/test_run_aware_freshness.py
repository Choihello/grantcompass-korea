from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.freshness import load_one_source_freshness
from grantcompass.domain.enums import FreshnessStatus, SourceName
from grantcompass.reports.pdf import ConsultationReportService
from grantcompass.storage.table_programs import SourceRunRow
from grantcompass.web.queries import list_programs
from tests.cli_fixtures import FixedClock
from tests.e2e.institution_seed import seed_institution

pytestmark = pytest.mark.anyio


async def test_recent_notice_followed_by_failed_sync_is_stale_on_cli_web_and_pdf(
    db_session: AsyncSession,
) -> None:
    await seed_institution(db_session)
    success = datetime(2026, 7, 20, 9, tzinfo=UTC)
    failure = datetime(2026, 7, 20, 10, tzinfo=UTC)
    db_session.add_all(
        (
            SourceRunRow(
                source=SourceName.KSTARTUP.value,
                started_at=success,
                finished_at=success,
                status="succeeded",
                item_count=1,
                response_hash="success-hash",
                error_code=None,
                error_message=None,
            ),
            SourceRunRow(
                source=SourceName.KSTARTUP.value,
                started_at=failure,
                finished_at=failure,
                status="failed",
                item_count=0,
                response_hash=None,
                error_code="upstream_failed",
                error_message="synthetic upstream failure",
            ),
        )
    )
    await db_session.commit()

    cli = await load_one_source_freshness(db_session, SourceName.KSTARTUP)
    web = await list_programs(db_session, failure)
    pdf = await ConsultationReportService(db_session, FixedClock(failure)).load(1)

    assert cli.status is FreshnessStatus.STALE
    assert cli.error_code == "upstream_failed"
    assert web[0].freshness == "stale"
    assert pdf.sources[0].freshness == "stale"
