from html.parser import HTMLParser
from typing import final, override

import pytest
from sqlalchemy import func, select

from grantcompass.storage.audit_schemas import parse_assessment_audit_state
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import AssessmentRow
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow
from grantcompass.web.app import get_runtime
from tests.e2e.test_institution_web import InstitutionHarness, institution_client
from tests.integration.task12_fixtures import REFERENCE_TIME

pytestmark = pytest.mark.anyio
__all__ = ["institution_client"]


@final
class _ReviewMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.revision: dict[str, str | None] | None = None
        self.assessment_ids: list[str] = []
        self.text: list[str] = []

    @override
    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "input" and attributes.get("name") == "expected_review_revision":
            self.revision = attributes
        assessment_id = attributes.get("data-assessment-id") if tag == "tr" else None
        if assessment_id is not None:
            self.assessment_ids.append(assessment_id)

    @override
    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _parse_markup(markup: str) -> _ReviewMarkupParser:
    parser = _ReviewMarkupParser()
    parser.feed(markup)
    return parser


def _review_payload(*, second_status: str = "unsatisfied") -> dict[str, str]:
    return {
        "actor": "조건 검토자",
        "reason": "두 번째 조건 증빙 확인",
        "expected_review_revision": "0",
        "condition_status_1": "",
        "condition_status_2": second_status,
    }


async def test_non_first_condition_override_is_explicit_and_effective(
    institution_client: InstitutionHarness,
) -> None:
    # Given: the browser exposes both automatic condition identities and statuses.
    form = await institution_client.client.get("/programs/1")
    document = _parse_markup(form.text)
    assert 'name="condition_status_1"' in form.text
    assert 'name="condition_status_2"' in form.text
    assert document.revision is not None
    assert document.revision.get("type") == "hidden"
    assert document.revision.get("value") == "0"

    # When: the reviewer overrides only the second condition.
    response = await institution_client.client.post(
        "/assessments/1/review",
        data=_review_payload(),
    )

    # Then: the exact override is durable and effective without changing automation.
    assert response.status_code == 303, response.text
    runtime = get_runtime(institution_client.app)
    async with runtime.session_factory() as session:
        assessment = await session.get(AssessmentRow, 1)
        audit = (await session.scalars(select(AuditEventRow))).one()
    assert assessment is not None
    assert assessment.final_status == "eligible"
    assert audit.after_json is not None
    state = parse_assessment_audit_state(audit.after_json)
    assert tuple(
        (item.rule_assessment_id, item.rule_id, item.status) for item in state.overrides
    ) == ((2, 2, "unsatisfied"),)
    assert state.effective_final_status == "ineligible"
    case = await institution_client.client.get(response.headers["location"])
    assert "자동 종합 eligible" in case.text
    assert "유효 종합 ineligible" in case.text
    assert "satisfied → unsatisfied → unsatisfied" in case.text
    assert "조건 검토자" in case.text
    assert "두 번째 조건 증빙 확인" in case.text


async def test_stale_review_form_is_rejected_without_sibling_audit(
    institution_client: InstitutionHarness,
) -> None:
    # Given: two browser forms observed the same revision zero.
    left = _review_payload(second_status="conditional")
    right = _review_payload(second_status="unsatisfied")

    # When: the left form wins before the stale right form is submitted.
    winner = await institution_client.client.post("/assessments/1/review", data=left)
    stale = await institution_client.client.post("/assessments/1/review", data=right)

    # Then: repository CAS reports the conflict and appends no sibling event.
    assert winner.status_code == 303, winner.text
    assert stale.status_code == 409
    assert "concurrent_change" in stale.text
    runtime = get_runtime(institution_client.app)
    async with runtime.session_factory() as session:
        assessment = await session.get(AssessmentRow, 1)
        event_count = await session.scalar(select(func.count(AuditEventRow.id)))
    assert assessment is not None
    assert assessment.review_revision == 1
    assert event_count == 1


async def test_program_shows_only_latest_reverse_result_per_profile(
    institution_client: InstitutionHarness,
) -> None:
    # Given: the same managed profile already has one persisted assessment.
    payload = {"actor": "매칭 담당자", "reason": "최신 결과 확인"}

    # When: reverse matching runs twice more.
    first = await institution_client.client.post("/programs/1/reverse-match", data=payload)
    second = await institution_client.client.post("/programs/1/reverse-match", data=payload)
    detail = await institution_client.client.get("/programs/1")

    # Then: one deterministic latest row and action represent that profile.
    assert first.status_code == 303
    assert second.status_code == 303
    assert detail.text.count("합성기업") == 1
    runtime = get_runtime(institution_client.app)
    async with runtime.session_factory() as session:
        assessments = tuple(
            (
                await session.scalars(
                    select(AssessmentRow)
                    .where(AssessmentRow.profile_id == 1)
                    .order_by(AssessmentRow.assessed_at, AssessmentRow.id)
                )
            ).all()
        )
    assert tuple(item.id for item in assessments) == (1, 2, 3)
    document = _parse_markup(detail.text)
    assert document.assessment_ids == [str(assessments[-1].id)]


async def test_case_retains_review_history_from_older_assessments(
    institution_client: InstitutionHarness,
) -> None:
    # Given: the first assessment has a human override and attributed audit event.
    reviewed = await institution_client.client.post(
        "/assessments/1/review",
        data=_review_payload(),
    )
    assert reviewed.status_code == 303, reviewed.text

    # When: a newer automatic reverse-match assessment becomes current.
    matched = await institution_client.client.post(
        "/programs/1/reverse-match",
        data={"actor": "매칭 담당자", "reason": "새 자동 판정"},
    )
    case = await institution_client.client.get("/cases/1")

    # Then: current state is latest while the older immutable review remains visible.
    assert matched.status_code == 303
    assert "automatic" in case.text
    assert "조건 검토자" in case.text
    assert "두 번째 조건 증빙 확인" in case.text
    rendered_text = "".join(_parse_markup(case.text).text)
    assert '"rule_assessment_id":2' in rendered_text


async def test_program_times_are_rendered_in_seoul(
    institution_client: InstitutionHarness,
) -> None:
    # Given: the official source was collected at 09:00 UTC.
    # When: the program dossier renders the source ledger.
    detail = await institution_client.client.get("/programs/1")

    # Then: users see the exact configured Asia/Seoul representation.
    assert "2026-07-20 18:00 KST" in detail.text
    assert "2026-07-20 09:00:00" not in detail.text


async def test_attachments_render_only_under_their_notice_version(
    institution_client: InstitutionHarness,
) -> None:
    # Given: two current official sources have distinct attachments.
    runtime = get_runtime(institution_client.app)
    async with runtime.session_factory() as session:
        notice = NoticeVersionRow(
            program_id=1,
            source="bizinfo",
            source_notice_id="B-INSTITUTION-2",
            content_hash="c" * 64,
            detail_url="https://example.invalid/bizinfo",
            raw_payload_json="{}",
            normalized_json="{}",
            collected_at=REFERENCE_TIME,
        )
        session.add(notice)
        await session.flush()
        session.add_all(
            (
                CurrentNoticeVersionRow(
                    source=notice.source,
                    source_notice_id=notice.source_notice_id,
                    version_id=notice.id,
                ),
                AttachmentRow(
                    notice_version_id=notice.id,
                    filename="bizinfo.hwpx",
                    download_url="https://example.invalid/bizinfo.hwpx",
                    media_type="application/hwp+zip",
                    content_hash="d" * 64,
                    local_path=None,
                    parse_status="parsed",
                    parse_error_code=None,
                    requires_review=False,
                    parser_name="fixture",
                    parser_version="1",
                ),
            )
        )
        await session.commit()

    # When: the source ledger is rendered.
    detail = await institution_client.client.get("/programs/1")

    # Then: each row contains only its own notice-version attachments.
    kstartup = detail.text.index("kstartup")
    kstartup_row = detail.text[kstartup : detail.text.index("</tr>", kstartup)]
    bizinfo = detail.text.index("bizinfo")
    bizinfo_row = detail.text[bizinfo : detail.text.index("</tr>", bizinfo)]
    assert "rule.pdf" in kstartup_row
    assert "bizinfo.hwpx" not in kstartup_row
    assert "bizinfo.hwpx" in bizinfo_row
    assert "rule.pdf" not in bizinfo_row
