from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from grantcompass.domain.eligibility import ApplicantProfile
from grantcompass.domain.enums import ConditionStatus, RuleKind
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.rules.deterministic import (
    DeterministicAssessmentEngine,
    completed_business_age_months,
    evaluate_business_age,
)
from tests.assessment_fixtures import (
    ASSESSED_AT,
    PROFILE_VALUES,
    RuleValues,
    make_profile,
    make_rule,
)


@pytest.mark.parametrize(
    ("months", "limit", "expected"),
    [
        (35, 36, ConditionStatus.SATISFIED),
        (36, 36, ConditionStatus.SATISFIED),
        (37, 36, ConditionStatus.UNSATISFIED),
    ],
)
def test_business_age_boundary(
    months: int,
    limit: int,
    expected: ConditionStatus,
) -> None:
    # Given: completed business months around an inclusive upper bound.

    # When: the supported comparison is evaluated.
    result = evaluate_business_age(months, "lte", limit)

    # Then: the boundary is inclusive only at the limit.
    assert result is expected


@pytest.mark.parametrize(
    ("founded_on", "assessed_at", "expected"),
    [
        (date(2025, 1, 31), datetime(2025, 2, 28, tzinfo=UTC), 1),
        (date(2024, 2, 29), datetime(2025, 2, 28, tzinfo=UTC), 12),
        (date(2024, 2, 29), datetime(2025, 2, 27, 23, 59, tzinfo=UTC), 11),
        (date(2025, 3, 31), datetime(2026, 3, 30, tzinfo=UTC), 11),
    ],
)
def test_completed_business_months_use_clamped_calendar_anniversary(
    founded_on: date,
    assessed_at: datetime,
    expected: int,
) -> None:
    # Given: a founding date and deterministic reference instant.

    # When: completed calendar months are calculated.
    result = completed_business_age_months(founded_on, assessed_at)

    # Then: end-of-month and leap anniversaries are calendar-correct.
    assert result == expected


def test_business_months_are_timezone_independent() -> None:
    # Given: two representations of the same instant across a date boundary.
    first = datetime(2026, 4, 1, 0, 30, tzinfo=timezone(timedelta(hours=9)))
    second = datetime(2026, 3, 31, 15, 30, tzinfo=UTC)

    # When: both reference instants calculate business age.
    results = (
        completed_business_age_months(date(2026, 2, 28), first),
        completed_business_age_months(date(2026, 2, 28), second),
    )

    # Then: UTC normalization gives the same completed-month result.
    assert results == (1, 1)


def test_representative_age_uses_utc_reference_year() -> None:
    # Given: a local timestamp already in the next year but still prior year in UTC.
    assessed_at = datetime(2027, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=9)))
    rule = make_rule(RuleValues(RuleKind.REPRESENTATIVE_AGE, "lte", 36))

    # When: representative age is assessed.
    item = (
        DeterministicAssessmentEngine()
        .assess(
            make_profile(),
            (rule,),
            assessed_at,
        )
        .items[0]
    )

    # Then: the UTC assessment year supplies the deterministic age.
    assert item.status is ConditionStatus.SATISFIED


@pytest.mark.parametrize(
    ("values", "expected_status", "expected_error"),
    [
        (RuleValues(RuleKind.REGION, "in", "kr-11"), ConditionStatus.SATISFIED, None),
        (
            RuleValues(RuleKind.INDUSTRY, "not_in", " ksic-k64 "),
            ConditionStatus.SATISFIED,
            None,
        ),
        (
            RuleValues(RuleKind.PERFORMANCE, "gte", ("revenue_krw", 100)),
            ConditionStatus.SATISFIED,
            None,
        ),
        (
            RuleValues(RuleKind.DUPLICATE_BENEFIT, "not_in", "benefit-growth"),
            ConditionStatus.SATISFIED,
            None,
        ),
        (
            RuleValues(RuleKind.NATURAL_LANGUAGE, "in", "manual"),
            ConditionStatus.UNKNOWN,
            "unsupported_rule_kind",
        ),
        (
            RuleValues(RuleKind.REGION, "contains", "KR-11"),
            ConditionStatus.UNKNOWN,
            "unsupported_operator",
        ),
        (
            RuleValues(RuleKind.PERFORMANCE, "gte", ("revenue_krw", "high")),
            ConditionStatus.UNKNOWN,
            "malformed_expected_value",
        ),
    ],
)
def test_engine_evaluates_supported_schemas_and_visible_failures(
    values: RuleValues,
    expected_status: ConditionStatus,
    expected_error: str | None,
) -> None:
    # Given: a persisted profile and one evidence-linked rule.
    engine = DeterministicAssessmentEngine()

    # When: the rule is assessed at the fixed instant.
    item = engine.assess(make_profile(), (make_rule(values),), ASSESSED_AT).items[0]

    # Then: the exact status and stable error code are visible.
    assert item.status is expected_status
    assert item.error_id == expected_error
    assert item.evidence_ids


@pytest.mark.parametrize(
    ("profile", "rule"),
    [
        (
            make_profile(replace(PROFILE_VALUES, founded_on=None)),
            RuleValues(RuleKind.BUSINESS_AGE_MONTHS, "lte", 36),
        ),
        (
            make_profile(replace(PROFILE_VALUES, representative_birth_year=None)),
            RuleValues(RuleKind.REPRESENTATIVE_AGE, "lte", 39),
        ),
        (
            make_profile(replace(PROFILE_VALUES, regions=())),
            RuleValues(RuleKind.REGION, "in", "KR-11"),
        ),
        (
            make_profile(replace(PROFILE_VALUES, industries=())),
            RuleValues(RuleKind.INDUSTRY, "in", "KSIC-J62"),
        ),
        (
            make_profile(replace(PROFILE_VALUES, performance=freeze_json_object({}))),
            RuleValues(RuleKind.PERFORMANCE, "gte", ("revenue_krw", 1)),
        ),
        (
            make_profile(replace(PROFILE_VALUES, benefit_history=())),
            RuleValues(RuleKind.DUPLICATE_BENEFIT, "not_in", "benefit-seed"),
        ),
    ],
)
def test_missing_profile_facts_remain_unknown(
    profile: ApplicantProfile,
    rule: RuleValues,
) -> None:
    # Given: a profile without the deterministic fact required by one rule.

    # When: the rule is assessed.
    item = DeterministicAssessmentEngine().assess(profile, (make_rule(rule),), ASSESSED_AT).items[0]

    # Then: absence is explicit rather than guessed.
    assert item.status is ConditionStatus.UNKNOWN
    assert item.error_id == "missing_profile_fact"


@pytest.mark.parametrize(
    ("profile", "rule"),
    [
        (
            make_profile(replace(PROFILE_VALUES, regions=("   ",))),
            RuleValues(RuleKind.REGION, "in", "KR-11"),
        ),
        (
            make_profile(replace(PROFILE_VALUES, regions=("KR-11", "  "))),
            RuleValues(RuleKind.REGION, "in", "KR-11"),
        ),
        (
            make_profile(replace(PROFILE_VALUES, industries=("\t",))),
            RuleValues(RuleKind.INDUSTRY, "not_in", "KSIC-J62"),
        ),
        (
            make_profile(replace(PROFILE_VALUES, industries=("KSIC-J62", "\n"))),
            RuleValues(RuleKind.INDUSTRY, "in", "KSIC-J62"),
        ),
    ],
)
def test_malformed_region_and_industry_facts_remain_unknown(
    profile: ApplicantProfile,
    rule: RuleValues,
) -> None:
    # Given: a nonempty code tuple containing at least one malformed normalized member.

    # When: the set-valued fact is assessed.
    item = DeterministicAssessmentEngine().assess(profile, (make_rule(rule),), ASSESSED_AT).items[0]

    # Then: no valid sibling can hide malformed profile input.
    assert item.status is ConditionStatus.UNKNOWN
    assert item.error_id == "malformed_profile_fact"
