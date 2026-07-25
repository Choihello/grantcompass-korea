from datetime import UTC, date, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.table_documents import (
    DocumentBlockRow,
    DocumentRow,
    EvidenceRow,
    rule_evidence,
)
from grantcompass.storage.table_eligibility import EligibilityRuleRow
from grantcompass.storage.table_programs import (
    AttachmentRow,
    NoticeVersionRow,
    ProgramRow,
    SourceRunRow,
)


async def seed_search_fixture(
    database_url: str,
    *,
    representative_age: bool = False,
) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            for program_id in range(1, 6):
                session.add(
                    ProgramRow(
                        id=program_id,
                        canonical_key=f"program-{program_id}",
                        title=f"합성 지원사업 {program_id}",
                        organization="합성 창업지원기관",
                        application_start=date(2026, 7, 1),
                        application_end=date(2026, 8, program_id),
                        created_at=datetime(2026, 1, 1, tzinfo=UTC),
                        updated_at=datetime(2026, 7, 1, tzinfo=UTC),
                        reference_date=date(2026, 7, 1),
                        reference_date_source="announcement_date",
                    )
                )
            await session.flush()
            for program_id in range(1, 5):
                await _add_evidence_chain(session, program_id)
                session.add(
                    _representative_age_rule()
                    if representative_age and program_id == 1
                    else _rule_for(program_id)
                )
                await session.flush()
            session.add_all(_source_runs())
            await session.flush()
            _ = await session.execute(
                insert(rule_evidence),
                tuple(
                    {"rule_id": program_id * 10, "evidence_id": program_id * 10}
                    for program_id in range(1, 5)
                ),
            )
    finally:
        await engine.dispose()


def _source_runs() -> tuple[SourceRunRow, ...]:
    return (
        SourceRunRow(
            id=1,
            source=SourceName.KSTARTUP.value,
            started_at=datetime(2026, 7, 14, tzinfo=UTC),
            finished_at=datetime(2026, 7, 14, 1, tzinfo=UTC),
            status="succeeded",
            item_count=4,
            response_hash="k-hash",
            error_code=None,
            error_message=None,
        ),
        SourceRunRow(
            id=2,
            source=SourceName.BIZINFO.value,
            started_at=datetime(2026, 7, 13, tzinfo=UTC),
            finished_at=datetime(2026, 7, 13, 1, tzinfo=UTC),
            status="succeeded",
            item_count=4,
            response_hash="b-hash",
            error_code=None,
            error_message=None,
        ),
        SourceRunRow(
            id=3,
            source=SourceName.BIZINFO.value,
            started_at=datetime(2026, 7, 15, tzinfo=UTC),
            finished_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
            status="failed",
            item_count=0,
            response_hash=None,
            error_code="synthetic_stale",
            error_message="synthetic stale",
        ),
    )


async def _add_evidence_chain(session: AsyncSession, program_id: int) -> None:
    identity = program_id * 10
    session.add(
        NoticeVersionRow(
            id=identity,
            program_id=program_id,
            source=SourceName.KSTARTUP.value,
            source_notice_id=f"K-{program_id}",
            content_hash=f"{identity:064x}",
            detail_url=f"https://www.k-startup.go.kr/notice/{program_id}",
            raw_payload_json="{}",
            normalized_json="{}",
            collected_at=datetime(2026, 7, 14, tzinfo=UTC),
            announcement_date=date(2026, 7, 14),
            reference_date=date(2026, 7, 14),
            reference_date_source="announcement_date",
        )
    )
    await session.flush()
    session.add(
        AttachmentRow(
            id=identity,
            notice_version_id=identity,
            filename=f"notice-{program_id}.pdf",
            download_url=f"https://www.k-startup.go.kr/files/{program_id}.pdf",
            media_type="application/pdf",
            content_hash=f"{identity:064x}",
            local_path=None,
            parse_status="parsed",
            parse_error_code=None,
            requires_review=False,
            parser_name="synthetic",
            parser_version="1",
        )
    )
    await session.flush()
    session.add(
        DocumentRow(
            id=identity,
            attachment_id=identity,
            parser_name="synthetic",
            parser_version="1",
            content_hash=f"{identity:064x}",
            parsed_at=datetime(2026, 7, 14, tzinfo=UTC),
            warning_json="[]",
        )
    )
    await session.flush()
    session.add(
        DocumentBlockRow(
            id=identity,
            document_id=identity,
            ordinal=0,
            kind="paragraph",
            text=f"합성 조건 {program_id}",
            page=program_id,
            section_path="신청자격",
            table_ref=None,
            source_block_id=f"block-{program_id}",
            bbox_json=None,
            confidence=1.0,
            provenance="pdf_text",
        )
    )
    await session.flush()
    session.add(
        EvidenceRow(
            id=identity,
            document_id=identity,
            block_id=identity,
            source_url=f"https://www.k-startup.go.kr/notice/{program_id}",
            page=program_id,
            section_path="신청자격",
            quote=f"합성 조건 {program_id}",
            content_hash=f"{identity:064x}",
        )
    )
    await session.flush()


def _rule_for(program_id: int) -> EligibilityRuleRow:
    kinds = ("region", "industry", "natural_language", "region")
    expected = ('["서울"]', '["manufacturing"]', '"검토 필요"', '["부산"]')
    required = (True, False, True, True)
    return EligibilityRuleRow(
        id=program_id * 10,
        program_id=program_id,
        kind=kinds[program_id - 1],
        operator="in",
        expected_json=expected[program_id - 1],
        required=required[program_id - 1],
        review_status="automatic",
        rule_version="rules-v1",
    )


def _representative_age_rule() -> EligibilityRuleRow:
    return EligibilityRuleRow(
        id=10,
        program_id=1,
        kind="representative_age",
        operator="lte",
        expected_json="40",
        required=True,
        review_status="automatic",
        rule_version="rules-v1",
    )
