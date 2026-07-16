from dataclasses import replace
from datetime import UTC, datetime

import pytest

from grantcompass.domain.eligibility import (
    ApplicantProfile,
    ApplicantProfileId,
    EligibilityRule,
)
from grantcompass.domain.enums import RuleKind
from grantcompass.rules.deterministic import (
    AssessmentInputError,
    AssessmentInputErrorCode,
    DeterministicAssessmentEngine,
)
from tests.assessment_fixtures import (
    ASSESSED_AT,
    PROFILE_VALUES,
    RuleValues,
    make_profile,
    make_rule,
)


@pytest.mark.parametrize(
    ("profile", "rules", "expected_code"),
    [
        (
            make_profile(replace(PROFILE_VALUES, profile_id=None)),
            (make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")),),
            "missing_profile_id",
        ),
        (
            make_profile(),
            (replace(make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")), id=None),),
            "missing_rule_id",
        ),
        (
            make_profile(),
            (
                replace(
                    make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")),
                    program_id=None,
                ),
            ),
            "missing_program_id",
        ),
        (
            make_profile(),
            (
                replace(
                    make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")),
                    evidence=(
                        replace(
                            make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")).evidence[0],
                            id=None,
                        ),
                    ),
                ),
            ),
            "missing_evidence_id",
        ),
        (
            make_profile(),
            (
                make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")),
                make_rule(
                    RuleValues(
                        RuleKind.REGION,
                        "in",
                        "KR-11",
                        rule_id=2,
                        program_id=11,
                        evidence_id=102,
                    )
                ),
            ),
            "mixed_programs",
        ),
        (
            make_profile(),
            (
                make_rule(RuleValues(RuleKind.REGION, "in", "KR-11")),
                replace(
                    make_rule(
                        RuleValues(
                            RuleKind.INDUSTRY,
                            "in",
                            "KSIC-J62",
                            rule_id=2,
                            evidence_id=102,
                        )
                    ),
                    rule_version="rules-v2",
                ),
            ),
            "mixed_rule_versions",
        ),
        (make_profile(), (), "empty_rules"),
    ],
)
def test_assessment_rejects_invalid_identity_boundary(
    profile: ApplicantProfile,
    rules: tuple[EligibilityRule, ...],
    expected_code: AssessmentInputErrorCode,
) -> None:
    # Given: one specifically invalid assessment input.

    # When: the engine validates its persisted assessment boundary.
    with pytest.raises(AssessmentInputError) as caught:
        _ = DeterministicAssessmentEngine().assess(profile, rules, ASSESSED_AT)

    # Then: the finite machine-readable failure is returned.
    assert caught.value.code == expected_code


def test_assessment_rejects_naive_reference_time() -> None:
    # Given: a persisted assessment input with a timezone-naive reference.
    rule = make_rule(RuleValues(RuleKind.REGION, "in", "KR-11"))

    # When: the engine validates the reference instant.
    with pytest.raises(AssessmentInputError) as caught:
        _ = DeterministicAssessmentEngine().assess(
            make_profile(),
            (rule,),
            datetime(2026, 3, 31, 12, tzinfo=UTC).replace(tzinfo=None),
        )

    # Then: local-machine timezone assumptions cannot enter the result.
    assert caught.value.code == "naive_assessed_at"


def test_persisted_profile_id_round_trips_through_json() -> None:
    # Given: a frozen profile carrying its persisted identity.
    profile = make_profile()

    # When: the boundary model is serialized and parsed again.
    parsed = ApplicantProfile.model_validate_json(profile.model_dump_json())

    # Then: the branded persisted identity remains available.
    assert parsed.id == ApplicantProfileId(20)
