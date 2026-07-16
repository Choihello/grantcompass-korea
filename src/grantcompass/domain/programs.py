"""Canonical public-program and source-notice domain models."""

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import ClassVar
from unicodedata import normalize

from pydantic import BaseModel, ConfigDict, HttpUrl, field_serializer, field_validator

from grantcompass.domain.enums import SourceName
from grantcompass.domain.ids import (
    AssessmentId,
    AttachmentId,
    ChangeSetId,
    NoticeVersionId,
    ProgramId,
)
from grantcompass.domain.json_types import (
    FrozenJsonObject,
    JsonObject,
    freeze_json_object,
    thaw_json_object,
)

__all__ = [
    "AssessmentId",
    "AttachmentId",
    "AttachmentRef",
    "CanonicalProgramView",
    "ChangeSet",
    "ConflictValue",
    "FieldConflict",
    "IngestResult",
    "MergeCandidate",
    "NoticeVersion",
    "NoticeVersionId",
    "Program",
    "ProgramId",
    "RawNotice",
    "canonical_key_for",
    "canonical_key_from_fields",
    "has_complete_merge_identity",
    "storage_key_for",
]


class AttachmentRef(BaseModel):
    """Validated attachment metadata supplied by a source adapter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    filename: str
    download_url: HttpUrl
    media_type: str | None = None
    content_hash: str | None = None


class RawNotice(BaseModel):
    """Validated source notice at the collection boundary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    source: SourceName
    source_notice_id: str
    title: str
    organization: str | None = None
    summary: str | None = None
    application_start: date | None = None
    application_end: date | None = None
    detail_url: HttpUrl
    attachments: tuple[AttachmentRef, ...] = ()
    raw_payload: FrozenJsonObject

    @field_validator("raw_payload", mode="before")
    @classmethod
    def freeze_raw_payload(
        cls,
        value: JsonObject | FrozenJsonObject,
    ) -> FrozenJsonObject:
        """Parse transport JSON into a deeply immutable value."""
        return freeze_json_object(value)

    @field_serializer("raw_payload")
    def serialize_raw_payload(self, value: FrozenJsonObject) -> JsonObject:
        """Serialize immutable JSON as standard JSON containers."""
        return thaw_json_object(value)

    def content_hash(self) -> str:
        """Return the stable hash of published content, excluding transport metadata."""
        canonical = self.model_dump_json(exclude={"raw_payload"}, exclude_none=False)
        return sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Program:
    """Immutable merged representation of one public support program."""

    id: ProgramId
    canonical_key: str
    title: str
    organization: str | None
    application_start: date | None
    application_end: date | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NoticeVersion:
    """Immutable source-specific snapshot of published notice content."""

    id: NoticeVersionId
    program_id: ProgramId
    source: SourceName
    source_notice_id: str
    content_hash: str
    detail_url: str
    raw_payload_json: str
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class ConflictValue:
    """One source-specific normalized value retained during a conflict."""

    source: SourceName
    value: str | None


@dataclass(frozen=True, slots=True)
class FieldConflict:
    """Current disagreement among official source values for one program field."""

    program_id: ProgramId
    field_name: str
    values: tuple[ConflictValue, ...]


@dataclass(frozen=True, slots=True)
class MergeCandidate:
    """Pair withheld from automatic merging for human review."""

    left_program_id: ProgramId
    right_program_id: ProgramId
    title_similarity: float
    status: str


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """Immutable link between consecutive changed notice snapshots."""

    id: ChangeSetId
    kind: str
    changed_fields: tuple[str, ...]
    previous_version_id: NoticeVersionId
    current_version_id: NoticeVersionId


@dataclass(frozen=True, slots=True)
class CanonicalProgramView:
    """Conflict-aware public program state derived from current source pointers."""

    id: ProgramId
    title: str | None
    organization: str | None
    summary: str | None
    application_start: date | None
    application_end: date | None
    conflicts: tuple[FieldConflict, ...]


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Immutable outcome of one idempotent notice-ingestion transaction."""

    program_id: ProgramId
    notice_version_id: NoticeVersionId
    notice_version_created: bool
    change_set: ChangeSet | None = None
    impacted_assessment_ids: tuple[AssessmentId, ...] = ()


def canonical_key_for(raw: RawNotice) -> str:
    """Build the 0.1 merge key from normalized title, organization, and deadline."""
    return canonical_key_from_fields(raw.title, raw.organization, raw.application_end)


def has_complete_merge_identity(raw: RawNotice) -> bool:
    """Return whether every conservative automatic-merge field is present."""
    return (
        bool(raw.title.strip())
        and raw.organization is not None
        and bool(raw.organization.strip())
        and raw.application_end is not None
    )


def storage_key_for(raw: RawNotice) -> str:
    """Return an exact merge key or a source-identity-isolated incomplete key."""
    canonical_key = canonical_key_for(raw)
    if has_complete_merge_identity(raw):
        return canonical_key
    identity = f"{raw.source.value}|{raw.source_notice_id}"
    return f"{canonical_key}|incomplete:{sha256(identity.encode()).hexdigest()}"


def canonical_key_from_fields(
    title_value: str,
    organization_value: str | None,
    application_end_value: date | None,
) -> str:
    """Build an exact normalized identity from the three conservative merge fields."""
    title = " ".join(normalize("NFKC", title_value).casefold().split())
    organization = ""
    if organization_value is not None:
        organization = " ".join(normalize("NFKC", organization_value).casefold().split())
    application_end = application_end_value.isoformat() if application_end_value is not None else ""
    return f"{title}|{organization}|{application_end}"
