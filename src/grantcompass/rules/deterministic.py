"""Deterministic eligibility assessment orchestration."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, override

from grantcompass.domain.documents import EvidenceId
from grantcompass.domain.eligibility import (
    ApplicantProfile,
    ApplicantProfileId,
    AssessmentResult,
    EligibilityRule,
    EligibilityRuleId,
    RuleAssessment,
)
from grantcompass.domain.enums import (
    ConditionStatus,
    ReviewStatus,
    RuleKind,
)
from grantcompass.domain.ids import ProgramId
from grantcompass.rules.aggregate import aggregate_final_status
from grantcompass.rules.conflicts import promote_conflicts
from grantcompass.rules.evaluation_types import EvaluationOutcome, RuleEvaluator, unknown
from grantcompass.rules.evaluators import (
    BusinessAgeEvaluator,
    DuplicateBenefitEvaluator,
    IndustryEvaluator,
    PerformanceEvaluator,
    RegionEvaluator,
    RepresentativeAgeEvaluator,
    UnsupportedRuleEvaluator,
    completed_business_age_months,
    evaluate_business_age,
)

__all__ = [
    "AssessmentInputError",
    "AssessmentInputErrorCode",
    "DeterministicAssessmentEngine",
    "EvaluationOutcome",
    "completed_business_age_months",
    "evaluate_business_age",
]

type AssessmentInputErrorCode = Literal[
    "empty_rules",
    "missing_profile_id",
    "missing_rule_id",
    "missing_program_id",
    "missing_evidence_id",
    "mixed_programs",
    "mixed_rule_versions",
    "naive_assessed_at",
]

_EMPTY_RULES: Final[AssessmentInputErrorCode] = "empty_rules"
_MISSING_PROFILE_ID: Final[AssessmentInputErrorCode] = "missing_profile_id"
_MISSING_RULE_ID: Final[AssessmentInputErrorCode] = "missing_rule_id"
_MISSING_PROGRAM_ID: Final[AssessmentInputErrorCode] = "missing_program_id"
_MISSING_EVIDENCE_ID: Final[AssessmentInputErrorCode] = "missing_evidence_id"
_MIXED_PROGRAMS: Final[AssessmentInputErrorCode] = "mixed_programs"
_MIXED_RULE_VERSIONS: Final[AssessmentInputErrorCode] = "mixed_rule_versions"
_NAIVE_ASSESSED_AT: Final[AssessmentInputErrorCode] = "naive_assessed_at"


@dataclass(frozen=True, slots=True)
class AssessmentInputError(Exception):
    """Finite invalid assessment-boundary failure."""

    code: AssessmentInputErrorCode

    @override
    def __str__(self) -> str:
        """Return the stable machine-readable input code."""
        return self.code


@dataclass(frozen=True, slots=True)
class _ValidatedInput:
    profile_id: ApplicantProfileId
    program_id: ProgramId
    rule_version: str


class DeterministicAssessmentEngine:
    """Orchestrate evaluators with a mutable registry reserved for explicit injection."""

    def __init__(self) -> None:
        """Install the supported deterministic evaluator map."""
        self.evaluators: dict[RuleKind, RuleEvaluator] = {
            RuleKind.BUSINESS_AGE_MONTHS: BusinessAgeEvaluator(),
            RuleKind.REGION: RegionEvaluator(),
            RuleKind.REPRESENTATIVE_AGE: RepresentativeAgeEvaluator(),
            RuleKind.INDUSTRY: IndustryEvaluator(),
            RuleKind.PERFORMANCE: PerformanceEvaluator(),
            RuleKind.DUPLICATE_BENEFIT: DuplicateBenefitEvaluator(),
            RuleKind.NATURAL_LANGUAGE: UnsupportedRuleEvaluator(),
        }

    def assess(
        self,
        profile: ApplicantProfile,
        rules: Sequence[EligibilityRule],
        assessed_at: datetime,
    ) -> AssessmentResult:
        """Validate identities, evaluate every rule, and aggregate exact statuses."""
        validated = _validate_input(profile, rules, assessed_at)
        raw_items = tuple(self._evaluate(profile, rule, assessed_at) for rule in rules)
        items = promote_conflicts(rules, raw_items)
        final_status = aggregate_final_status(tuple(item.status for item in items))
        review_required = any(
            rule.review_status is ReviewStatus.REVIEW_REQUIRED for rule in rules
        ) or any(
            item.status in {ConditionStatus.UNKNOWN, ConditionStatus.CONFLICT} for item in items
        )
        return AssessmentResult(
            program_id=validated.program_id,
            profile_id=validated.profile_id,
            final_status=final_status,
            review_status=(
                ReviewStatus.REVIEW_REQUIRED if review_required else ReviewStatus.AUTOMATIC
            ),
            rule_version=validated.rule_version,
            assessed_at=assessed_at,
            items=items,
        )

    def _evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> RuleAssessment:
        try:
            outcome = self.evaluators[rule.kind].evaluate(profile, rule, assessed_at)
        except RuntimeError:
            outcome = unknown(f"evaluator_runtime_error:{rule.kind.value}")
        status = (
            ConditionStatus.CONDITIONAL
            if not rule.required and outcome.status is ConditionStatus.UNSATISFIED
            else outcome.status
        )
        return RuleAssessment(
            rule_id=_rule_id(rule),
            status=status,
            explanation=outcome.explanation,
            evidence_ids=tuple(_evidence_id(evidence.id) for evidence in rule.evidence),
            error_id=outcome.error_id,
        )


def _validate_input(
    profile: ApplicantProfile,
    rules: Sequence[EligibilityRule],
    assessed_at: datetime,
) -> _ValidatedInput:
    if profile.id is None:
        raise AssessmentInputError(_MISSING_PROFILE_ID)
    if assessed_at.utcoffset() is None:
        raise AssessmentInputError(_NAIVE_ASSESSED_AT)
    program_id, rule_version = _validate_rules(rules)
    return _ValidatedInput(profile.id, program_id, rule_version)


def _validate_rules(rules: Sequence[EligibilityRule]) -> tuple[ProgramId, str]:
    if not rules:
        raise AssessmentInputError(_EMPTY_RULES)
    for rule in rules:
        if rule.id is None:
            raise AssessmentInputError(_MISSING_RULE_ID)
        if rule.program_id is None:
            raise AssessmentInputError(_MISSING_PROGRAM_ID)
        if not rule.evidence or any(evidence.id is None for evidence in rule.evidence):
            raise AssessmentInputError(_MISSING_EVIDENCE_ID)
    program_ids = {rule.program_id for rule in rules}
    if len(program_ids) != 1:
        raise AssessmentInputError(_MIXED_PROGRAMS)
    versions = {rule.rule_version for rule in rules}
    if len(versions) != 1:
        raise AssessmentInputError(_MIXED_RULE_VERSIONS)
    program_id = rules[0].program_id
    if program_id is None:
        raise AssessmentInputError(_MISSING_PROGRAM_ID)
    return program_id, rules[0].rule_version


def _rule_id(rule: EligibilityRule) -> EligibilityRuleId:
    if rule.id is None:
        raise AssessmentInputError(_MISSING_RULE_ID)
    return rule.id


def _evidence_id(value: EvidenceId | None) -> EvidenceId:
    if value is None:
        raise AssessmentInputError(_MISSING_EVIDENCE_ID)
    return value
