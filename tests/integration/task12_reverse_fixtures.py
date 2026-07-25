from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.storage.table_cases import ManagedCompanyRow
from grantcompass.storage.table_documents import EvidenceRow, rule_evidence
from grantcompass.storage.table_eligibility import ApplicantProfileRow, EligibilityRuleRow
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import NoticeVersionRow, ProgramRow
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_program, seed_rule


async def seed_reverse_matrix(session: AsyncSession) -> ProgramRow:
    program = await seed_program(session)
    _ = await seed_rule(session, program)
    first_evidence_id = (
        await session.scalars(select(EvidenceRow.id).order_by(EvidenceRow.id))
    ).one()
    industry_rule = EligibilityRuleRow(
        program_id=program.id,
        kind="industry",
        operator="in",
        expected_json='"software"',
        required=False,
        review_status="automatic",
        rule_version="rules-v1",
    )
    session.add(industry_rule)
    await session.flush()
    _ = await session.execute(
        rule_evidence.insert().values(
            rule_id=industry_rule.id,
            evidence_id=first_evidence_id,
        )
    )
    second_notice = NoticeVersionRow(
        program_id=program.id,
        source="bizinfo",
        source_notice_id="B-INSTITUTION-1",
        content_hash="c" * 64,
        detail_url="https://example.invalid/bizinfo/institutional",
        raw_payload_json="{}",
        normalized_json="{}",
        collected_at=REFERENCE_TIME,
        announcement_date=REFERENCE_TIME.date(),
        reference_date=REFERENCE_TIME.date(),
        reference_date_source="announcement_date",
    )
    session.add(second_notice)
    await session.flush()
    session.add(
        CurrentNoticeVersionRow(
            source=second_notice.source,
            source_notice_id=second_notice.source_notice_id,
            version_id=second_notice.id,
        )
    )
    profiles = (
        _profile("조건기업", '["KR-11"]', '["hardware"]'),
        _profile("확인기업", "[]", '["software"]'),
        _profile("적격기업A", '["KR-11"]', '["software"]'),
        _profile("오류기업", "{", '["software"]'),
        _profile("부적격기업", '["KR-26"]', '["software"]'),
        _profile("적격기업B", '["KR-11"]', '["software"]'),
    )
    session.add_all(profiles)
    await session.flush()
    session.add_all(
        (
            _managed(2, profiles[0], active=False),
            _managed(4, profiles[1], active=True),
            _managed(9, profiles[2], active=False),
            _managed(12, profiles[3], active=True),
            _managed(30, profiles[4], active=True),
            _managed(40, profiles[5], active=True),
        )
    )
    await session.commit()
    return program


def _profile(name: str, regions_json: str, industries_json: str) -> ApplicantProfileRow:
    return ApplicantProfileRow(
        display_name=name,
        founded_on=date(2025, 1, 1),
        regions_json=regions_json,
        representative_birth_year=1990,
        industries_json=industries_json,
        performance_json="{}",
        benefit_history_json="[]",
        created_at=REFERENCE_TIME,
    )


def _managed(
    managed_id: int,
    profile: ApplicantProfileRow,
    *,
    active: bool,
) -> ManagedCompanyRow:
    return ManagedCompanyRow(
        id=managed_id,
        profile_id=profile.id,
        owner_name=f"owner-{managed_id}",
        active=active,
    )
