"""Semantic validation for the latest immutable institutional audit state."""

from grantcompass.domain.cases import AuditErrorCode, AuditValidationError
from grantcompass.domain.enums import CaseStage, ReviewStatus
from grantcompass.domain.reviews import AssessmentReview
from grantcompass.storage.audit_json import aware_utc
from grantcompass.storage.audit_schemas import (
    AssessmentAuditState,
    AssessmentConditionState,
    CaseAuditState,
)
from grantcompass.storage.table_cases import CaseRow


def validate_assessment_after_state(
    state: AssessmentAuditState,
    review: AssessmentReview,
    current_status: ReviewStatus,
    current_revision: int,
) -> None:
    """Reject prior review state that disagrees with immutable automatic rows."""
    expected_conditions = tuple(
        AssessmentConditionState(
            rule_assessment_id=int(item.rule_assessment_id),
            rule_id=int(item.rule_id),
            status=item.automatic_status.value,
            explanation=item.explanation,
            evidence_ids=tuple(int(value) for value in item.evidence_ids),
            error_id=item.error_id,
        )
        for item in review.conditions
    )
    if (
        state.assessment_id != int(review.assessment_id)
        or state.automatic_final_status != review.automatic_final_status.value
        or state.review_status != current_status.value
        or state.review_revision != current_revision
        or state.automatic_conditions != expected_conditions
    ):
        raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT)


def validate_case_after_state(
    state: CaseAuditState,
    row: CaseRow,
    stage: CaseStage,
) -> None:
    """Reject prior case state that disagrees with the current case row."""
    expected_updated_at = aware_utc(row.updated_at)
    if (
        state.entity_id != row.id
        or state.stage != stage.value
        or state.assignee_name != row.assignee_name
        or state.note != row.note
        or state.updated_at != expected_updated_at.isoformat()
    ):
        raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT)
