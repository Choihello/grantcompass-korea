"""Typed assessment-review validation and immutable audit state builders."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from pydantic import TypeAdapter, ValidationError

from grantcompass.domain.cases import AuditErrorCode, AuditValidationError
from grantcompass.domain.documents import EvidenceId
from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus, FinalStatus, ReviewStatus
from grantcompass.domain.ids import AssessmentId
from grantcompass.domain.json_types import FrozenJsonObject, freeze_json_object
from grantcompass.domain.reviews import (
    AssessmentReview,
    ConditionOverride,
    ReviewedCondition,
    RuleAssessmentId,
)
from grantcompass.rules.aggregate import aggregate_final_status
from grantcompass.storage.audit_json import aware_utc
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow

_EVIDENCE_IDS = TypeAdapter(tuple[int, ...])


@dataclass(frozen=True, slots=True)
class ReviewSource:
    """Validated automatic rows and attributed overrides for one review."""

    assessment: AssessmentRow
    conditions: tuple[RuleAssessmentRow, ...]
    override_by_id: Mapping[RuleAssessmentId, ConditionOverride]


@dataclass(frozen=True, slots=True)
class _SnapshotView:
    review: AssessmentReview
    status: ReviewStatus
    effective_final_status: FinalStatus
    overrides: tuple[ConditionOverride, ...]
    reviewed_at: datetime | None


def validate_review_overrides(
    assessment_id: AssessmentId,
    overrides: tuple[ConditionOverride, ...],
    persisted: Sequence[RuleAssessmentRow],
) -> dict[RuleAssessmentId, ConditionOverride]:
    """Reject empty, duplicate, unknown, foreign, or mismatched identities."""
    if any(int(item.rule_assessment_id) <= 0 or int(item.rule_id) <= 0 for item in overrides):
        raise AuditValidationError(AuditErrorCode.INVALID_OVERRIDE_IDENTITY)
    assessment_ids = tuple(item.rule_assessment_id for item in overrides)
    rule_ids = tuple(item.rule_id for item in overrides)
    if len(set(assessment_ids)) != len(assessment_ids) or len(set(rule_ids)) != len(rule_ids):
        raise AuditValidationError(AuditErrorCode.DUPLICATE_OVERRIDE)
    row_by_id = {RuleAssessmentId(row.id): row for row in persisted}
    validated: dict[RuleAssessmentId, ConditionOverride] = {}
    for item in overrides:
        row = row_by_id.get(item.rule_assessment_id)
        if row is None:
            raise AuditValidationError(AuditErrorCode.UNKNOWN_RULE_ASSESSMENT)
        if row.assessment_id != int(assessment_id) or row.rule_id != int(item.rule_id):
            raise AuditValidationError(AuditErrorCode.FOREIGN_RULE_ASSESSMENT)
        validated[item.rule_assessment_id] = item
    return validated


def build_assessment_review(source: ReviewSource, reviewed_at: datetime) -> AssessmentReview:
    """Build automatic and effective condition views without mutating stored rows."""
    if not source.conditions:
        raise AuditValidationError(AuditErrorCode.MALFORMED_ASSESSMENT)
    conditions = tuple(
        _reviewed_condition(row, source.override_by_id.get(RuleAssessmentId(row.id)))
        for row in source.conditions
    )
    automatic_final_status = parse_final_status(source.assessment.final_status)
    overrides = tuple(source.override_by_id[key] for key in sorted(source.override_by_id, key=int))
    return AssessmentReview(
        assessment_id=AssessmentId(source.assessment.id),
        automatic_final_status=automatic_final_status,
        effective_final_status=aggregate_final_status(
            tuple(item.effective_status for item in conditions)
        ),
        review_status=ReviewStatus.REVIEWED,
        rule_version=source.assessment.rule_version,
        assessed_at=aware_utc(source.assessment.assessed_at),
        reviewed_at=reviewed_at,
        overrides=overrides,
        conditions=conditions,
    )


def automatic_review_snapshot(
    review: AssessmentReview,
    original_status: ReviewStatus,
) -> FrozenJsonObject:
    """Build the first review's untouched automatic before-state."""
    automatic_conditions = tuple(
        replace(
            item,
            override_status=None,
            effective_status=item.automatic_status,
        )
        for item in review.conditions
    )
    automatic_review = replace(
        review,
        effective_final_status=review.automatic_final_status,
        overrides=(),
        conditions=automatic_conditions,
    )
    return _review_snapshot(
        _SnapshotView(
            automatic_review,
            original_status,
            automatic_review.automatic_final_status,
            (),
            None,
        )
    )


def completed_review_snapshot(review: AssessmentReview) -> FrozenJsonObject:
    """Build one completed review's actor-independent after-state."""
    return _review_snapshot(
        _SnapshotView(
            review,
            ReviewStatus.REVIEWED,
            review.effective_final_status,
            review.overrides,
            review.reviewed_at,
        )
    )


def parse_review_status(value: str) -> ReviewStatus:
    """Parse stored review progress into its finite enum."""
    try:
        return ReviewStatus(value)
    except ValueError:
        raise AuditValidationError(AuditErrorCode.MALFORMED_ASSESSMENT) from None


def parse_final_status(value: str) -> FinalStatus:
    """Parse stored automatic final status into its finite enum."""
    try:
        return FinalStatus(value)
    except ValueError:
        raise AuditValidationError(AuditErrorCode.MALFORMED_ASSESSMENT) from None


def _reviewed_condition(
    row: RuleAssessmentRow,
    override: ConditionOverride | None,
) -> ReviewedCondition:
    try:
        automatic = ConditionStatus(row.status)
        evidence_ids = tuple(
            EvidenceId(value) for value in _EVIDENCE_IDS.validate_json(row.evidence_ids_json)
        )
    except (ValueError, ValidationError):
        raise AuditValidationError(AuditErrorCode.MALFORMED_ASSESSMENT) from None
    return ReviewedCondition(
        rule_assessment_id=RuleAssessmentId(row.id),
        rule_id=EligibilityRuleId(row.rule_id),
        automatic_status=automatic,
        override_status=None if override is None else override.status,
        effective_status=automatic if override is None else override.status,
        explanation=row.explanation,
        evidence_ids=evidence_ids,
    )


def _review_snapshot(view: _SnapshotView) -> FrozenJsonObject:
    return freeze_json_object(
        {
            "schema_version": 1,
            "assessment_id": int(view.review.assessment_id),
            "automatic_final_status": view.review.automatic_final_status.value,
            "review_status": view.status.value,
            "effective_final_status": view.effective_final_status.value,
            "reviewed_at": None if view.reviewed_at is None else view.reviewed_at.isoformat(),
            "overrides": [
                {
                    "rule_assessment_id": int(item.rule_assessment_id),
                    "rule_id": int(item.rule_id),
                    "status": item.status.value,
                }
                for item in view.overrides
            ],
            "automatic_conditions": [
                {
                    "rule_assessment_id": int(item.rule_assessment_id),
                    "rule_id": int(item.rule_id),
                    "status": item.automatic_status.value,
                    "explanation": item.explanation,
                    "evidence_ids": [int(value) for value in item.evidence_ids],
                }
                for item in view.review.conditions
            ],
        }
    )
