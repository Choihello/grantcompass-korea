"""Strict schemas for the two durable institutional audit state families."""

from enum import StrEnum
from typing import Annotated, ClassVar, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, TypeAdapter

type PositiveIdentity = Annotated[StrictInt, Field(gt=0)]
type ReviewRevision = Annotated[StrictInt, Field(ge=0)]
type CaseStageValue = Literal[
    "recommended",
    "contacted",
    "consulted",
    "applying",
    "submitted",
    "selected",
    "not_selected",
    "closed",
]
type ConditionStatusValue = Literal[
    "satisfied", "unsatisfied", "conditional", "unknown", "conflict"
]
type FinalStatusValue = Literal["eligible", "conditional", "ineligible", "needs_review"]
type ReviewStatusValue = Literal["automatic", "review_required", "reviewed"]


class _AuditSchema(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)


class CaseAuditState(_AuditSchema):
    """Exact persisted state for a case transition."""

    schema_version: Literal[1]
    entity_id: PositiveIdentity
    stage: CaseStageValue
    assignee_name: StrictStr | None
    note: StrictStr | None
    updated_at: StrictStr


class AssessmentOverrideState(_AuditSchema):
    """Exact persisted identity and status for one human override."""

    rule_assessment_id: PositiveIdentity
    rule_id: PositiveIdentity
    status: ConditionStatusValue


class AssessmentConditionState(_AuditSchema):
    """Exact persisted automatic condition evidence for a review."""

    rule_assessment_id: PositiveIdentity
    rule_id: PositiveIdentity
    status: ConditionStatusValue
    explanation: StrictStr
    evidence_ids: tuple[PositiveIdentity, ...]
    error_id: StrictStr | None


class AssessmentAuditState(_AuditSchema):
    """Exact persisted automatic and effective assessment review state."""

    schema_version: Literal[1]
    assessment_id: PositiveIdentity
    automatic_final_status: FinalStatusValue
    review_status: ReviewStatusValue
    effective_final_status: FinalStatusValue
    review_revision: ReviewRevision
    reviewed_at: StrictStr | None
    overrides: tuple[AssessmentOverrideState, ...]
    automatic_conditions: Annotated[tuple[AssessmentConditionState, ...], Field(min_length=1)]


class _CaseAuditIdentity(_AuditSchema):
    entity_type: Literal["case"]
    action: Literal["transition"]


class _AssessmentAuditIdentity(_AuditSchema):
    entity_type: Literal["assessment"]
    action: Literal["review"]


type _AuditIdentity = _CaseAuditIdentity | _AssessmentAuditIdentity


class AuditStateKind(StrEnum):
    """Closed discriminator for every supported audit state family."""

    CASE = "case"
    ASSESSMENT = "assessment"


_IDENTITY_ADAPTER: TypeAdapter[_AuditIdentity] = TypeAdapter(_AuditIdentity)
_CASE_ADAPTER: TypeAdapter[CaseAuditState] = TypeAdapter(CaseAuditState)
_ASSESSMENT_ADAPTER: TypeAdapter[AssessmentAuditState] = TypeAdapter(AssessmentAuditState)


def parse_audit_identity(entity_type: str, action: str) -> AuditStateKind:
    """Validate a row identity and return its matching state schema."""
    identity = _IDENTITY_ADAPTER.validate_python(
        {"entity_type": entity_type, "action": action},
        strict=True,
    )
    match identity:
        case _CaseAuditIdentity():
            return AuditStateKind.CASE
        case _AssessmentAuditIdentity():
            return AuditStateKind.ASSESSMENT
        case _:
            assert_never(identity)


def validate_audit_state(value: str, kind: AuditStateKind) -> None:
    """Validate one JSON document against its discriminated strict schema."""
    match kind:
        case AuditStateKind.CASE:
            _ = _CASE_ADAPTER.validate_json(value, strict=True)
        case AuditStateKind.ASSESSMENT:
            _ = _ASSESSMENT_ADAPTER.validate_json(value, strict=True)
        case _:
            assert_never(kind)
