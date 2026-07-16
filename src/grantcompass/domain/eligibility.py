"""Applicant, eligibility-rule, and assessment domain models."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar, NewType

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from grantcompass.domain.documents import Evidence, EvidenceId
from grantcompass.domain.enums import ConditionStatus, FinalStatus, ReviewStatus, RuleKind
from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.domain.json_types import (
    FrozenJsonObject,
    JsonObject,
    JsonScalar,
    freeze_json_object,
    thaw_json_object,
)

ApplicantProfileId = NewType("ApplicantProfileId", int)
EligibilityRuleId = NewType("EligibilityRuleId", int)

type ExpectedValue = JsonScalar | tuple[JsonScalar, ...]


class ApplicantProfile(BaseModel):
    """Validated applicant facts supplied at an application boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    display_name: str
    founded_on: date | None = None
    regions: tuple[str, ...] = ()
    representative_birth_year: int | None = None
    industries: tuple[str, ...] = ()
    performance: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    benefit_history: tuple[FrozenJsonObject, ...] = ()

    @field_validator("performance", mode="before")
    @classmethod
    def freeze_performance(
        cls,
        value: JsonObject | FrozenJsonObject,
    ) -> FrozenJsonObject:
        """Parse performance JSON into a deeply immutable value."""
        return freeze_json_object(value)

    @field_validator("benefit_history", mode="before")
    @classmethod
    def freeze_benefit_history(
        cls,
        value: tuple[JsonObject | FrozenJsonObject, ...] | list[JsonObject | FrozenJsonObject],
    ) -> tuple[FrozenJsonObject, ...]:
        """Parse every benefit-history item into deeply immutable values."""
        return tuple(freeze_json_object(item) for item in value)

    @field_serializer("performance")
    def serialize_performance(self, value: FrozenJsonObject) -> JsonObject:
        """Serialize immutable performance data as a JSON object."""
        return thaw_json_object(value)

    @field_serializer("benefit_history")
    def serialize_benefit_history(
        self,
        value: tuple[FrozenJsonObject, ...],
    ) -> tuple[JsonObject, ...]:
        """Serialize immutable benefit history as JSON objects."""
        return tuple(thaw_json_object(item) for item in value)


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
