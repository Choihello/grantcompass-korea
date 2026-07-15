"""Parsed-document and evidence provenance domain models."""

from dataclasses import dataclass
from typing import NewType

DocumentId = NewType("DocumentId", str)
DocumentBlockId = NewType("DocumentBlockId", str)
EvidenceId = NewType("EvidenceId", int)


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    """Immutable addressable block extracted from a source document."""

    block_id: DocumentBlockId
    ordinal: int
    kind: str
    text: str
    page: int | None
    section_path: str | None
    table_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Immutable parser output with content-addressed source identity."""

    document_id: DocumentId
    parser_name: str
    parser_version: str
    content_hash: str
    blocks: tuple[DocumentBlock, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Evidence:
    """Exact document coordinates supporting an eligibility statement."""

    document_id: DocumentId
    block_id: DocumentBlockId
    source_url: str
    page: int | None
    section_path: str | None
    quote: str
    content_hash: str
    id: EvidenceId | None = None
