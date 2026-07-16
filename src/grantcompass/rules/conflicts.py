"""Conservative promotion of contradictory official rule outcomes."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Final

from grantcompass.domain.eligibility import EligibilityRule, RuleAssessment
from grantcompass.domain.enums import ConditionStatus, RuleKind
from grantcompass.rules.evaluation_values import expected_codes, performance_expected

type RuleComparator = Callable[[EligibilityRule, EligibilityRule], bool]


def promote_conflicts(
    rules: Sequence[EligibilityRule],
    items: Sequence[RuleAssessment],
) -> tuple[RuleAssessment, ...]:
    """Promote only comparable required cross-source contradictions."""
    indexes: set[int] = set()
    for left_index, left_rule in enumerate(rules):
        for right_index in range(left_index + 1, len(rules)):
            right_rule = rules[right_index]
            if _contradicts(
                left_rule,
                items[left_index],
                right_rule,
                items[right_index],
            ):
                indexes.update((left_index, right_index))
    return tuple(
        replace(item, status=ConditionStatus.CONFLICT, explanation="source_conflict")
        if index in indexes
        else item
        for index, item in enumerate(items)
    )


def _contradicts(
    left_rule: EligibilityRule,
    left_item: RuleAssessment,
    right_rule: EligibilityRule,
    right_item: RuleAssessment,
) -> bool:
    statuses = {left_item.status, right_item.status}
    return (
        left_rule.required
        and right_rule.required
        and statuses == {ConditionStatus.SATISFIED, ConditionStatus.UNSATISFIED}
        and _distinct_sources(left_rule, right_rule)
        and _comparable(left_rule, right_rule)
    )


def _distinct_sources(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_sources = {(item.document_id, item.source_url) for item in left.evidence}
    right_sources = {(item.document_id, item.source_url) for item in right.evidence}
    return left_sources.isdisjoint(right_sources)


def _comparable(left: EligibilityRule, right: EligibilityRule) -> bool:
    return left.kind is right.kind and _COMPARATORS[left.kind](left, right)


def _always_comparable(left: EligibilityRule, right: EligibilityRule) -> bool:
    del left, right
    return True


def _never_comparable(left: EligibilityRule, right: EligibilityRule) -> bool:
    del left, right
    return False


def _same_performance_metric(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_expected = performance_expected(left.expected_value)
    right_expected = performance_expected(right.expected_value)
    return (
        left_expected is not None
        and right_expected is not None
        and left_expected[0] == right_expected[0]
    )


def _overlapping_codes(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_codes = expected_codes(left.expected_value)
    right_codes = expected_codes(right.expected_value)
    return (
        left_codes is not None
        and right_codes is not None
        and not left_codes.isdisjoint(right_codes)
    )


_COMPARATORS: Final[dict[RuleKind, RuleComparator]] = {
    RuleKind.BUSINESS_AGE_MONTHS: _always_comparable,
    RuleKind.REGION: _overlapping_codes,
    RuleKind.REPRESENTATIVE_AGE: _always_comparable,
    RuleKind.INDUSTRY: _overlapping_codes,
    RuleKind.PERFORMANCE: _same_performance_metric,
    RuleKind.DUPLICATE_BENEFIT: _overlapping_codes,
    RuleKind.NATURAL_LANGUAGE: _never_comparable,
}
