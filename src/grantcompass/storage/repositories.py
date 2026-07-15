"""Transactional async repositories for canonical persistence."""

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.programs import (
    IngestResult,
    NoticeVersionId,
    ProgramId,
    RawNotice,
    canonical_key_for,
)
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, ProgramRow


class ProgramRepository:
    """Persist canonical programs and immutable source notice versions."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind repository operations to one caller-owned async session."""
        self._session: AsyncSession = session

    async def upsert_notice(self, raw: RawNotice, collected_at: datetime) -> IngestResult:
        """Atomically persist one idempotent source notice snapshot."""
        async with self._session.begin():
            latest_statement = (
                select(NoticeVersionRow)
                .where(
                    NoticeVersionRow.source == raw.source.value,
                    NoticeVersionRow.source_notice_id == raw.source_notice_id,
                )
                .order_by(NoticeVersionRow.id.desc())
                .limit(1)
            )
            latest = await self._session.scalar(latest_statement)
            content_hash = raw.content_hash()
            if latest is not None and latest.content_hash == content_hash:
                return IngestResult(
                    program_id=ProgramId(latest.program_id),
                    notice_version_id=NoticeVersionId(latest.id),
                    notice_version_created=False,
                )

            if latest is not None:
                program_id = latest.program_id
            else:
                canonical_key = canonical_key_for(raw)
                program = await self._session.scalar(
                    select(ProgramRow).where(ProgramRow.canonical_key == canonical_key)
                )
                if program is None:
                    program = ProgramRow(
                        canonical_key=canonical_key,
                        title=" ".join(raw.title.split()),
                        organization=raw.organization,
                        application_start=raw.application_start,
                        application_end=raw.application_end,
                        created_at=collected_at,
                        updated_at=collected_at,
                    )
                    self._session.add(program)
                    await self._session.flush()
                program_id = program.id

            version = NoticeVersionRow(
                program_id=program_id,
                source=raw.source.value,
                source_notice_id=raw.source_notice_id,
                content_hash=content_hash,
                detail_url=str(raw.detail_url),
                raw_payload_json=json.dumps(
                    raw.raw_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                collected_at=collected_at,
            )
            self._session.add(version)
            await self._session.flush()
            for attachment in raw.attachments:
                self._session.add(
                    AttachmentRow(
                        notice_version_id=version.id,
                        filename=attachment.filename,
                        download_url=str(attachment.download_url),
                        media_type=attachment.media_type,
                        content_hash=attachment.content_hash,
                        local_path=None,
                        parse_status="pending",
                    )
                )
            return IngestResult(
                program_id=ProgramId(program_id),
                notice_version_id=NoticeVersionId(version.id),
                notice_version_created=True,
            )

    async def count_notice_versions(self, program_id: ProgramId) -> int:
        """Count immutable snapshots currently stored for one program."""
        result = await self._session.execute(
            select(func.count(NoticeVersionRow.id)).where(NoticeVersionRow.program_id == program_id)
        )
        await self._session.commit()
        return result.scalar_one()
