from datetime import datetime
from pathlib import Path

from grantcompass.domain.eligibility import (
    ApplicantProfile,
    AssessmentResult,
    EligibilityRule,
)
from grantcompass.domain.enums import (
    ConditionStatus,
    FinalStatus,
    ReviewStatus,
    RuleKind,
)
from grantcompass.rules.assessment_benchmark import AssessmentBenchmarkCase, load_assessment_cases
from grantcompass.rules.deterministic import (
    DeterministicAssessmentEngine,
    EvaluationOutcome,
)

MANIFEST_PATH = Path(__file__).parents[1] / "fixtures" / "benchmark" / "assessments.jsonl"


class BrokenEvaluator:
    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        del profile, rule, assessed_at
        message = "synthetic benchmark evaluator failure"
        raise RuntimeError(message)


def test_all_100_assessments_match_independent_golden_outcomes() -> None:
    # Given: exactly 100 frozen, independently reviewed benchmark cases.
    cases = load_assessment_cases(MANIFEST_PATH)

    # When: every case is assessed twice through the production engine.
    results: list[tuple[AssessmentBenchmarkCase, AssessmentResult, AssessmentResult]] = []
    for case in cases:
        engine = DeterministicAssessmentEngine()
        if case.evaluator_failure_kind is not None:
            engine.evaluators[case.evaluator_failure_kind] = BrokenEvaluator()
        rules = tuple(rule.to_domain() for rule in case.rules)
        first = engine.assess(case.profile, rules, case.assessed_at)
        second = engine.assess(case.profile, rules, case.assessed_at)
        results.append((case, first, second))

    # Then: all inputs are distinct and exact reviewed outputs are reproducible.
    assert len(results) == 100
    assert len({case.case_id for case, _first, _second in results}) == 100
    assert len({case.input_signature() for case, _first, _second in results}) == 100
    for case, first, second in results:
        assert first == second
        assert first.final_status is case.expected_final_status
        assert first.review_status is case.expected_review_status
        assert tuple(
            (
                item.rule_id,
                item.status,
                item.error_id,
                item.evidence_ids,
            )
            for item in first.items
        ) == tuple(item.domain_signature() for item in case.expected_items)
        assert all(item.evidence_ids for item in first.items)


def test_benchmark_covers_every_required_assessment_class() -> None:
    # Given: the parsed golden benchmark cases.
    cases = load_assessment_cases(MANIFEST_PATH)

    # When: structural coverage tokens are collected from declared inputs and outcomes.
    kinds = {rule.kind for case in cases for rule in case.rules}
    operators = {rule.operator for case in cases for rule in case.rules}
    statuses = {item.status for case in cases for item in case.expected_items}
    final_statuses = {case.expected_final_status for case in cases}
    review_statuses = {case.expected_review_status for case in cases}
    features = {feature for case in cases for feature in case.coverage}

    # Then: every supported and review-sensitive class is present.
    assert kinds == set(RuleKind)
    assert operators == {"lte", "lt", "gte", "gt", "in", "not_in", "contains"}
    assert statuses == set(ConditionStatus)
    assert final_statuses == set(FinalStatus)
    assert review_statuses == {ReviewStatus.AUTOMATIC, ReviewStatus.REVIEW_REQUIRED}
    assert {
        "boundary",
        "missing_fact",
        "malformed_expected",
        "unsupported_kind",
        "conflict",
        "unrelated_non_conflict",
        "conditional",
        "review_required",
        "evaluator_failure",
        "leap_day",
        "end_of_month",
    }.issubset(features)


def test_benchmark_contains_golden_malformed_region_and_industry_facts() -> None:
    # Given: the parsed golden benchmark cases.
    cases = load_assessment_cases(MANIFEST_PATH)

    # When: malformed code-set facts with matching visible outcomes are identified.
    malformed_kinds = {
        rule.kind
        for case in cases
        for rule, expected in zip(case.rules, case.expected_items, strict=True)
        if expected.error_id == "malformed_profile_fact"
        and (
            (
                rule.kind is RuleKind.REGION
                and any(not value.strip() for value in case.profile.regions)
            )
            or (
                rule.kind is RuleKind.INDUSTRY
                and any(not value.strip() for value in case.profile.industries)
            )
        )
    }

    # Then: both normalized set-valued profile facts have literal golden coverage.
    assert malformed_kinds == {RuleKind.REGION, RuleKind.INDUSTRY}
