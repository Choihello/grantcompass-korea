from dataclasses import dataclass
from io import BytesIO

import fitz
import pytest
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.pdfmetrics import registerFont
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus
from grantcompass.domain.ids import AssessmentId
from grantcompass.domain.reviews import AssessmentReviewCommand, ConditionOverride, RuleAssessmentId
from grantcompass.reports.pdf import ConsultationReportService
from grantcompass.storage.repositories import AssessmentRepository
from grantcompass.storage.table_eligibility import RuleAssessmentRow
from tests.e2e.institution_seed import seed_institution
from tests.integration.task12_fixtures import REFERENCE_TIME

pytestmark = pytest.mark.anyio


@dataclass(slots=True)
class _SearchableRenderer:
    markup: str | None = None

    async def render(self, markup: str) -> bytes:
        self.markup = markup
        stream = BytesIO()
        registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        canvas = Canvas(stream)
        canvas.setFont("HYSMyeongJo-Medium", 10)
        canvas.drawString(
            45,
            790,
            "공식 출처 PDF 검토자 PDF 수정 사유 자동 유효 unsatisfied",
        )
        canvas.save()
        return stream.getvalue()


async def test_consultation_output_is_a_searchable_evidence_pdf(db_session: AsyncSession) -> None:
    # Given: persisted source and a non-first human condition override.
    await seed_institution(db_session)
    rows = tuple(
        (
            await db_session.scalars(
                select(RuleAssessmentRow).where(RuleAssessmentRow.assessment_id == 1)
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
            AssessmentId(1),
            (override,),
            "PDF 검토자",
            "PDF 수정 사유",
            REFERENCE_TIME,
        )
    )

    # When: the service passes its real output through production PDF validation.
    renderer = _SearchableRenderer()
    service = ConsultationReportService(db_session, renderer=renderer)
    result = await service.render_consultation_pdf(1)

    # Then: the output opens, has pages, and preserves source/review/effective evidence text.
    assert result.startswith(b"%PDF")
    assert renderer.markup is not None
    assert "공식 출처" in renderer.markup
    assert "PDF 검토자" in renderer.markup
    with fitz.open(stream=result, filetype="pdf") as document:
        extracted = "".join(page.get_text() for page in document)
        assert document.page_count >= 1
    for expected in ("공식 출처", "PDF 검토자", "PDF 수정 사유", "자동", "unsatisfied", "유효"):
        assert expected in extracted
