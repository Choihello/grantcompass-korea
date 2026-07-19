"""Immutable assessment review commands and effective views."""

from dataclasses import dataclass
from datetime import datetime
from typing import NewType

from grantcompass.domain.documents import EvidenceId
from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus, FinalStatus, ReviewStatus
from grantcompass.domain.ids import AssessmentId

RuleAssessmentId = NewType("RuleAssessmentId", int)


@dataclass(frozen=True, slots=True)
class ConditionOverride:
    """One attributed human status override for an assessed rule."""

    rule_assessment_id: RuleAssessmentId
    rule_id: EligibilityRuleId
    status: ConditionStatus


@dataclass(frozen=True, slots=True)
class AssessmentReviewCommand:
    """One immutable assessment verification or override request."""

    assessment_id: AssessmentId
    overrides: tuple[ConditionOverride, ...]
    actor: str
    reason: str
    reviewed_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewedCondition:
    """Automatic and effective states for one immutable condition result."""

    rule_assessment_id: RuleAssessmentId
    rule_id: EligibilityRuleId
    automatic_status: ConditionStatus
    override_status: ConditionStatus | None
    effective_status: ConditionStatus
    explanation: str
    evidence_ids: tuple[EvidenceId, ...]
    error_id: str | None


@dataclass(frozen=True, slots=True)
class AssessmentReview:
    """Attributed review view that preserves the original automatic result."""

    assessment_id: AssessmentId
    automatic_final_status: FinalStatus
    effective_final_status: FinalStatus
    review_status: ReviewStatus
    rule_version: str
    assessed_at: datetime
    reviewed_at: datetime
    overrides: tuple[ConditionOverride, ...]
    conditions: tuple[ReviewedCondition, ...]
