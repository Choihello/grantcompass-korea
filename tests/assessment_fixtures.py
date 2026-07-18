from dataclasses import dataclass
from datetime import UTC, date, datetime

from grantcompass.domain.documents import (
    DocumentBlockId,
    DocumentId,
    Evidence,
    EvidenceId,
)
from grantcompass.domain.eligibility import (
    ApplicantProfile,
    ApplicantProfileId,
    EligibilityRule,
    EligibilityRuleId,
    ExpectedValue,
)
from grantcompass.domain.enums import ReviewStatus, RuleKind
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.json_types import FrozenJsonObject, freeze_json_object

ASSESSED_AT = datetime(2026, 3, 31, 12, tzinfo=UTC)
_PERFORMANCE = freeze_json_object({"revenue_krw": 100})
_BENEFIT_HISTORY = (freeze_json_object({"program_id": "benefit-seed"}),)


@dataclass(frozen=True, slots=True)
class ProfileValues:
    profile_id: int | None = 20
    founded_on: date | None = date(2023, 3, 31)
    regions: tuple[str, ...] = ("KR-11",)
    representative_birth_year: int | None = 1990
    industries: tuple[str, ...] = ("KSIC-J62",)
    performance: FrozenJsonObject = _PERFORMANCE
    benefit_history: tuple[FrozenJsonObject, ...] = _BENEFIT_HISTORY


@dataclass(frozen=True, slots=True)
class RuleValues:
    kind: RuleKind
    operator: str
    expected_value: ExpectedValue
    rule_id: int = 1
    program_id: int = 10
    required: bool = True
    review_status: ReviewStatus = ReviewStatus.AUTOMATIC
    source: str = "source-a"
    document_id: str | None = None
    source_url: str | None = None
    evidence_id: int | None = 101


PROFILE_VALUES = ProfileValues()


def make_profile(values: ProfileValues = PROFILE_VALUES) -> ApplicantProfile:
    return ApplicantProfile(
        id=None if values.profile_id is None else ApplicantProfileId(values.profile_id),
        display_name="benchmark-profile",
        founded_on=values.founded_on,
        regions=values.regions,
        representative_birth_year=values.representative_birth_year,
        industries=values.industries,
        performance=values.performance,
        benefit_history=values.benefit_history,
    )


def make_rule(values: RuleValues) -> EligibilityRule:
    evidence = Evidence(
        id=None if values.evidence_id is None else EvidenceId(values.evidence_id),
        document_id=DocumentId(values.document_id or f"document-{values.source}"),
        block_id=DocumentBlockId(f"block-{values.rule_id}"),
        source_url=values.source_url or f"https://example.invalid/{values.source}",
        page=1,
        section_path="eligibility",
        quote=f"rule-{values.rule_id}",
        content_hash=f"{values.rule_id:064x}",
    )
    return EligibilityRule(
        id=EligibilityRuleId(values.rule_id),
        program_id=ProgramId(values.program_id),
        kind=values.kind,
        operator=values.operator,
        expected_value=values.expected_value,
        required=values.required,
        review_status=values.review_status,
        rule_version="rules-v1",
        evidence=(evidence,),
    )
