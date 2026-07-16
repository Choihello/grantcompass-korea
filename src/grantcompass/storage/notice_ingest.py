"""Atomic canonical notice ingestion and analysis orchestration."""

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.ids import NoticeVersionId, ProgramId
from grantcompass.domain.json_types import thaw_json_object
from grantcompass.domain.programs import (
    IngestResult,
    RawNotice,
    has_complete_merge_identity,
    storage_key_for,
)
from grantcompass.storage.notice_analysis import NoticeAnalyzer, VersionTransition
from grantcompass.storage.notice_queries import find_exact_program
from grantcompass.storage.notice_snapshots import NoticeSnapshot
from grantcompass.storage.notice_state import point_to_version, read_current_version
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, ProgramRow


@dataclass(frozen=True, slots=True)
class IngestContext:
    """Boundary values shared by one atomic ingestion."""

    raw: RawNotice
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class VersionInsert:
    """Inputs for one immutable notice-version insertion."""

    context: IngestContext
    program_id: ProgramId
    snapshot: NoticeSnapshot


class NoticeIngestor:
    """Persist one source snapshot within a caller-owned async session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session whose transaction encloses every derived record."""
        self._session: AsyncSession = session

    async def upsert(self, raw: RawNotice, collected_at: datetime) -> IngestResult:
        """Persist idempotently and atomically derive merge and change analysis."""
        async with self._session.begin():
            context = IngestContext(raw=raw, collected_at=collected_at)
            existing, current = await self._find_versions(raw)
            if existing is not None and current is not None and existing.id == current.id:
                return IngestResult(
                    program_id=ProgramId(existing.program_id),
                    notice_version_id=NoticeVersionId(existing.id),
                    notice_version_created=False,
                )
            linked = current if current is not None else existing
            program_id, created_program = await self._resolve_program(context, linked)
            snapshot = NoticeSnapshot.from_raw(raw)
            version = existing
            if version is None:
                version = await self._insert_version(
                    VersionInsert(context=context, program_id=program_id, snapshot=snapshot)
                )
            await point_to_version(self._session, version)
            analyzer = NoticeAnalyzer(self._session, collected_at)
            if created_program:
                await analyzer.record_merge_candidate(program_id, raw)
            change_set = None
            impacted_ids = ()
            if current is not None:
                change_set, impacted_ids = await analyzer.record_change(
                    VersionTransition(
                        program_id=program_id,
                        previous=current,
                        current=version,
                        current_snapshot=snapshot,
                    )
                )
            await analyzer.sync_conflicts(program_id)
            return IngestResult(
                program_id=program_id,
                notice_version_id=NoticeVersionId(version.id),
                notice_version_created=existing is None,
                change_set=change_set,
                impacted_assessment_ids=impacted_ids,
            )

    async def _find_versions(
        self,
        raw: RawNotice,
    ) -> tuple[NoticeVersionRow | None, NoticeVersionRow | None]:
        identity = (
            NoticeVersionRow.source == raw.source.value,
            NoticeVersionRow.source_notice_id == raw.source_notice_id,
        )
        existing = await self._session.scalar(
            select(NoticeVersionRow).where(
                *identity,
                NoticeVersionRow.content_hash == raw.content_hash(),
            )
        )
        current = await read_current_version(self._session, raw.source, raw.source_notice_id)
        return existing, current

    async def _resolve_program(
        self,
        context: IngestContext,
        latest: NoticeVersionRow | None,
    ) -> tuple[ProgramId, bool]:
        if latest is not None:
            return ProgramId(latest.program_id), False
        if has_complete_merge_identity(context.raw):
            exact_id = await find_exact_program(self._session, storage_key_for(context.raw))
            if exact_id is not None:
                return exact_id, False
        row = ProgramRow(
            canonical_key=storage_key_for(context.raw),
            title=" ".join(context.raw.title.split()),
            organization=context.raw.organization,
            application_start=context.raw.application_start,
            application_end=context.raw.application_end,
            created_at=context.collected_at,
            updated_at=context.collected_at,
        )
        self._session.add(row)
        await self._session.flush()
        return ProgramId(row.id), True

    async def _insert_version(self, insert: VersionInsert) -> NoticeVersionRow:
        raw = insert.context.raw
        version = NoticeVersionRow(
            program_id=insert.program_id,
            source=raw.source.value,
            source_notice_id=raw.source_notice_id,
            content_hash=raw.content_hash(),
            detail_url=str(raw.detail_url),
            raw_payload_json=json.dumps(
                thaw_json_object(raw.raw_payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            normalized_json=insert.snapshot.model_dump_json(),
            collected_at=insert.context.collected_at,
        )
        self._session.add(version)
        await self._session.flush()
        self._session.add_all(
            AttachmentRow(
                notice_version_id=version.id,
                filename=item.filename,
                download_url=str(item.download_url),
                media_type=item.media_type,
                content_hash=item.content_hash,
                local_path=None,
                parse_status="pending",
            )
            for item in raw.attachments
        )
        return version
