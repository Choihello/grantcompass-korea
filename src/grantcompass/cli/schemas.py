"""Frozen CLI trust-boundary and serialized output schemas."""

from datetime import date, datetime
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from grantcompass.domain.enums import (
    ConditionStatus,
    FinalStatus,
    FreshnessStatus,
    ReviewStatus,
    SourceName,
)
from grantcompass.matching.forward import DeadlineState
from grantcompass.matching.roadmap import RoadmapItemKind

SchemaVersion = Literal["1.0"]
_MAX_PROFILE_CODE_LENGTH: Final = 100


class FrozenSchema(BaseModel):
    """Provide immutable, closed CLI schemas."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class ProfileCreateInput(FrozenSchema):
    """Parse profile facts once at the CLI boundary."""

    display_name: str = Field(min_length=1, max_length=300)
    founded_on: date | None = None
    regions: tuple[str, ...] = ()
    representative_birth_year: int | None = Field(default=None, ge=1800, le=2100)
    industries: tuple[str, ...] = ()

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        """Trim only surrounding display-name whitespace."""
        return value.strip()

    @field_validator("regions", "industries", mode="before")
    @classmethod
    def normalize_codes(cls, values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        """Trim and stably de-duplicate bounded profile code values."""
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            if not value or len(value) > _MAX_PROFILE_CODE_LENGTH:
                raise ProfileFieldError
            if value not in seen:
                normalized.append(value)
                seen.add(value)
        return tuple(normalized)


class ProfileFieldError(ValueError):
    """Reject an invalid finite profile field before persistence."""


class ProfileIdentityOutput(FrozenSchema):
    """Serialized selected applicant identity."""

    id: int
    display_name: str


class ProfileCreatedOutput(FrozenSchema):
    """Serialized profile creation result."""

    schema_version: SchemaVersion = "1.0"
    profile_id: int
    display_name: str


class SourceFreshnessOutput(FrozenSchema):
    """Serialized current source health and last successful collection."""

    source: SourceName
    status: FreshnessStatus
    observed_at: datetime | None
    last_successful_at: datetime | None
    error_code: str | None


class SyncResultOutput(FrozenSchema):
    """Serialized one-source synchronization outcome."""

    source: SourceName
    stored: int
    unchanged: int
    failed: int
    freshness: FreshnessStatus
    error_code: str | None
    last_successful_at: datetime | None


class SyncOutput(FrozenSchema):
    """Serialized deterministic synchronization response."""

    schema_version: SchemaVersion = "1.0"
    synced_at: datetime
    results: tuple[SyncResultOutput, ...]


class ConditionOutput(FrozenSchema):
    """Serialized condition assessment with evidence references."""

    rule_id: int
    status: ConditionStatus
    error_id: str | None
    evidence_ids: tuple[int, ...]


class EvidenceOutput(FrozenSchema):
    """Serialized bounded official provenance for one evidence record."""

    id: int
    source_url: str
    document_id: str
    block_id: str
    page: int | None
    section_path: str | None
    content_hash: str


class DeadlineOutput(FrozenSchema):
    """Serialized application deadline state."""

    state: DeadlineState
    date: date | None
    days_remaining: int | None


class RoadmapOutput(FrozenSchema):
    """Serialized condition action or verification question."""

    kind: RoadmapItemKind
    code: str
    condition_status: ConditionStatus | None
    rule_id: int | None
    evidence_ids: tuple[int, ...]


class SearchProgramOutput(FrozenSchema):
    """Serialized complete assessment or visible per-program input error."""

    program_id: int
    title: str
    organization: str | None
    final_status: FinalStatus | None
    review_status: ReviewStatus
    deadline: DeadlineOutput
    conditions: tuple[ConditionOutput, ...]
    evidence: tuple[EvidenceOutput, ...]
    roadmap: tuple[RoadmapOutput, ...]
    input_errors: tuple[str, ...]


class SearchOutput(FrozenSchema):
    """Serialized deterministic profile search response."""

    schema_version: SchemaVersion = "1.0"
    profile: ProfileIdentityOutput
    assessed_at: datetime
    source_freshness: tuple[SourceFreshnessOutput, ...]
    results: tuple[SearchProgramOutput, ...]


class ReportWrittenOutput(FrozenSchema):
    """Serialized report artifact identity without embedding its contents."""

    schema_version: SchemaVersion = "1.0"
    output_path: str
    profile_id: int
    result_count: int
