"""Transactional institution-owned notice registration."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.documents.ingest import DocumentIngestor
from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import IngestResult, RawNotice
from grantcompass.storage.audit_json import dump_audit_json, validate_attribution
from grantcompass.storage.notice_ingest import NoticeIngestor
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_programs import AttachmentRow

_MANUAL_SOURCE_REQUIRED = "manual_source_required"
_DOCUMENT_PAIR_REQUIRED = "document_pair_required"


@dataclass(frozen=True, slots=True)
class ManualNoticeCommand:
    """Validated inputs for one attributed institution-owned notice."""

    notice: RawNotice
    collected_at: datetime
    actor: str
    reason: str
    document_content: bytes | None = None
    document_filename: str | None = None


async def create_manual_notice(
    session: AsyncSession,
    command: ManualNoticeCommand,
) -> IngestResult:
    """Create, parse, and attribute one manual notice atomically."""
    if command.notice.source is not SourceName.MANUAL:
        raise ValueError(_MANUAL_SOURCE_REQUIRED)
    actor, reason = validate_attribution(command.actor, command.reason, command.collected_at)
    attachment_supplied = command.document_content is not None
    if attachment_supplied != (command.document_filename is not None):
        raise ValueError(_DOCUMENT_PAIR_REQUIRED)
    async with session.begin():
        result = await NoticeIngestor(session).upsert_in_transaction(
            command.notice,
            command.collected_at,
        )
        if command.document_content is not None and command.document_filename is not None:
            attachment = (
                await session.scalars(
                    select(AttachmentRow).where(
                        AttachmentRow.notice_version_id == int(result.notice_version_id)
                    )
                )
            ).one()
            _ = await DocumentIngestor(session).ingest(
                attachment.id,
                command.document_content,
                command.document_filename,
            )
        after = freeze_json_object(
            {
                "schema_version": 1,
                "entity_id": int(result.program_id),
                "notice_version_id": int(result.notice_version_id),
                "source": SourceName.MANUAL.value,
            }
        )
        session.add(
            AuditEventRow(
                entity_type="program",
                entity_id=str(int(result.program_id)),
                action="manual_notice",
                actor_name=actor,
                reason=reason,
                before_json=None,
                after_json=dump_audit_json(after),
                created_at=command.collected_at,
            )
        )
        return result


__all__ = ["ManualNoticeCommand", "create_manual_notice"]
