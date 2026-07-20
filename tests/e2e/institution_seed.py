"""Canonical institution workspace seed for HTTP acceptance tests."""

import json
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.storage.table_cases import CaseRow, ManagedCompanyRow
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    RuleAssessmentRow,
)
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_program, seed_rule


async def seed_institution(session: AsyncSession) -> None:
    """Seed one evidence-backed program, company, assessment, and case."""
    program = await seed_program(session)
    _ = await seed_rule(session, program)
    profile = ApplicantProfileRow(
        display_name="합성기업",
        founded_on=date(2025, 1, 1),
        regions_json='["KR-11"]',
        representative_birth_year=1990,
        industries_json='["software"]',
        performance_json="{}",
        benefit_history_json="[]",
        created_at=REFERENCE_TIME,
    )
    session.add(profile)
    await session.flush()
    managed = ManagedCompanyRow(profile_id=profile.id, owner_name="대표자", active=True)
    session.add(managed)
    await session.flush()
    assessment = AssessmentRow(
        program_id=program.id,
        profile_id=profile.id,
        final_status="eligible",
        review_status="automatic",
        rule_version="rules-v1",
        assessed_at=REFERENCE_TIME,
    )
    session.add(assessment)
    await session.flush()
    session.add(
        RuleAssessmentRow(
            assessment_id=assessment.id,
            rule_id=1,
            status="satisfied",
            explanation="comparison_satisfied",
            evidence_ids_json=json.dumps((1,), separators=(",", ":")),
        )
    )
    session.add(
        CaseRow(
            managed_company_id=managed.id,
            program_id=program.id,
            assignee_name="기관 담당자",
            stage="recommended",
            note="초기 상담",
            updated_at=datetime(2026, 7, 20, 9, tzinfo=UTC),
        )
    )
    await session.commit()


__all__ = ["seed_institution"]
