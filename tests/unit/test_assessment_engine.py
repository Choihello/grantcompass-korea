from datetime import datetime

import pytest

from grantcompass.domain.documents import EvidenceId
from grantcompass.domain.eligibility import ApplicantProfile, EligibilityRule
from grantcompass.domain.enums import (
    ConditionStatus,
    FinalStatus,
    ReviewStatus,
    RuleKind,
)
from grantcompass.rules.deterministic import DeterministicAssessmentEngine
from grantcompass.rules.evaluation_types import EvaluationOutcome
from tests.assessment_fixtures import (
    ASSESSED_AT,
    RuleValues,
    make_profile,
    make_rule,
)


def test_optional_unsatisfied_rule_becomes_conditional() -> None:
    # Given: a non-required region condition the profile does not satisfy.
    rule = make_rule(
        RuleValues(
            RuleKind.REGION,
            "in",
            "KR-26",
            required=False,
        )
    )

    # When: the condition is assessed.
    result = DeterministicAssessmentEngine().assess(make_profile(), (rule,), ASSESSED_AT)

    # Then: the item and final decision are conditional.
    assert result.items[0].status is ConditionStatus.CONDITIONAL
    assert result.final_status is FinalStatus.CONDITIONAL


class BrokenEvaluator:
    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        del profile, rule, assessed_at
        message = "synthetic evaluator failure"
        raise RuntimeError(message)


class UnexpectedEvaluatorError(ValueError):
    pass


class UnexpectedEvaluator:
    def evaluate(
        self,
        profile: ApplicantProfile,
        rule: EligibilityRule,
        assessed_at: datetime,
    ) -> EvaluationOutcome:
        del profile, rule, assessed_at
        message = "unexpected evaluator failure"
        raise UnexpectedEvaluatorError(message)


def test_rule_failure_is_visible_unknown() -> None:
    # Given: a region evaluator that raises the allowed runtime failure.
    engine = DeterministicAssessmentEngine()
    engine.evaluators[RuleKind.REGION] = BrokenEvaluator()

    # When: one valid region rule is assessed.
    result = engine.assess(
        make_profile(),
        (make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")),),
        ASSESSED_AT,
    )

    # Then: the item remains visible with deterministic failure metadata.
    assert result.items[0].status is ConditionStatus.UNKNOWN
    assert result.items[0].error_id == "evaluator_runtime_error:region"
    assert result.items[0].evidence_ids == (EvidenceId(101),)
    assert result.final_status is FinalStatus.NEEDS_REVIEW


def test_non_runtime_evaluator_failure_remains_visible_to_caller() -> None:
    # Given: an injected evaluator raises outside the allowed conversion contract.
    engine = DeterministicAssessmentEngine()
    engine.evaluators[RuleKind.REGION] = UnexpectedEvaluator()

    # When: the engine invokes the evaluator.
    with pytest.raises(UnexpectedEvaluatorError):
        _ = engine.assess(
            make_profile(),
            (make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")),),
            ASSESSED_AT,
        )

    # Then: the orchestration boundary does not broadly swallow the exception.


def test_same_direction_numeric_constraints_from_distinct_sources_promote_conflict() -> None:
    # Given: official sources publish different upper limits for the same numeric fact.
    rules = (
        make_rule(RuleValues(RuleKind.BUSINESS_AGE_MONTHS, "lte", 35, source="source-a")),
        make_rule(
            RuleValues(
                RuleKind.BUSINESS_AGE_MONTHS,
                "lte",
                36,
                rule_id=2,
                source="source-b",
                evidence_id=102,
            )
        ),
    )

    # When: a 36-month-old business is assessed.
    result = DeterministicAssessmentEngine().assess(make_profile(), rules, ASSESSED_AT)

    # Then: contradictory comparable outcomes become reviewable conflicts.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.CONFLICT,
        ConditionStatus.CONFLICT,
    )
    assert result.final_status is FinalStatus.NEEDS_REVIEW
    assert result.review_status is ReviewStatus.REVIEW_REQUIRED


def test_mixed_direction_numeric_constraints_retain_evaluated_precedence() -> None:
    # Given: independent lower and upper bounds that produce different outcomes.
    rules = (
        make_rule(RuleValues(RuleKind.BUSINESS_AGE_MONTHS, "gte", 36, source="source-a")),
        make_rule(
            RuleValues(
                RuleKind.BUSINESS_AGE_MONTHS,
                "lte",
                35,
                rule_id=2,
                source="source-b",
                evidence_id=102,
            )
        ),
    )

    # When: a 36-month-old business is assessed.
    result = DeterministicAssessmentEngine().assess(make_profile(), rules, ASSESSED_AT)

    # Then: opposing directions coexist and UNSATISFIED retains final precedence.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.SATISFIED,
        ConditionStatus.UNSATISFIED,
    )
    assert result.final_status is FinalStatus.INELIGIBLE


def test_same_source_outcomes_do_not_promote_conflict() -> None:
    # Given: two comparable limits retained from the same official source identity.
    rules = (
        make_rule(RuleValues(RuleKind.BUSINESS_AGE_MONTHS, "lte", 35, source="source-a")),
        make_rule(
            RuleValues(
                RuleKind.BUSINESS_AGE_MONTHS,
                "lte",
                36,
                rule_id=2,
                source="source-a",
                evidence_id=102,
            )
        ),
    )

    # When: their raw outcomes disagree.
    result = DeterministicAssessmentEngine().assess(make_profile(), rules, ASSESSED_AT)

    # Then: evidence from one source cannot manufacture an official-source conflict.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.UNSATISFIED,
        ConditionStatus.SATISFIED,
    )
    assert result.final_status is FinalStatus.INELIGIBLE


@pytest.mark.parametrize(
    (
        "left_document_id",
        "left_source_url",
        "right_document_id",
        "right_source_url",
    ),
    [
        (
            "shared-document",
            "https://one.invalid/rule",
            "shared-document",
            "https://two.invalid/rule",
        ),
        (
            "document-a",
            "HTTPS://EXAMPLE.INVALID:443/rule#first",
            "document-b",
            "https://example.invalid/rule#second",
        ),
        (
            "document-a",
            "https://[malformed",
            "document-b",
            "https://different.invalid/rule",
        ),
    ],
)
def test_overlapping_source_identity_does_not_promote_conflict(
    left_document_id: str,
    left_source_url: str,
    right_document_id: str,
    right_source_url: str,
) -> None:
    # Given: contradictory numeric limits whose document or canonical URL identity overlaps.
    rules = (
        make_rule(
            RuleValues(
                RuleKind.BUSINESS_AGE_MONTHS,
                "lte",
                35,
                source="source-a",
                document_id=left_document_id,
                source_url=left_source_url,
            )
        ),
        make_rule(
            RuleValues(
                RuleKind.BUSINESS_AGE_MONTHS,
                "lte",
                36,
                rule_id=2,
                source="source-b",
                evidence_id=102,
                document_id=right_document_id,
                source_url=right_source_url,
            )
        ),
    )

    # When: their raw outcomes disagree.
    result = DeterministicAssessmentEngine().assess(make_profile(), rules, ASSESSED_AT)

    # Then: either shared identity dimension prevents false cross-source promotion.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.UNSATISFIED,
        ConditionStatus.SATISFIED,
    )
    assert result.final_status is FinalStatus.INELIGIBLE


def test_unrelated_set_values_do_not_promote_conflict() -> None:
    # Given: distinct region constraints about unrelated normalized members.
    rules = (
        make_rule(RuleValues(RuleKind.REGION, "in", "KR-11", source="source-a")),
        make_rule(
            RuleValues(
                RuleKind.REGION,
                "in",
                "KR-26",
                rule_id=2,
                source="source-b",
                evidence_id=102,
            )
        ),
    )

    # When: a Seoul profile is assessed.
    result = DeterministicAssessmentEngine().assess(make_profile(), rules, ASSESSED_AT)

    # Then: unrelated facts retain their original outcomes.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.SATISFIED,
        ConditionStatus.UNSATISFIED,
    )
    assert result.final_status is FinalStatus.INELIGIBLE


def test_review_required_rule_marks_otherwise_automatic_result() -> None:
    # Given: one satisfied rule whose extraction requires human review.
    rule = make_rule(
        RuleValues(
            RuleKind.REGION,
            "in",
            "KR-11",
            review_status=ReviewStatus.REVIEW_REQUIRED,
        )
    )

    # When: the rule is assessed.
    result = DeterministicAssessmentEngine().assess(make_profile(), (rule,), ASSESSED_AT)

    # Then: the final eligibility remains eligible but review is required.
    assert result.final_status is FinalStatus.ELIGIBLE
    assert result.review_status is ReviewStatus.REVIEW_REQUIRED
