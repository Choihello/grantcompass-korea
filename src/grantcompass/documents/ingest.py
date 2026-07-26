"""Transactional attachment parsing and durable review-state transitions."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePath
from typing import Final, Literal

from anyio.to_thread import run_sync
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.documents.base import DocumentParseError, ParsedDocument
from grantcompass.documents.download import MAX_ATTACHMENT_BYTES
from grantcompass.documents.errors import DocumentIngestError, DocumentIngestErrorCode
from grantcompass.documents.hwpx import HwpxParser
from grantcompass.documents.pdf import PdfParser
from grantcompass.domain.enums import ReviewStatus
from grantcompass.rules.candidates import RegexRuleCandidateProvider
from grantcompass.storage.table_documents import (
    DocumentBlockRow,
    DocumentRow,
    EvidenceRow,
    rule_evidence,
)
from grantcompass.storage.table_eligibility import EligibilityRuleRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow

IngestStatus = Literal["parsed", "requires_review", "failed", "missing"]
MissingCode = Literal["attachment_missing", "download_url_missing"]
_PDF_PARSER: Final = ("pdf", "1.0.0")
_HWPX_PARSER: Final = ("hwpx", "1.0.0")
ATTACHMENT_TOO_LARGE: Final[DocumentIngestErrorCode] = "attachment_too_large"
INVALID_ATTACHMENT_TYPE: Final[DocumentIngestErrorCode] = "invalid_attachment_type"
ATTACHMENT_NOT_FOUND: Final = "attachment_not_found"
NOTICE_VERSION_NOT_FOUND: Final = "notice_version_not_found"
DOCUMENT_BLOCK_NOT_FOUND: Final = "document_block_not_found"


@dataclass(frozen=True, slots=True)
class DocumentIngestOutcome:
    """Stable result of one flushed, caller-transaction-owned transition."""

    attachment_id: int
    status: IngestStatus
    content_hash: str | None
    error_code: str | None


class DocumentIngestor:
    """Parse attachments and flush evidence without committing the caller's session."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        max_bytes: int = MAX_ATTACHMENT_BYTES,
        pdf_parser: PdfParser | None = None,
        hwpx_parser: HwpxParser | None = None,
    ) -> None:
        """Bind a caller-owned session and immutable parser boundaries."""
        self._session: AsyncSession = session
        self._max_bytes: int = max_bytes
        self._pdf_parser: PdfParser = pdf_parser or PdfParser()
        self._hwpx_parser: HwpxParser = hwpx_parser or HwpxParser()

    async def ingest(
        self,
        attachment_id: int,
        content: bytes,
        filename: str,
    ) -> DocumentIngestOutcome:
        """Parse bytes off-loop and flush parsed or failed state atomically."""
        attachment = await self._attachment(attachment_id)
        if len(content) > self._max_bytes:
            raise DocumentIngestError(ATTACHMENT_TOO_LARGE)
        parser, parser_name, parser_version = self._parser_for(filename)
        content_hash = sha256(content).hexdigest()
        try:
            parsed = await run_sync(
                parser.parse,
                str(attachment_id),
                content,
                filename,
            )
        except DocumentParseError as error:
            await self._remove_document_evidence(attachment.id, delete_documents=True)
            outcome = DocumentIngestOutcome(attachment_id, "failed", content_hash, error.code)
            self._set_attachment_state(
                attachment,
                outcome,
                parser_name,
                parser_version,
            )
            await self._session.flush()
            return outcome
        return await self._store_parsed(attachment, parsed)

    async def mark_missing(
        self,
        attachment_id: int,
        reason: MissingCode,
    ) -> DocumentIngestOutcome:
        """Flush a reviewable missing state without fabricating parsed content."""
        attachment = await self._attachment(attachment_id)
        await self._remove_document_evidence(attachment.id, delete_documents=True)
        outcome = DocumentIngestOutcome(attachment_id, "missing", None, reason)
        self._set_attachment_state(attachment, outcome, None, None)
        await self._session.flush()
        return outcome

    async def mark_failed(
        self,
        attachment_id: int,
        reason: str,
    ) -> DocumentIngestOutcome:
        """Flush a reviewable download or analysis failure state."""
        attachment = await self._attachment(attachment_id)
        await self._remove_document_evidence(attachment.id, delete_documents=True)
        outcome = DocumentIngestOutcome(attachment_id, "failed", None, reason)
        self._set_attachment_state(attachment, outcome, None, None)
        await self._session.flush()
        return outcome

    async def _attachment(self, attachment_id: int) -> AttachmentRow:
        attachment = await self._session.get(AttachmentRow, attachment_id)
        if attachment is None:
            raise LookupError(ATTACHMENT_NOT_FOUND)
        return attachment

    def _parser_for(self, filename: str) -> tuple[PdfParser | HwpxParser, str, str]:
        match PurePath(filename).suffix.casefold():
            case ".pdf":
                return self._pdf_parser, *_PDF_PARSER
            case ".hwpx":
                return self._hwpx_parser, *_HWPX_PARSER
            case _:
                raise DocumentIngestError(INVALID_ATTACHMENT_TYPE)

    async def _store_parsed(
        self,
        attachment: AttachmentRow,
        parsed: ParsedDocument,
    ) -> DocumentIngestOutcome:
        warning = parsed.warnings[0] if parsed.warnings else None
        status: IngestStatus = "requires_review" if warning is not None else "parsed"
        outcome = DocumentIngestOutcome(attachment.id, status, parsed.content_hash, warning)
        self._set_attachment_state(
            attachment,
            outcome,
            parsed.parser_name,
            parsed.parser_version,
        )
        document = await self._replace_document(attachment.id, parsed)
        blocks = [
            DocumentBlockRow(
                document_id=document.id,
                ordinal=block.ordinal,
                kind=block.kind,
                text=block.text,
                page=block.page,
                section_path=block.section_path,
                table_ref=block.table_ref,
                source_block_id=str(block.block_id),
                bbox_json=(
                    json.dumps(block.bbox, separators=(",", ":"))
                    if block.bbox is not None
                    else None
                ),
                confidence=block.confidence,
                provenance=block.provenance,
            )
            for block in parsed.blocks
        ]
        self._session.add_all(blocks)
        await self._session.flush()
        await self._persist_rule_candidates(attachment, document, parsed, blocks)
        return outcome

    async def _persist_rule_candidates(
        self,
        attachment: AttachmentRow,
        document: DocumentRow,
        parsed: ParsedDocument,
        blocks: list[DocumentBlockRow],
    ) -> None:
        rules = RegexRuleCandidateProvider().extract(parsed)
        if not rules:
            if attachment.parse_error_code is None:
                attachment.parse_error_code = "no_rule_candidates"
            attachment.requires_review = True
            await self._session.flush()
            return
        notice = await self._session.get(NoticeVersionRow, attachment.notice_version_id)
        if notice is None:
            raise LookupError(NOTICE_VERSION_NOT_FOUND)
        block_rows = {row.source_block_id: row for row in blocks}
        for rule in rules:
            rule_row = EligibilityRuleRow(
                program_id=notice.program_id,
                kind=rule.kind.value,
                operator=rule.operator,
                expected_json=json.dumps(
                    rule.expected_value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                required=rule.required,
                review_status=ReviewStatus.REVIEW_REQUIRED.value,
                rule_version=rule.rule_version,
                source_document_id=document.id,
            )
            self._session.add(rule_row)
            await self._session.flush()
            for evidence in rule.evidence:
                block_row = block_rows.get(str(evidence.block_id))
                if block_row is None:
                    raise LookupError(DOCUMENT_BLOCK_NOT_FOUND)
                evidence_row = EvidenceRow(
                    document_id=document.id,
                    block_id=block_row.id,
                    source_url=notice.detail_url,
                    page=evidence.page,
                    section_path=evidence.section_path,
                    quote=evidence.quote,
                    content_hash=evidence.content_hash,
                )
                self._session.add(evidence_row)
                await self._session.flush()
                _ = await self._session.execute(
                    rule_evidence.insert().values(
                        rule_id=rule_row.id,
                        evidence_id=evidence_row.id,
                    )
                )
        attachment.requires_review = True
        await self._session.flush()

    async def _replace_document(
        self,
        attachment_id: int,
        parsed: ParsedDocument,
    ) -> DocumentRow:
        documents = list(
            await self._session.scalars(
                select(DocumentRow)
                .where(DocumentRow.attachment_id == attachment_id)
                .order_by(DocumentRow.id)
            )
        )
        if documents:
            document = documents[0]
            document.parser_name = parsed.parser_name
            document.parser_version = parsed.parser_version
            document.content_hash = parsed.content_hash
            document.parsed_at = datetime.now(UTC)
            document.warning_json = json.dumps(parsed.warnings, separators=(",", ":"))
            await self._remove_document_evidence(attachment_id, delete_documents=False)
            for duplicate in documents[1:]:
                await self._session.delete(duplicate)
            return document
        document = DocumentRow(
            attachment_id=attachment_id,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            content_hash=parsed.content_hash,
            parsed_at=datetime.now(UTC),
            warning_json=json.dumps(parsed.warnings, separators=(",", ":")),
        )
        self._session.add(document)
        await self._session.flush()
        return document

    async def _remove_document_evidence(
        self,
        attachment_id: int,
        *,
        delete_documents: bool,
    ) -> None:
        document_ids = select(DocumentRow.id).where(DocumentRow.attachment_id == attachment_id)
        block_ids = select(DocumentBlockRow.id).where(
            DocumentBlockRow.document_id.in_(document_ids)
        )
        evidence_ids = select(EvidenceRow.id).where(EvidenceRow.block_id.in_(block_ids))
        generated_rule_ids = select(EligibilityRuleRow.id).where(
            EligibilityRuleRow.source_document_id.in_(document_ids)
        )
        _ = await self._session.execute(
            delete(rule_evidence).where(rule_evidence.c.rule_id.in_(generated_rule_ids))
        )
        _ = await self._session.execute(
            delete(EligibilityRuleRow).where(EligibilityRuleRow.id.in_(generated_rule_ids))
        )
        _ = await self._session.execute(
            delete(rule_evidence).where(rule_evidence.c.evidence_id.in_(evidence_ids))
        )
        _ = await self._session.execute(delete(EvidenceRow).where(EvidenceRow.id.in_(evidence_ids)))
        _ = await self._session.execute(
            delete(DocumentBlockRow).where(DocumentBlockRow.document_id.in_(document_ids))
        )
        if delete_documents:
            _ = await self._session.execute(
                delete(DocumentRow).where(DocumentRow.attachment_id == attachment_id)
            )

    @staticmethod
    def _set_attachment_state(
        attachment: AttachmentRow,
        outcome: DocumentIngestOutcome,
        parser_name: str | None,
        parser_version: str | None,
    ) -> None:
        attachment.parse_status = outcome.status
        attachment.content_hash = outcome.content_hash
        attachment.parse_error_code = outcome.error_code
        attachment.parser_name = parser_name
        attachment.parser_version = parser_version
        attachment.requires_review = outcome.status != "parsed"


__all__ = ["DocumentIngestError", "DocumentIngestOutcome", "DocumentIngestor"]
