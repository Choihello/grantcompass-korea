import pytest

from grantcompass.domain.eligibility import AssessmentResult
from grantcompass.domain.enums import ConditionStatus, FinalStatus, RuleKind
from grantcompass.rules.deterministic import DeterministicAssessmentEngine
from tests.assessment_fixtures import (
    ASSESSED_AT,
    RuleValues,
    make_profile,
    make_rule,
)


def _assess_source_pair(left_source_url: str, right_source_url: str) -> AssessmentResult:
    rules = (
        make_rule(
            RuleValues(
                RuleKind.BUSINESS_AGE_MONTHS,
                "lte",
                35,
                source="source-a",
                document_id="document-a",
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
                document_id="document-b",
                source_url=right_source_url,
            )
        ),
    )
    return DeterministicAssessmentEngine().assess(make_profile(), rules, ASSESSED_AT)


@pytest.mark.parametrize(
    ("left_source_url", "right_source_url"),
    [
        (
            "https://example.invalid/%2f",
            "https://example.invalid/%2F",
        ),
        (
            "https://example.invalid",
            "https://example.invalid/",
        ),
    ],
)
def test_equivalent_http_url_syntax_does_not_establish_source_independence(
    left_source_url: str,
    right_source_url: str,
) -> None:
    # Given: disjoint document IDs whose valid source URLs are syntax-equivalent.

    # When: contradictory comparable rules are assessed.
    result = _assess_source_pair(left_source_url, right_source_url)

    # Then: equivalent URLs prevent false cross-source conflict promotion.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.UNSATISFIED,
        ConditionStatus.SATISFIED,
    )
    assert result.final_status is FinalStatus.INELIGIBLE


@pytest.mark.parametrize(
    ("left_source_url", "right_source_url"),
    [
        (
            "HTTP://192.0.2.1:80/rule#left",
            "http://192.0.2.1/rule#right",
        ),
        (
            "HTTPS://[2001:0DB8:0:0:0:0:0:1]:443/rule#left",
            "https://[2001:db8::1]/rule#right",
        ),
        (
            "HTTPS://BÜCHER.EXAMPLE:443/rule#left",
            "https://xn--bcher-kva.example/rule#right",
        ),
        (
            "https://example.invalid/%7euser",
            "https://example.invalid/~user",
        ),
    ],
)
def test_valid_canonical_source_forms_do_not_establish_source_independence(
    left_source_url: str,
    right_source_url: str,
) -> None:
    # Given: disjoint document IDs with equivalent accepted HTTP source forms.

    # When: contradictory comparable rules are assessed.
    result = _assess_source_pair(left_source_url, right_source_url)

    # Then: canonical source identity prevents conflict promotion.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.UNSATISFIED,
        ConditionStatus.SATISFIED,
    )
    assert result.final_status is FinalStatus.INELIGIBLE


@pytest.mark.parametrize(
    "invalid_source_url",
    [
        "htt%70://example.invalid/rule",
        "https://example.invalid:%34%34%33/rule",
        "https://-example.invalid/rule",
        "https://999.0.0.1/rule",
        "https://[2001:db8::gg]/rule",
        "https://example.invalid:70000/rule",
        "https://user:secret@example.invalid/rule",
    ],
)
def test_invalid_source_url_cannot_establish_source_independence(
    invalid_source_url: str,
) -> None:
    # Given: one rejected source URL and one unrelated valid source URL.

    # When: contradictory comparable rules are assessed.
    result = _assess_source_pair(
        invalid_source_url,
        "https://different.invalid/rule",
    )

    # Then: rejected source identity cannot promote a conflict.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.UNSATISFIED,
        ConditionStatus.SATISFIED,
    )
    assert result.final_status is FinalStatus.INELIGIBLE


@pytest.mark.parametrize(
    ("left_source_url", "right_source_url"),
    [
        (
            "https://example.invalid/a%2Fb",
            "https://example.invalid/a/b",
        ),
        (
            "https://example.invalid/rule?value=one%26two",
            "https://example.invalid/rule?value=one&two",
        ),
    ],
)
def test_reserved_escapes_remain_distinct_source_identity(
    left_source_url: str,
    right_source_url: str,
) -> None:
    # Given: disjoint sources that differ by encoded reserved characters.

    # When: contradictory comparable rules are assessed.
    result = _assess_source_pair(left_source_url, right_source_url)

    # Then: reserved path and query semantics remain distinct.
    assert tuple(item.status for item in result.items) == (
        ConditionStatus.CONFLICT,
        ConditionStatus.CONFLICT,
    )
    assert result.final_status is FinalStatus.NEEDS_REVIEW
