"""Conservative promotion of contradictory official rule outcomes."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final, Literal

from grantcompass.domain.eligibility import EligibilityRule, RuleAssessment
from grantcompass.domain.enums import ConditionStatus, RuleKind
from grantcompass.rules.evaluation_values import expected_codes, performance_expected
from grantcompass.rules.source_urls import canonical_http_url as _canonical_url

type NumericDirection = Literal["lower", "upper"]

_AGE_RULE_KINDS: Final = frozenset({RuleKind.BUSINESS_AGE_MONTHS, RuleKind.REPRESENTATIVE_AGE})
_NUMERIC_RULE_KINDS: Final = _AGE_RULE_KINDS | {RuleKind.PERFORMANCE}
_SET_RULE_KINDS: Final = frozenset({RuleKind.REGION, RuleKind.INDUSTRY, RuleKind.DUPLICATE_BENEFIT})


@dataclass(frozen=True, slots=True)
class ConflictGroupKey:
    """Typed semantic group whose rules may represent competing constraints."""

    kind: RuleKind
    direction: NumericDirection | None = None
    metric_key: str | None = None


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
    left_documents = {item.document_id for item in left.evidence}
    right_documents = {item.document_id for item in right.evidence}
    left_urls = _canonical_urls(left)
    right_urls = _canonical_urls(right)
    return (
        left_documents.isdisjoint(right_documents)
        and left_urls is not None
        and right_urls is not None
        and left_urls.isdisjoint(right_urls)
    )


def _comparable(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_group = _conflict_group(left)
    right_group = _conflict_group(right)
    if left_group is None or left_group != right_group:
        return False
    if left_group.kind in _NUMERIC_RULE_KINDS:
        return True
    if left_group.kind in _SET_RULE_KINDS:
        return _overlapping_codes(left, right)
    return False


def _conflict_group(rule: EligibilityRule) -> ConflictGroupKey | None:
    if rule.kind in _AGE_RULE_KINDS:
        direction = _numeric_direction(rule.operator)
        return None if direction is None else ConflictGroupKey(kind=rule.kind, direction=direction)
    if rule.kind is RuleKind.PERFORMANCE:
        expected = performance_expected(rule.expected_value)
        direction = _numeric_direction(rule.operator)
        return (
            None
            if expected is None or direction is None
            else ConflictGroupKey(
                kind=rule.kind,
                direction=direction,
                metric_key=expected[0],
            )
        )
    if rule.kind in _SET_RULE_KINDS:
        return ConflictGroupKey(kind=rule.kind)
    return None


def _numeric_direction(operator: str) -> NumericDirection | None:
    if operator in {"gte", "gt"}:
        return "lower"
    if operator in {"lte", "lt"}:
        return "upper"
    return None


def _overlapping_codes(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_codes = expected_codes(left.expected_value)
    right_codes = expected_codes(right.expected_value)
    return (
        left_codes is not None
        and right_codes is not None
        and not left_codes.isdisjoint(right_codes)
    )


def _canonical_urls(rule: EligibilityRule) -> frozenset[str] | None:
    urls: set[str] = set()
    for evidence in rule.evidence:
        canonical = _canonical_url(evidence.source_url)
        if canonical is None:
            return None
        urls.add(canonical)
    return frozenset(urls)
