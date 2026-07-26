import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.ids import ProgramId
from grantcompass.domain.reverse import CompanyInputErrorCode
from grantcompass.matching.reverse import ReverseMatchingService
from grantcompass.storage.table_cases import AuditEventRow, CaseRow, ManagedCompanyRow
from grantcompass.storage.table_documents import DocumentBlockRow
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    EligibilityRuleRow,
    RuleAssessmentRow,
)
from grantcompass.storage.table_programs import ProgramRow
from grantcompass.web.company_queries import list_companies
from grantcompass.web.match_queries import latest_matches
from grantcompass.web.queries import get_program_detail, list_programs
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_program, seed_rule

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


async def test_company_ledger_batches_profiles_and_latest_cases(
    db_session: AsyncSession,
) -> None:
    # Per-company profile and latest-case reads add 100 statements for this fixture.
    program = _program(300)
    db_session.add(program)
    profiles = [
        ApplicantProfileRow(
            display_name=f"관리기업 {index}",
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
    companies = [
        ManagedCompanyRow(profile_id=profile.id, owner_name="합성 대표", active=True)
        for profile in profiles
    ]
    db_session.add_all(companies)
    await db_session.flush()
    for company in companies:
        db_session.add_all(
            (
                CaseRow(
                    managed_company_id=company.id,
                    program_id=program.id,
                    assignee_name="기관 담당자",
                    stage="recommended",
                    note="이전 상담",
                    updated_at=REFERENCE_TIME,
                ),
                CaseRow(
                    managed_company_id=company.id,
                    program_id=program.id,
                    assignee_name="기관 담당자",
                    stage="applying",
                    note="최신 상담",
                    updated_at=REFERENCE_TIME + timedelta(minutes=1),
                ),
            )
        )
    await db_session.commit()
    db_session.expunge_all()

    async with _statement_counter(db_session) as statements:
        entries = await list_companies(db_session)

    assert len(entries) == _ROW_COUNT
    assert {entry.profile_name for entry in entries} == {
        f"관리기업 {index}" for index in range(_ROW_COUNT)
    }
    assert {entry.case_stage for entry in entries} == {"applying"}
    assert len(statements) == 3, tuple(statements)


async def test_latest_matches_batches_populated_profiles_conditions_and_audits(
    db_session: AsyncSession,
) -> None:
    # Per-match profile, condition, rule, or audit reads make this grow with 50 matches.
    program = _program(400)
    db_session.add(program)
    await db_session.flush()
    rule = EligibilityRuleRow(
        program_id=program.id,
        kind="region",
        operator="in",
        expected_json='"KR-11"',
        required=True,
        review_status="automatic",
        rule_version="rules-v1",
    )
    db_session.add(rule)
    profiles = [
        ApplicantProfileRow(
            display_name=f"매치기업 {index}",
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
    assessments = [
        AssessmentRow(
            program_id=program.id,
            profile_id=profile.id,
            final_status="eligible",
            review_status="reviewed",
            rule_version="rules-v1",
            assessed_at=REFERENCE_TIME,
            review_revision=1,
        )
        for profile in profiles
    ]
    db_session.add_all(assessments)
    await db_session.flush()
    conditions = [
        RuleAssessmentRow(
            assessment_id=assessment.id,
            rule_id=rule.id,
            status="satisfied",
            explanation="comparison_satisfied",
            evidence_ids_json="[1]",
        )
        for assessment in assessments
    ]
    db_session.add_all(conditions)
    await db_session.flush()
    for assessment, condition in zip(assessments, conditions, strict=True):
        after_json = json.dumps(
            {
                "schema_version": 1,
                "assessment_id": assessment.id,
                "automatic_final_status": "eligible",
                "review_status": "reviewed",
                "effective_final_status": "eligible",
                "review_revision": 1,
                "reviewed_at": REFERENCE_TIME.isoformat(),
                "overrides": [],
                "automatic_conditions": [
                    {
                        "rule_assessment_id": condition.id,
                        "rule_id": rule.id,
                        "status": "satisfied",
                        "explanation": "comparison_satisfied",
                        "evidence_ids": [1],
                        "error_id": None,
                    }
                ],
            },
            separators=(",", ":"),
        )
        db_session.add(
            AuditEventRow(
                entity_type="assessment",
                entity_id=str(assessment.id),
                action="review",
                actor_name="검토자",
                reason="쿼리 회귀 검토",
                before_json=None,
                after_json=after_json,
                created_at=REFERENCE_TIME,
            )
        )
    await db_session.commit()
    db_session.expunge_all()

    async with _statement_counter(db_session) as statements:
        matches = await latest_matches(db_session, program.id)

    assert len(matches) == _ROW_COUNT
    assert {entry.reviewer for entry in matches} == {"검토자"}
    assert all(len(entry.conditions) == 1 for entry in matches)
    assert len(statements) == 4, tuple(statements)


async def test_reverse_matching_surfaces_dangling_evidence_as_finite_missing_evidence(
    db_session: AsyncSession,
) -> None:
    # A raw query-layer integrity exception would crash the complete reverse-matching run.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile = ApplicantProfileRow(
        display_name="손상 증거 기업",
        founded_on=date(2025, 1, 1),
        regions_json='["KR-11"]',
        representative_birth_year=1990,
        industries_json='["software"]',
        performance_json="{}",
        benefit_history_json="[]",
        created_at=REFERENCE_TIME,
    )
    db_session.add(profile)
    await db_session.flush()
    db_session.add(ManagedCompanyRow(profile_id=profile.id, owner_name="합성 대표", active=True))
    await db_session.commit()
    _ = await db_session.execute(text("PRAGMA foreign_keys=OFF"))
    _ = await db_session.execute(delete(DocumentBlockRow))
    await db_session.commit()
    _ = await db_session.execute(text("PRAGMA foreign_keys=ON"))
    await db_session.commit()

    results = await ReverseMatchingService(db_session).reverse_match(
        ProgramId(program.id), REFERENCE_TIME
    )

    assert len(results) == 1
    assert results[0].assessment is None
    assert results[0].input_error is not None
    assert results[0].input_error.code is CompanyInputErrorCode.MISSING_EVIDENCE
