from grantcompass.domain.enums import (
    CaseStage,
    ConditionStatus,
    FinalStatus,
    FreshnessStatus,
    ReviewStatus,
    RuleKind,
    SourceName,
)


def test_public_enum_values_are_stable() -> None:
    # Given: the public enum classes exported by the domain package.

    # When: their serialized values are read in declaration order.
    actual_values = {
        "source_name": [item.value for item in SourceName],
        "condition_status": [item.value for item in ConditionStatus],
        "final_status": [item.value for item in FinalStatus],
        "review_status": [item.value for item in ReviewStatus],
        "freshness_status": [item.value for item in FreshnessStatus],
        "case_stage": [item.value for item in CaseStage],
        "rule_kind": [item.value for item in RuleKind],
    }

    # Then: the machine-consumed wire values remain stable.
    assert actual_values == {
        "source_name": ["kstartup", "bizinfo", "manual"],
        "condition_status": [
            "satisfied",
            "unsatisfied",
            "conditional",
            "unknown",
            "conflict",
        ],
        "final_status": [
            "eligible",
            "conditional",
            "ineligible",
            "needs_review",
        ],
        "review_status": ["automatic", "review_required", "reviewed"],
        "freshness_status": ["fresh", "stale"],
        "case_stage": [
            "recommended",
            "contacted",
            "consulted",
            "applying",
            "submitted",
            "selected",
            "not_selected",
            "closed",
        ],
        "rule_kind": [
            "business_age_months",
            "region",
            "representative_age",
            "industry",
            "performance",
            "duplicate_benefit",
            "natural_language",
        ],
    }
