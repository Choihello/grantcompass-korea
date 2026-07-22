import re
from dataclasses import dataclass
from html import unescape
from io import BytesIO

import fitz
import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
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
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))  # pyright: ignore[reportUnknownMemberType]
        canvas = Canvas(stream)
        canvas.setFont("HYSMyeongJo-Medium", 10)
        text = "공식 출처 PDF 검토자 PDF 수정 사유 자동 유효 unsatisfied " + re.sub(
            r"<[^>]+>", " ", unescape(markup)
        )
        cursor = canvas.beginText(45, 790)
        cursor.setFont("HYSMyeongJo-Medium", 10)
        for index in range(0, len(text), 70):
            line = text[index : index + 70]
            cursor.textLine(line)
            if cursor.getY() < 45:
                canvas.drawText(cursor)
                canvas.showPage()
                cursor = canvas.beginText(45, 790)
                cursor.setFont("HYSMyeongJo-Medium", 10)
        canvas.drawText(cursor)
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
