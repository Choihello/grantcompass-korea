"""Applicant, eligibility-rule, and assessment domain models."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar, NewType

from pydantic import BaseModel, ConfigDict, Field

from grantcompass.domain.documents import Evidence, EvidenceId
from grantcompass.domain.enums import ConditionStatus, FinalStatus, ReviewStatus, RuleKind
from grantcompass.domain.json_types import JsonObject, JsonScalar
from grantcompass.domain.programs import ProgramId

ApplicantProfileId = NewType("ApplicantProfileId", int)
EligibilityRuleId = NewType("EligibilityRuleId", int)
AssessmentId = NewType("AssessmentId", int)

type ExpectedValue = JsonScalar | tuple[JsonScalar, ...]


class ApplicantProfile(BaseModel):
    """Validated applicant facts supplied at an application boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    display_name: str
    founded_on: date | None = None
    regions: tuple[str, ...] = ()
    representative_birth_year: int | None = None
    industries: tuple[str, ...] = ()
    performance: JsonObject = Field(default_factory=dict)
    benefit_history: tuple[JsonObject, ...] = ()


@dataclass(frozen=True, slots=True)
class EligibilityRule:
    """Immutable normalized condition with traceable evidence."""

    kind: RuleKind
    operator: str
    expected_value: ExpectedValue
    required: bool
    review_status: ReviewStatus
    rule_version: str
    evidence: tuple[Evidence, ...]
    id: EligibilityRuleId | None = None
    program_id: ProgramId | None = None


@dataclass(frozen=True, slots=True)
class RuleAssessment:
    """Immutable result for one eligibility rule."""

    rule_id: EligibilityRuleId
    status: ConditionStatus
    explanation: str
    evidence_ids: tuple[EvidenceId, ...]
    error_id: str | None = None


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    """Immutable reproducible result for one program and applicant profile."""

    program_id: ProgramId
    profile_id: ApplicantProfileId
    final_status: FinalStatus
    review_status: ReviewStatus
    rule_version: str
    assessed_at: datetime
    items: tuple[RuleAssessment, ...]
    id: AssessmentId | None = None
