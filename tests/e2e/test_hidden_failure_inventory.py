from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import select

from grantcompass.config import Settings
from grantcompass.domain.enums import SourceName
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.table_eligibility import RuleAssessmentRow
from grantcompass.storage.table_notice_analysis import FieldConflictRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, SourceRunRow
from grantcompass.storage.tables import Base
from grantcompass.web.app import create_app, dispose_app
from grantcompass.web.failures import FailureHealth
from tests.cli_fixtures import FixedClock
from tests.e2e.institution_seed import seed_institution

pytestmark = pytest.mark.anyio


async def _seed_hidden_failures(database_url: str) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    now = datetime(2026, 7, 22, 10, tzinfo=UTC)
    async with session_factory() as session:
        notice = (
            await session.scalars(select(NoticeVersionRow).order_by(NoticeVersionRow.id))
        ).first()
        rule_assessment = (await session.scalars(select(RuleAssessmentRow))).first()
        assert notice is not None
        assert rule_assessment is not None
        session.add(
            SourceRunRow(
                source=SourceName.BIZINFO.value,
                started_at=now,
                finished_at=now,
                status="failed",
                item_count=0,
                response_hash=None,
                error_code="rate_limited",
                error_message="synthetic hidden source failure",
            )
        )
        for ordinal in range(2):
            session.add(
                AttachmentRow(
                    notice_version_id=notice.id,
                    filename=f"synthetic-encrypted-{ordinal}.pdf",
                    download_url=f"https://example.invalid/encrypted-{ordinal}.pdf",
                    media_type="application/pdf",
                    content_hash=None,
                    local_path=None,
                    parse_status="failed",
                    parse_error_code="encrypted_pdf",
                    requires_review=True,
                    parser_name=None,
                    parser_version=None,
                )
            )
        session.add(
            FieldConflictRow(
                program_id=notice.program_id,
                field_name="organization",
                values_json='["명백한 합성기관 A","명백한 합성기관 B"]',
                detected_at=now,
            )
        )
        rule_assessment.status = "unknown"
        rule_assessment.error_id = "unsupported_rule_kind"
        await session.commit()
    await engine.dispose()


async def test_health_reports_persisted_hidden_candidates_in_stable_order(
    tmp_path: Path,
) -> None:
    # Given: persisted source, duplicate attachment, conflict, and rule-assessment errors.
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'hidden-failures.db'}"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await seed_institution(session)
    await engine.dispose()
    await _seed_hidden_failures(database_url)
    app = create_app(
        Settings(database_url=database_url, allowed_hosts=("hidden-failures.test",)),
        FixedClock(),
    )

    # When: the operator reads the machine health contract twice.
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://hidden-failures.test",
    ) as client:
        first = await client.get("/health/failures")
        second = await client.get("/health/failures")
    await dispose_app(app)

    # Then: database-derived candidates are deduplicated and deterministically namespaced.
    assert first.status_code == 200
    assert second.content == first.content
    payload = FailureHealth.model_validate_json(first.content)
    assert payload.visible_failure_ids == ()
    assert payload.hidden_failures == (
        "attachment_parse:encrypted_pdf",
        "field_conflict:organization",
        "rule_assessment:unsupported_rule_kind",
        "source_run:bizinfo:rate_limited",
    )
