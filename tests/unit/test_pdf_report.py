import json
from datetime import date
from pathlib import Path

import fitz
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.reports.pdf import ConsultationReportService, blocked_url_fetcher
from grantcompass.storage.table_cases import AuditEventRow, CaseRow, ManagedCompanyRow
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    RuleAssessmentRow,
)
from tests.integration.task12_fixtures import REFERENCE_TIME, seed_program, seed_rule

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def configured_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = (
        Path(__file__).parents[2] / ".tools" / "weasyprint-windows" / "dist" / "weasyprint.exe"
    )
    if executable.is_file():
        monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))
    else:
        monkeypatch.delenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", raising=False)


async def test_consultation_pdf_has_header_and_evidence_text(db_session: AsyncSession) -> None:
    # Given: a case linked to an automatic evidence-backed assessment.
    case_id = await _seed_report_case(db_session)
    service = ConsultationReportService(db_session)

    # When: the case is rendered through the secure WeasyPrint boundary.
    result = await service.render_consultation_pdf(case_id)

    # Then: the PDF remains searchable and contains the institutional evidence fields.
    assert result.startswith(b"%PDF")
    with fitz.open(stream=result, filetype="pdf") as document:
        extracted = "".join(page.get_text() for page in document)
    assert "공식 출처" in extracted
    assert "검토자" in extracted
    assert "수정 사유" in extracted
    assert "조건별 근거" in extracted
    assert "상담 단계" in extracted


async def test_consultation_pdf_escapes_source_markup(db_session: AsyncSession) -> None:
    # Given: source-controlled text containing markup and an external image URL.
    case_id = await _seed_report_case(
        db_session,
        company_name='<img src="https://attacker.invalid/pixel">위험기업',
    )

    # When: the consultation PDF is rendered.
    result = await ConsultationReportService(db_session).render_consultation_pdf(case_id)

    # Then: source markup is represented only as readable text, never fetched as a resource.
    with fitz.open(stream=result, filetype="pdf") as document:
        extracted = "".join(page.get_text() for page in document)
    assert "위험기업" in extracted
    assert "attacker.invalid" in extracted


async def test_pdf_url_fetcher_blocks_external_and_file_resources() -> None:
    # Given: external network and local-file resource locations.
    # When: WeasyPrint asks the hardened resource boundary to resolve them.
    with pytest.raises(ValueError, match="external_resource_blocked"):
        _ = blocked_url_fetcher("https://attacker.invalid/pixel")
    with pytest.raises(ValueError, match="external_resource_blocked"):
        _ = blocked_url_fetcher("file:///etc/passwd")

    # Then: no resolver response can disclose or retrieve either resource.


async def test_consultation_pdf_keeps_audit_text_inside_page(
    db_session: AsyncSession,
) -> None:
    # Given: an immutable audit event contains long unbroken canonical JSON.
    case_id = await _seed_report_case(db_session)
    db_session.add(
        AuditEventRow(
            entity_type="case",
            entity_id=str(case_id),
            action="transition",
            actor_name="검토자",
            reason="긴 감사 이력 검증",
            before_json=json.dumps({"state": "x" * 900}, separators=(",", ":")),
            after_json=json.dumps({"state": "y" * 900}, separators=(",", ":")),
            created_at=REFERENCE_TIME,
        )
    )
    await db_session.commit()

    # When: the report is rendered to its fixed A4 page geometry.
    result = await ConsultationReportService(db_session).render_consultation_pdf(case_id)

    # Then: every text span remains inside the document's right content margin.
    with fitz.open(stream=result, filetype="pdf") as document:
        for page in document:
            spans = (
                span
                for block in page.get_text("dict")["blocks"]
                if "lines" in block
                for line in block["lines"]
                for span in line["spans"]
            )
            assert all(span["bbox"][2] <= page.rect.x1 - 40 for span in spans)


async def _seed_report_case(
    session: AsyncSession,
    *,
    company_name: str = "합성기업",
) -> int:
    program = await seed_program(session)
    _ = await seed_rule(session, program)
    profile = ApplicantProfileRow(
        display_name=company_name,
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
    return case.id
