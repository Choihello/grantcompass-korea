from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from grantcompass.documents.ingest import DocumentIngestor
from grantcompass.storage.table_documents import DocumentBlockRow, DocumentRow, EvidenceRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, ProgramRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"


async def _attachment_row(session: AsyncSession, identity: str = "fixture-1") -> AttachmentRow:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    async with session.begin():
        program = ProgramRow(
            canonical_key=identity,
            title="Fixture",
            organization=None,
            application_start=None,
            application_end=None,
            created_at=now,
            updated_at=now,
            reference_date=now.date(),
            reference_date_source="collected_at_fallback",
        )
        session.add(program)
        await session.flush()
        notice = NoticeVersionRow(
            program_id=program.id,
            source="kstartup",
            source_notice_id=identity,
            content_hash="0" * 64,
            detail_url="https://example.test/notice",
            raw_payload_json="{}",
            normalized_json="{}",
            collected_at=now,
            announcement_date=None,
            reference_date=now.date(),
            reference_date_source="collected_at_fallback",
        )
        session.add(notice)
        await session.flush()
        row = AttachmentRow(
            notice_version_id=notice.id,
            filename="notice.pdf",
            download_url="https://files.example.test/notice.pdf",
            media_type="application/pdf",
            content_hash=None,
            local_path=None,
            parse_status="pending",
            parse_error_code=None,
            requires_review=False,
            parser_name=None,
            parser_version=None,
        )
        session.add(row)
        await session.flush()
        return row


@pytest.mark.anyio
async def test_ingestor_persists_parsed_document(db_session: AsyncSession) -> None:
    # Given: a pending attachment and valid text PDF.
    row = await _attachment_row(db_session)
    content = (FIXTURES / "text-layer.pdf").read_bytes()
    ingestor = DocumentIngestor(db_session)

    # When: content is ingested.
    outcome = await ingestor.ingest(row.id, content, "notice.pdf")

    # Then: parser provenance and exact content hash are transactional.
    await db_session.refresh(row)
    document = (await db_session.scalars(select(DocumentRow))).one()
    assert outcome.status == "parsed"
    assert row.parse_status == "parsed"
    assert row.content_hash == document.content_hash
    assert row.parser_name == "pdf"


@pytest.mark.anyio
async def test_parser_failure_and_missing_are_reviewable(db_session: AsyncSession) -> None:
    # Given: two pending attachment rows.
    broken = await _attachment_row(db_session, "broken")
    missing = await _attachment_row(db_session, "missing")
    ingestor = DocumentIngestor(db_session)

    # When: one parse fails and one download is missing.
    failed = await ingestor.ingest(broken.id, b"not-a-pdf", "notice.pdf")
    absent = await ingestor.mark_missing(missing.id, "download_url_missing")

    # Then: neither is promoted to parsed and both retain safe evidence.
    await db_session.refresh(broken)
    await db_session.refresh(missing)
    assert (failed.status, broken.parse_error_code, broken.requires_review) == (
        "failed",
        "invalid_pdf",
        True,
    )
    assert (absent.status, missing.parse_error_code, missing.requires_review) == (
        "missing",
        "download_url_missing",
        True,
    )


@pytest.mark.anyio
async def test_ingestor_leaves_commit_and_rollback_to_caller(db_session: AsyncSession) -> None:
    # Given: a committed pending attachment and caller-owned session.
    row = await _attachment_row(db_session, "rollback")
    attachment_id = row.id
    content = (FIXTURES / "text-layer.pdf").read_bytes()

    # When: ingestion flushes and the caller rolls its transaction back.
    _ = await DocumentIngestor(db_session).ingest(attachment_id, content, "notice.pdf")
    assert db_session.in_transaction()
    await db_session.rollback()

    # Then: the pending state remains and no parsed document was committed.
    restored = await db_session.get(AttachmentRow, attachment_id)
    document_count = await db_session.scalar(
        select(func.count(DocumentRow.id)).where(DocumentRow.attachment_id == attachment_id)
    )
    assert restored is not None
    assert restored.parse_status == "pending"
    assert document_count == 0


@pytest.mark.anyio
async def test_reparse_replaces_stale_document_blocks(db_session: AsyncSession) -> None:
    # Given: an attachment already parsed with text and table blocks.
    row = await _attachment_row(db_session, "reparse")
    text_content = (FIXTURES / "text-layer.pdf").read_bytes()
    scanned_content = (FIXTURES / "scanned-page.pdf").read_bytes()
    ingestor = DocumentIngestor(db_session)
    _ = await ingestor.ingest(row.id, text_content, "notice.pdf")
    initial_count = await db_session.scalar(select(func.count(DocumentBlockRow.id)))

    # When: the same attachment is reparsed from a deficient scanned PDF.
    outcome = await ingestor.ingest(row.id, scanned_content, "notice.pdf")

    # Then: old blocks are removed and the reviewable warning is durable.
    document_count = await db_session.scalar(
        select(func.count(DocumentRow.id)).where(DocumentRow.attachment_id == row.id)
    )
    final_count = await db_session.scalar(select(func.count(DocumentBlockRow.id)))
    assert initial_count is not None
    assert initial_count > 0
    assert outcome.status == "requires_review"
    assert document_count == 1
    assert final_count == 0


@pytest.mark.anyio
async def test_parse_failure_removes_stale_document_evidence(db_session: AsyncSession) -> None:
    # Given: parsed evidence for an attachment.
    row = await _attachment_row(db_session, "parsed-failed")
    content = (FIXTURES / "text-layer.pdf").read_bytes()
    ingestor = DocumentIngestor(db_session)
    _ = await ingestor.ingest(row.id, content, "notice.pdf")
    block = (await db_session.scalars(select(DocumentBlockRow))).first()
    assert block is not None
    db_session.add(
        EvidenceRow(
            document_id=block.document_id,
            block_id=block.id,
            source_url=row.download_url,
            page=block.page,
            section_path=block.section_path,
            quote=block.text,
            content_hash=row.content_hash,
        )
    )
    await db_session.flush()

    # When: a subsequent parse fails.
    outcome = await ingestor.ingest(row.id, b"not-a-pdf", "notice.pdf")

    # Then: stale parsed rows and their evidence are removed atomically.
    assert outcome.status == "failed"
    assert await db_session.scalar(select(func.count(DocumentRow.id))) == 0
    assert await db_session.scalar(select(func.count(DocumentBlockRow.id))) == 0
    assert await db_session.scalar(select(func.count(EvidenceRow.id))) == 0


@pytest.mark.anyio
async def test_missing_transition_removes_stale_document(db_session: AsyncSession) -> None:
    # Given: a successfully parsed attachment.
    row = await _attachment_row(db_session, "parsed-missing")
    content = (FIXTURES / "text-layer.pdf").read_bytes()
    ingestor = DocumentIngestor(db_session)
    _ = await ingestor.ingest(row.id, content, "notice.pdf")

    # When: its source later reports the attachment missing.
    outcome = await ingestor.mark_missing(row.id, "attachment_missing")

    # Then: no stale document can support a future eligibility decision.
    assert outcome.status == "missing"
    assert await db_session.scalar(select(func.count(DocumentRow.id))) == 0
    assert await db_session.scalar(select(func.count(DocumentBlockRow.id))) == 0
