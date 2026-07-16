"""Typed outcomes and contracts for pure rule evaluators."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from grantcompass.domain.eligibility import ApplicantProfile, EligibilityRule
from grantcompass.domain.enums import ConditionStatus


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    """One pure evaluator outcome before orchestration policy."""

    status: ConditionStatus
    explanation: str
    error_id: str | None = None


class RuleEvaluator(Protocol):
    """Structural contract implemented by deterministic evaluators."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Evaluate one typed profile fact against one normalized rule."""
        ...


def satisfied(*, value: bool) -> EvaluationOutcome:
    """Return the stable satisfied or unsatisfied outcome."""
    if value:
        return EvaluationOutcome(ConditionStatus.SATISFIED, "comparison_satisfied")
    return EvaluationOutcome(ConditionStatus.UNSATISFIED, "comparison_unsatisfied")


def unknown(error_id: str) -> EvaluationOutcome:
    """Return a stable visible unknown outcome."""
    return EvaluationOutcome(ConditionStatus.UNKNOWN, error_id, error_id)
