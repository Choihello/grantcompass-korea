from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import grantcompass.reports.pdf as pdf_module
from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus
from grantcompass.domain.ids import AssessmentId
from grantcompass.domain.reviews import (
    AssessmentReviewCommand,
    ConditionOverride,
    RuleAssessmentId,
)
from grantcompass.reports.pdf import ConsultationReportService
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_eligibility import ApplicantProfileRow, RuleAssessmentRow
from tests.e2e.institution_seed import seed_institution
from tests.integration.task12_fixtures import REFERENCE_TIME

pytestmark = pytest.mark.anyio


@dataclass(slots=True)
class ControlledRenderer:
    markup: str | None = None
    calls: int = 0

    async def render(self, markup: str) -> bytes:
        self.markup = markup
        self.calls += 1
        return b"%PDF-controlled"


async def test_consultation_pdf_uses_controlled_renderer_without_local_binary(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: canonical report data and no configured ignored-host executable.
    await seed_institution(db_session)
    monkeypatch.delenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", raising=False)
    renderer = ControlledRenderer()

    # When: the report renders through its injected deterministic boundary.
    service = ConsultationReportService(db_session, renderer=renderer)
    result = await service.render_consultation_pdf(1)

    # Then: the same searchable report markup reaches that boundary exactly once.
    assert result == b"%PDF-controlled"
    assert renderer.calls == 1
    assert renderer.markup is not None
    assert "공식 출처" in renderer.markup
    assert "조건별 근거" in renderer.markup
    assert "상담 단계" in renderer.markup


async def test_non_first_override_appears_in_pdf_effective_output(
    db_session: AsyncSession,
) -> None:
    # Given: only the second automatic condition is explicitly overridden.
    await seed_institution(db_session)
    rows = tuple(
        (
            await db_session.scalars(
                select(RuleAssessmentRow)
                .where(RuleAssessmentRow.assessment_id == 1)
                .order_by(RuleAssessmentRow.id)
            )
        ).all()
    )
    override = ConditionOverride(
        RuleAssessmentId(rows[1].id),
        EligibilityRuleId(rows[1].rule_id),
        ConditionStatus.UNSATISFIED,
    )
    await db_session.commit()
    _ = await AssessmentRepository(db_session).review(
        AssessmentReviewCommand(
            assessment_id=AssessmentId(1),
            overrides=(override,),
            actor="PDF 검토자",
            reason="두 번째 조건 PDF 검증",
            reviewed_at=REFERENCE_TIME,
            expected_review_revision=0,
        )
    )
    renderer = ControlledRenderer()

    # When: consultation output is rendered from the shared canonical data.
    _ = await ConsultationReportService(db_session, renderer=renderer).render_consultation_pdf(1)

    # Then: automatic, override, effective, aggregate, reviewer, and reason stay distinct.
    assert renderer.markup is not None
    assert "자동 종합" in renderer.markup
    assert "eligible" in renderer.markup
    assert "유효 종합" in renderer.markup
    assert "ineligible" in renderer.markup
    assert "satisfied" in renderer.markup
    assert "unsatisfied" in renderer.markup
    assert "PDF 검토자" in renderer.markup
    assert "두 번째 조건 PDF 검증" in renderer.markup


@pytest.mark.parametrize(
    "markup",
    [
        '<img src="https://attacker.invalid/pixel">',
        '<object data="file:///etc/passwd"></object>',
        '<img srcset="https://attacker.invalid/a 1x">',
        '<svg><use xlink:href="https://attacker.invalid/icon"></use></svg>',
        '<video poster="https://attacker.invalid/poster"></video>',
        '<style>@import "https://attacker.invalid/x.css";</style>',
        "<style>body{background:url(file:///etc/passwd)}</style>",
        "<style>@font-face{font-family:x;src:url(https://attacker.invalid/x)}</style>",
    ],
)
async def test_secure_render_boundary_rejects_resource_markup(markup: str) -> None:
    # Given: untrusted HTML attempts a resource-bearing render operation.
    renderer = ControlledRenderer()

    # When: it crosses the actual secure render boundary.
    with pytest.raises(ValueError, match="external_resource_markup_blocked"):
        _ = await pdf_module.render_secure_pdf(markup, renderer)

    # Then: no renderer call can reach network, files, fonts, images, or media.
    assert renderer.calls == 0


async def test_escaped_hostile_source_text_remains_printable(
    db_session: AsyncSession,
) -> None:
    # Given: a persisted company name resembles a network-bearing image element.
    await seed_institution(db_session)
    profile = await db_session.get(ApplicantProfileRow, 1)
    assert profile is not None
    profile.display_name = '<img src="https://attacker.invalid/pixel">위험기업'
    await db_session.commit()
    renderer = ControlledRenderer()

    # When: normal template autoescaping precedes secure rendering.
    _ = await ConsultationReportService(db_session, renderer=renderer).render_consultation_pdf(1)

    # Then: the text remains printable but no resource element is emitted.
    assert renderer.markup is not None
    assert "위험기업" in renderer.markup
    assert "&lt;img" in renderer.markup
    assert '<img src="https://attacker.invalid/pixel">' not in renderer.markup


async def test_pdf_audit_style_keeps_unbroken_json_inside_page(
    db_session: AsyncSession,
) -> None:
    # Given: the report template includes immutable audit JSON.
    await seed_institution(db_session)
    renderer = ControlledRenderer()

    # When: the template is passed to the controlled renderer.
    _ = await ConsultationReportService(db_session, renderer=renderer).render_consultation_pdf(1)

    # Then: print CSS retains the measured long-token wrapping rule.
    assert renderer.markup is not None
    assert "word-break: break-all" in renderer.markup
