"""Canonical public-program and source-notice domain models."""

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import ClassVar, NewType
from unicodedata import normalize

from pydantic import BaseModel, ConfigDict, HttpUrl

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import JsonObject

ProgramId = NewType("ProgramId", int)
NoticeVersionId = NewType("NoticeVersionId", int)
AttachmentId = NewType("AttachmentId", int)


class AttachmentRef(BaseModel):
    """Validated attachment metadata supplied by a source adapter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

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
    raw_payload: JsonObject

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
class IngestResult:
    """Immutable outcome of one idempotent notice-ingestion transaction."""

    program_id: ProgramId
    notice_version_id: NoticeVersionId
    notice_version_created: bool


def canonical_key_for(raw: RawNotice) -> str:
    """Build the 0.1 merge key from normalized title, organization, and deadline."""
    title = " ".join(normalize("NFKC", raw.title).casefold().split())
    organization = ""
    if raw.organization is not None:
        organization = " ".join(normalize("NFKC", raw.organization).casefold().split())
    application_end = raw.application_end.isoformat() if raw.application_end is not None else ""
    return f"{title}|{organization}|{application_end}"
