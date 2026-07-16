"""Exact evidence-integrity validation for extracted rule candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override
from urllib.parse import quote

if TYPE_CHECKING:
    from collections.abc import Sequence

    from grantcompass.domain.documents import DocumentBlock, Evidence, ParsedDocument
    from grantcompass.domain.eligibility import EligibilityRule

type EvidenceIntegrityErrorCode = Literal[
    "missing_evidence",
    "duplicate_block_id",
    "duplicate_evidence",
    "unknown_block_id",
    "document_id_mismatch",
    "content_hash_mismatch",
    "source_url_mismatch",
    "page_mismatch",
    "section_path_mismatch",
    "quote_not_in_block",
]

_MISSING_EVIDENCE: Final[EvidenceIntegrityErrorCode] = "missing_evidence"
_DUPLICATE_BLOCK_ID: Final[EvidenceIntegrityErrorCode] = "duplicate_block_id"
_DUPLICATE_EVIDENCE: Final[EvidenceIntegrityErrorCode] = "duplicate_evidence"
_UNKNOWN_BLOCK_ID: Final[EvidenceIntegrityErrorCode] = "unknown_block_id"


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityError(Exception):
    """Finite evidence-integrity failure safe for boundary handling."""

    code: EvidenceIntegrityErrorCode

    @override
    def __str__(self) -> str:
        """Return the stable machine-readable integrity code."""
        return self.code


def validate_candidates(
    rules: Sequence[EligibilityRule],
    document: ParsedDocument,
) -> tuple[EligibilityRule, ...]:
    """Reject candidates whose evidence does not exactly match parser output."""
    block_ids = tuple(block.block_id for block in document.blocks)
    if len(set(block_ids)) != len(block_ids):
        raise EvidenceIntegrityError(_DUPLICATE_BLOCK_ID)
    blocks = {block.block_id: block for block in document.blocks}
    expected_url = source_url_for_document(str(document.document_id))
    for rule in rules:
        if not rule.evidence:
            raise EvidenceIntegrityError(_MISSING_EVIDENCE)
        identities = tuple(_evidence_identity(evidence) for evidence in rule.evidence)
        if len(set(identities)) != len(identities):
            raise EvidenceIntegrityError(_DUPLICATE_EVIDENCE)
        for evidence in rule.evidence:
            block = blocks.get(evidence.block_id)
            if block is None:
                raise EvidenceIntegrityError(_UNKNOWN_BLOCK_ID)
            _validate_evidence(evidence, block, document, expected_url)
    return tuple(rules)


def source_url_for_document(document_id: str) -> str:
    """Build the stable internal evidence URI for one document identity."""
    return f"grantcompass://documents/{quote(document_id, safe='')}"


def _validate_evidence(
    evidence: Evidence,
    block: DocumentBlock,
    document: ParsedDocument,
    expected_url: str,
) -> None:
    checks: tuple[tuple[bool, EvidenceIntegrityErrorCode], ...] = (
        (evidence.document_id == document.document_id, "document_id_mismatch"),
        (evidence.content_hash == document.content_hash, "content_hash_mismatch"),
        (evidence.source_url == expected_url, "source_url_mismatch"),
        (evidence.page == block.page, "page_mismatch"),
        (evidence.section_path == block.section_path, "section_path_mismatch"),
        (evidence.quote in block.text, "quote_not_in_block"),
    )
    for valid, code in checks:
        if not valid:
            raise EvidenceIntegrityError(code)


def _evidence_identity(
    evidence: Evidence,
) -> tuple[str, str, str, int | None, str | None, str, str]:
    return (
        str(evidence.document_id),
        str(evidence.block_id),
        evidence.source_url,
        evidence.page,
        evidence.section_path,
        evidence.quote,
        evidence.content_hash,
    )
