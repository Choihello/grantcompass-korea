from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.ids import ProgramId
from grantcompass.matching.reverse import ReverseMatchingService
from grantcompass.storage.table_cases import ManagedCompanyRow
from grantcompass.storage.table_eligibility import ApplicantProfileRow, EligibilityRuleRow
from grantcompass.storage.table_programs import ProgramRow
from grantcompass.web.queries import get_program_detail, list_programs
from tests.integration.task12_fixtures import REFERENCE_TIME

pytestmark = pytest.mark.anyio
_ROW_COUNT = 50


@asynccontextmanager
async def _statement_counter(session: AsyncSession) -> AsyncGenerator[list[str]]:
    bind = session.get_bind()
    statements: list[str] = []

    def record(*args: str) -> None:
        statements.append(args[2])

    event.listen(bind, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(bind, "before_cursor_execute", record)


def _program(index: int) -> ProgramRow:
    return ProgramRow(
        canonical_key=f"query-count-{index}",
        title=f"합성 지원사업 {index}",
        organization="합성 기관",
        application_start=date(2026, 7, 1),
        application_end=date(2026, 8, 31),
        created_at=REFERENCE_TIME,
        updated_at=REFERENCE_TIME,
        reference_date=REFERENCE_TIME.date(),
        reference_date_source="announcement_date",
    )


async def test_reverse_matching_reads_target_rules_and_company_profiles_in_bounded_queries(
    db_session: AsyncSession,
) -> None:
    # Removing either targeted rules or batched profiles makes this scale with 50 rows.
    programs = [_program(index) for index in range(_ROW_COUNT)]
    db_session.add_all(programs)
    await db_session.flush()
    profiles = [
        ApplicantProfileRow(
            display_name=f"합성기업 {index}",
            founded_on=date(2025, 1, 1),
            regions_json='["KR-11"]',
            representative_birth_year=1990,
            industries_json='["software"]',
            performance_json="{}",
            benefit_history_json="[]",
            created_at=REFERENCE_TIME,
        )
        for index in range(_ROW_COUNT)
    ]
    db_session.add_all(profiles)
    await db_session.flush()
    db_session.add_all(
        ManagedCompanyRow(profile_id=profile.id, owner_name="합성 대표", active=True)
        for profile in profiles
    )
    await db_session.commit()
    db_session.expunge_all()

    async with _statement_counter(db_session) as statements:
        results = await ReverseMatchingService(db_session).reverse_match(
            ProgramId(programs[-1].id),
            REFERENCE_TIME,
        )

    assert len(results) == _ROW_COUNT
    assert len(statements) == 4, tuple(statements)


async def test_program_detail_batches_evidence_independently_of_rule_count(
    db_session: AsyncSession,
) -> None:
    # A per-rule evidence lookup makes this exceed the fixed read budget by 50 queries.
    program = _program(100)
    db_session.add(program)
    await db_session.flush()
    db_session.add_all(
        EligibilityRuleRow(
            program_id=program.id,
            kind="region",
            operator="in",
            expected_json='"KR-11"',
            required=True,
            review_status="automatic",
            rule_version="rules-v1",
        )
        for _ in range(_ROW_COUNT)
    )
    await db_session.commit()
    db_session.expunge_all()

    async with _statement_counter(db_session) as statements:
        detail = await get_program_detail(db_session, program.id, "Asia/Seoul")

    assert detail is not None
    assert len(detail.evidence) == _ROW_COUNT
    assert len(statements) == 5, tuple(statements)


async def test_program_ledger_reads_are_bounded_independently_of_program_count(
    db_session: AsyncSession,
) -> None:
    # Per-program current-notice and change reads would add 100 statements here.
    db_session.add_all(_program(200 + index) for index in range(_ROW_COUNT))
    await db_session.commit()
    db_session.expunge_all()

    async with _statement_counter(db_session) as statements:
        entries = await list_programs(db_session, REFERENCE_TIME)

    assert len(entries) == _ROW_COUNT
    assert len(statements) == 3, tuple(statements)
