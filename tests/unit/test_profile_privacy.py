from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from grantcompass.domain.eligibility import ApplicantProfile

DEMO_PROFILES = Path(__file__).parents[1] / "fixtures" / "demo" / "synthetic_companies.json"


@pytest.mark.parametrize(
    "field",
    ["resident_registration_number", "bank_account", "phone", "email", "personal_email"],
)
def test_profile_rejects_disallowed_personal_fields(field: str) -> None:
    # Given: an otherwise valid synthetic profile carrying a forbidden personal field.
    payload = {
        "display_name": "명백한합성기업",
        "founded_on": "2025-01-01",
        "regions": ["서울"],
        "industries": ["software"],
        field: "sensitive-value",
    }

    # When: the public profile schema validates the untrusted payload.
    with pytest.raises(ValidationError) as captured:
        _ = ApplicantProfile.model_validate(payload)

    # Then: the closed schema identifies the unexpected field without retaining it.
    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_profile_schema_is_an_explicit_whitelist() -> None:
    # Given: the production applicant profile boundary.
    # When: its declared public fields are inspected.
    fields = frozenset(ApplicantProfile.model_fields)

    # Then: only facts required by deterministic matching can cross the boundary.
    assert fields == {
        "id",
        "display_name",
        "founded_on",
        "regions",
        "representative_birth_year",
        "industries",
        "performance",
        "benefit_history",
    }
    assert ApplicantProfile.model_config.get("extra") == "forbid"


def test_synthetic_demo_profiles_cross_the_production_schema() -> None:
    # Given: the distributable demo profile fixture.
    payload = DEMO_PROFILES.read_bytes()

    # When: the production applicant schema parses every JSON object.
    profiles = TypeAdapter(tuple[ApplicantProfile, ...]).validate_json(payload)

    # Then: conspicuously fictional records contain only matching facts.
    assert len(profiles) == 3
    assert all("합성" in profile.display_name for profile in profiles)
