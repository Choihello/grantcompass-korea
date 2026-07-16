"""Pure deterministic evaluators for supported applicant facts."""

from calendar import monthrange
from datetime import UTC, date, datetime

from grantcompass.domain.eligibility import ApplicantProfile, EligibilityRule
from grantcompass.domain.enums import ConditionStatus
from grantcompass.rules.evaluation_types import EvaluationOutcome, satisfied, unknown
from grantcompass.rules.evaluation_values import (
    expected_codes,
    normalized_code,
    numeric_comparison,
    numeric_value,
    performance_expected,
)

_SET_OPERATORS = frozenset({"in", "not_in"})


def completed_business_age_months(founded_on: date, assessed_at: datetime) -> int:
    """Return completed calendar months using a clamped monthly anniversary."""
    reference = assessed_at.astimezone(UTC).date()
    months = (reference.year - founded_on.year) * 12 + reference.month - founded_on.month
    anniversary_year = founded_on.year + (founded_on.month - 1 + months) // 12
    anniversary_month = (founded_on.month - 1 + months) % 12 + 1
    anniversary = date(
        anniversary_year,
        anniversary_month,
        min(founded_on.day, monthrange(anniversary_year, anniversary_month)[1]),
    )
    return months - 1 if reference < anniversary else months


def evaluate_business_age(
    months: int,
    operator: str,
    limit: int,
) -> ConditionStatus:
    """Evaluate completed business months with one supported numeric operator."""
    outcome = numeric_comparison(months, operator, limit)
    return outcome.status


class BusinessAgeEvaluator:
    """Evaluate completed calendar months since founding."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Evaluate the profile's completed business months."""
        if profile.founded_on is None:
            return unknown("missing_profile_fact")
        expected = numeric_value(rule.expected_value)
        if expected is None:
            return unknown("malformed_expected_value")
        months = completed_business_age_months(profile.founded_on, assessed_at)
        if months < 0:
            return unknown("malformed_profile_fact")
        return numeric_comparison(months, rule.operator, expected)


class RepresentativeAgeEvaluator:
    """Evaluate representative age from the reference calendar year."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Evaluate age from the UTC reference year."""
        if profile.representative_birth_year is None:
            return unknown("missing_profile_fact")
        expected = numeric_value(rule.expected_value)
        if expected is None:
            return unknown("malformed_expected_value")
        age = assessed_at.astimezone(UTC).year - profile.representative_birth_year
        if age < 0:
            return unknown("malformed_profile_fact")
        return numeric_comparison(age, rule.operator, expected)


class RegionEvaluator:
    """Evaluate normalized region code membership."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Evaluate the profile's normalized region codes."""
        del assessed_at
        return _evaluate_code_set(profile.regions, rule)


class IndustryEvaluator:
    """Evaluate normalized industry code membership."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Evaluate the profile's normalized industry codes."""
        del assessed_at
        return _evaluate_code_set(profile.industries, rule)


class PerformanceEvaluator:
    """Evaluate a numeric metric from `performance[metric_key]`."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Evaluate the declared numeric performance metric schema."""
        del assessed_at
        expected = performance_expected(rule.expected_value)
        if expected is None:
            return unknown("malformed_expected_value")
        metric, threshold = expected
        if not profile.performance:
            return unknown("missing_profile_fact")
        raw_value = profile.performance.get(metric)
        if raw_value is None:
            return unknown("missing_profile_fact")
        value = numeric_value(raw_value)
        if value is None:
            return unknown("malformed_profile_fact")
        return numeric_comparison(value, rule.operator, threshold)


class DuplicateBenefitEvaluator:
    """Evaluate membership in `benefit_history[*].program_id`."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Evaluate the declared benefit-history program-ID schema."""
        del assessed_at
        expected = expected_codes(rule.expected_value)
        if expected is None:
            return unknown("malformed_expected_value")
        if rule.operator not in _SET_OPERATORS:
            return unknown("unsupported_operator")
        if not profile.benefit_history:
            return unknown("missing_profile_fact")
        program_ids: set[str] = set()
        for item in profile.benefit_history:
            program_id = item.get("program_id")
            if not isinstance(program_id, str) or not program_id.strip():
                return unknown("malformed_profile_fact")
            program_ids.add(normalized_code(program_id))
        overlap = bool(program_ids.intersection(expected))
        return satisfied(value=overlap if rule.operator == "in" else not overlap)


class UnsupportedRuleEvaluator:
    """Keep unsupported natural-language conditions visible."""

    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        """Return a visible unsupported-kind outcome."""
        del profile, rule, assessed_at
        return unknown("unsupported_rule_kind")


def _evaluate_code_set(
    facts: tuple[str, ...],
    rule: EligibilityRule,
) -> EvaluationOutcome:
    if not facts:
        return unknown("missing_profile_fact")
    expected = expected_codes(rule.expected_value)
    if expected is None:
        return unknown("malformed_expected_value")
    if rule.operator not in _SET_OPERATORS:
        return unknown("unsupported_operator")
    overlap = bool({normalized_code(value) for value in facts}.intersection(expected))
    return satisfied(value=overlap if rule.operator == "in" else not overlap)
