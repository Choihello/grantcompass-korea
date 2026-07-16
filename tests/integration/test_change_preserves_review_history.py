from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import FinalStatus, ReviewStatus, SourceName
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    EligibilityRuleRow,
    RuleAssessmentRow,
)
from grantcompass.storage.table_notice_analysis import (
    AssessmentReviewNoteRow,
    ChangeImpactRow,
)
from tests.factories import NoticeValues, make_notice


@pytest.mark.anyio
async def test_notice_change_preserves_rule_result_review_note_and_audit(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    now: datetime,
) -> None:
    # Given: one reviewed automatic result with rule output, human note, and audit event.
    stored = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-PRESERVE"), now
    )
    profile = ApplicantProfileRow(
        display_name="가상 보존 기업",
        founded_on=None,
        regions_json="[]",
        representative_birth_year=None,
        industries_json="[]",
        performance_json="{}",
        benefit_history_json="[]",
        created_at=now,
    )
    rule = EligibilityRuleRow(
        program_id=stored.program_id,
        kind="region",
        operator="in",
        expected_json='["가상지역"]',
        required=True,
        review_status=ReviewStatus.REVIEWED.value,
        rule_version="rules-preserve",
    )
    db_session.add_all((profile, rule))
    await db_session.flush()
    assessment = AssessmentRow(
        program_id=stored.program_id,
        profile_id=profile.id,
        final_status=FinalStatus.ELIGIBLE.value,
        review_status=ReviewStatus.REVIEWED.value,
        rule_version="rules-preserve",
        assessed_at=now,
    )
    db_session.add(assessment)
    await db_session.flush()
    rule_result = RuleAssessmentRow(
        assessment_id=assessment.id,
        rule_id=rule.id,
        status="satisfied",
        explanation="가상지역 소재 확인",
        evidence_ids_json="[11]",
    )
    note = AssessmentReviewNoteRow(
        assessment_id=assessment.id,
        reviewer_name="가상 담당자",
        note="증빙 원문을 사람이 확인함",
        created_at=now,
    )
    audit = AuditEventRow(
        entity_type="assessment",
        entity_id=str(assessment.id),
        action="reviewed",
        actor_name="가상 담당자",
        reason="사람 검토 완료",
        before_json='{"review_status":"automatic"}',
        after_json='{"review_status":"reviewed"}',
        created_at=now,
    )
    db_session.add_all((rule_result, note, audit))
    await db_session.commit()
    await db_session.refresh(assessment)
    await db_session.refresh(rule_result)
    await db_session.refresh(note)
    await db_session.refresh(audit)
    assessment_before = _assessment_content(assessment)
    rule_before = _rule_result_content(rule_result)
    note_before = _note_content(note)
    audit_before = _audit_content(audit)
    await db_session.rollback()
    changed = make_notice(
        SourceName.KSTARTUP,
        "K-PRESERVE",
        replace(NoticeValues(), summary="가상 자격조건 변경"),
    )

    # When: the current notice content changes.
    result = await program_repository.upsert_notice(changed, now + timedelta(hours=1))

    # Then: only review status and the new impact change; all review history is identical.
    await db_session.refresh(assessment)
    await db_session.refresh(rule_result)
    await db_session.refresh(note)
    await db_session.refresh(audit)
    impact_count = await db_session.scalar(
        select(func.count(ChangeImpactRow.assessment_id)).where(
            ChangeImpactRow.assessment_id == assessment.id
        )
    )
    assert result.impacted_assessment_ids == (assessment.id,)
    assert assessment.review_status == ReviewStatus.REVIEW_REQUIRED.value
    assert _assessment_content(assessment) == assessment_before
    assert _rule_result_content(rule_result) == rule_before
    assert _note_content(note) == note_before
    assert _audit_content(audit) == audit_before
    assert impact_count == 1


def _assessment_content(row: AssessmentRow) -> tuple[int, int, str, str, datetime]:
    return row.program_id, row.profile_id, row.final_status, row.rule_version, row.assessed_at


def _rule_result_content(row: RuleAssessmentRow) -> tuple[int, int, str, str, str]:
    return row.assessment_id, row.rule_id, row.status, row.explanation, row.evidence_ids_json


def _note_content(row: AssessmentReviewNoteRow) -> tuple[int, str, str, datetime]:
    return row.assessment_id, row.reviewer_name, row.note, row.created_at


def _audit_content(row: AuditEventRow) -> tuple[str, str, str, str, str, str | None, str | None]:
    return (
        row.entity_type,
        row.entity_id,
        row.action,
        row.actor_name,
        row.reason,
        row.before_json,
        row.after_json,
    )
