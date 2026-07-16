"""Transactional async repositories for canonical persistence."""

from datetime import datetime
from typing import override

from anyio.lowlevel import checkpoint
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.domain.programs import (
    CanonicalProgramView,
    FieldConflict,
    IngestResult,
    MergeCandidate,
    NoticeVersionId,
    ProgramId,
    RawNotice,
    has_complete_merge_identity,
    storage_key_for,
)
from grantcompass.domain.source_runs import SourceRunFailure, SourceRunId, SourceRunSuccess
from grantcompass.storage.notice_ingest import NoticeIngestor
from grantcompass.storage.notice_queries import (
    find_exact_program,
    read_current_version_id,
    read_field_conflicts,
    read_merge_candidates,
    read_notice_sources,
    read_program_view,
)
from grantcompass.storage.table_programs import (
    NoticeVersionRow,
    SourceRunRow,
)

_MAX_INGEST_ATTEMPTS = 3


class IngestRaceExhaustedError(RuntimeError):
    """Stable failure after bounded canonical/source race reconciliation."""

    @override
    def __str__(self) -> str:
        """Return a storage-safe diagnostic without raw database details."""
        return "Concurrent notice ingestion could not be reconciled"


class ProgramRepository:
    """Persist canonical programs and immutable source notice versions."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind repository operations to one caller-owned async session."""
        self._session: AsyncSession = session

    async def start_source_run(self, source: SourceName, started_at: datetime) -> SourceRunId:
        """Create and commit a visible running source record."""
        async with self._session.begin():
            run = SourceRunRow(
                source=source.value,
                started_at=started_at,
                finished_at=None,
                status="running",
                item_count=0,
                response_hash=None,
                error_code=None,
                error_message=None,
            )
            self._session.add(run)
            await self._session.flush()
            return SourceRunId(run.id)

    async def complete_source_run(
        self,
        run_id: SourceRunId,
        outcome: SourceRunSuccess,
    ) -> None:
        """Commit a successful source-run transition."""
        async with self._session.begin():
            run = (
                await self._session.scalars(select(SourceRunRow).where(SourceRunRow.id == run_id))
            ).one()
            run.status = "succeeded"
            run.finished_at = outcome.finished_at
            run.item_count = outcome.item_count
            run.response_hash = outcome.response_hash

    async def fail_source_run(
        self,
        run_id: SourceRunId,
        outcome: SourceRunFailure,
    ) -> None:
        """Commit a failed source-run transition while preserving stored notices."""
        async with self._session.begin():
            run = (
                await self._session.scalars(select(SourceRunRow).where(SourceRunRow.id == run_id))
            ).one()
            run.status = "failed"
            run.finished_at = outcome.finished_at
            run.item_count = outcome.item_count
            run.response_hash = outcome.response_hash
            run.error_code = outcome.error_code
            run.error_message = outcome.error_message

    async def upsert_notice(self, raw: RawNotice, collected_at: datetime) -> IngestResult:
        """Atomically persist one idempotent source notice snapshot."""
        attempts_remaining = _MAX_INGEST_ATTEMPTS
        while attempts_remaining > 0:
            try:
                return await NoticeIngestor(self._session).upsert(raw, collected_at)
            except IntegrityError:
                await self._session.rollback()
                attempts_remaining -= 1
                if attempts_remaining == 0:
                    raise IngestRaceExhaustedError from None
                await checkpoint()
        raise IngestRaceExhaustedError

    async def find_merge_candidate(self, raw: RawNotice) -> ProgramId | None:
        """Return a merge target only for the exact conservative identity."""
        if not has_complete_merge_identity(raw):
            return None
        return await find_exact_program(self._session, storage_key_for(raw))

    async def current_notice_version(
        self,
        source: SourceName,
        source_notice_id: str,
    ) -> NoticeVersionId | None:
        """Return the explicit current version for one source identity."""
        return await read_current_version_id(self._session, source, source_notice_id)

    async def get_program(self, program_id: ProgramId) -> CanonicalProgramView:
        """Return conflict-aware canonical state without hidden source precedence."""
        return await read_program_view(self._session, program_id)

    async def notice_sources(self, program_id: ProgramId) -> frozenset[SourceName]:
        """Return every source retained for one canonical program."""
        return await read_notice_sources(self._session, program_id)

    async def get_field_conflicts(
        self,
        program_id: ProgramId,
    ) -> tuple[FieldConflict, ...]:
        """Return current source-specific field disagreements."""
        return await read_field_conflicts(self._session, program_id)

    async def list_merge_candidates(self) -> tuple[MergeCandidate, ...]:
        """Return review-only candidates that were never automatically merged."""
        return await read_merge_candidates(self._session)

    async def count_notice_versions(self, program_id: ProgramId) -> int:
        """Count immutable snapshots currently stored for one program."""
        result = await self._session.execute(
            select(func.count(NoticeVersionRow.id)).where(NoticeVersionRow.program_id == program_id)
        )
        return result.scalar_one()
