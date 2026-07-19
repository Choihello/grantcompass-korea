import json
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.storage.table_cases import CaseRow, ManagedCompanyRow
from grantcompass.storage.table_documents import (
    DocumentBlockRow,
    DocumentRow,
    EvidenceRow,
    rule_evidence,
)
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    EligibilityRuleRow,
    RuleAssessmentRow,
)
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, ProgramRow

REFERENCE_TIME = datetime(2026, 7, 20, 9, tzinfo=UTC)


async def seed_program(session: AsyncSession) -> ProgramRow:
    program = ProgramRow(
        canonical_key="institutional-program",
        title="합성 기관 지원사업",
        organization="합성 지원기관",
        application_start=date(2026, 7, 1),
        application_end=date(2026, 8, 31),
        created_at=REFERENCE_TIME,
        updated_at=REFERENCE_TIME,
    )
    session.add(program)
    await session.flush()
    notice = NoticeVersionRow(
        program_id=program.id,
        source="kstartup",
        source_notice_id="K-INSTITUTION-1",
        content_hash="a" * 64,
        detail_url="https://example.invalid/institutional",
        raw_payload_json="{}",
        normalized_json="{}",
        collected_at=REFERENCE_TIME,
    )
    session.add(notice)
    await session.flush()
    session.add(
        CurrentNoticeVersionRow(
            source=notice.source,
            source_notice_id=notice.source_notice_id,
            version_id=notice.id,
        )
    )
    await session.flush()
    return program


async def seed_profile(session: AsyncSession, name: str = "합성기업") -> ApplicantProfileRow:
    profile = ApplicantProfileRow(
        display_name=name,
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
    return profile


async def seed_rule(session: AsyncSession, program: ProgramRow) -> EligibilityRuleRow:
    notice = (
        await session.scalars(
            select(NoticeVersionRow).where(NoticeVersionRow.program_id == program.id)
        )
    ).one()
    attachment = AttachmentRow(
        notice_version_id=notice.id,
        filename="rule.pdf",
        download_url="https://example.invalid/rule.pdf",
        media_type="application/pdf",
        content_hash="b" * 64,
        local_path=None,
        parse_status="parsed",
        parse_error_code=None,
        requires_review=False,
        parser_name="fixture",
        parser_version="1",
    )
    session.add(attachment)
    await session.flush()
    document = DocumentRow(
        attachment_id=attachment.id,
        parser_name="fixture",
        parser_version="1",
        content_hash="b" * 64,
        parsed_at=REFERENCE_TIME,
        warning_json="[]",
    )
    session.add(document)
    await session.flush()
    block = DocumentBlockRow(
        document_id=document.id,
        ordinal=0,
        kind="paragraph",
        text="KR-11",
        page=1,
        section_path="eligibility",
        table_ref=None,
        source_block_id="p1",
        bbox_json=None,
        confidence=None,
        provenance="pdf_text",
    )
    session.add(block)
    await session.flush()
    evidence = EvidenceRow(
        document_id=document.id,
        block_id=block.id,
        source_url="https://example.invalid/institutional",
        page=1,
        section_path="eligibility",
        quote="KR-11",
        content_hash="b" * 64,
    )
    rule = EligibilityRuleRow(
        program_id=program.id,
        kind="region",
        operator="in",
        expected_json='"KR-11"',
        required=True,
        review_status="automatic",
        rule_version="rules-v1",
    )
    session.add_all((evidence, rule))
    await session.flush()
    _ = await session.execute(
        rule_evidence.insert().values(rule_id=rule.id, evidence_id=evidence.id)
    )
    return rule


async def seed_managed_company(
    session: AsyncSession,
    profile: ApplicantProfileRow,
) -> ManagedCompanyRow:
    managed = ManagedCompanyRow(profile_id=profile.id, owner_name="담당 창업자", active=True)
    session.add(managed)
    await session.flush()
    return managed


async def seed_case(session: AsyncSession) -> CaseRow:
    program = await seed_program(session)
    profile = await seed_profile(session)
    managed = await seed_managed_company(session, profile)
    case = CaseRow(
        managed_company_id=managed.id,
        program_id=program.id,
        assignee_name="기관 담당자",
        stage="recommended",
        note="초기 상담",
        updated_at=REFERENCE_TIME,
    )
    session.add(case)
    await session.commit()
    return case


async def seed_assessment(session: AsyncSession) -> AssessmentId:
    program = await seed_program(session)
    profile = await seed_profile(session)
    rule = await seed_rule(session, program)
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
            rule_id=rule.id,
            status="satisfied",
            explanation="comparison_satisfied",
            evidence_ids_json=json.dumps((1,), separators=(",", ":")),
        )
    )
    await session.commit()
    return AssessmentId(assessment.id)


def program_id(row: ProgramRow) -> ProgramId:
    return ProgramId(row.id)
