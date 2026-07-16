"""Transactional analysis of source merge candidates, conflicts, and changes."""

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from unicodedata import normalize

from pydantic import TypeAdapter
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import ReviewStatus, SourceName
from grantcompass.domain.ids import AssessmentId, ChangeSetId, NoticeVersionId, ProgramId
from grantcompass.domain.programs import (
    ChangeSet,
    ConflictValue,
    RawNotice,
    canonical_key_from_fields,
)
from grantcompass.storage.notice_snapshots import (
    NoticeSnapshot,
    changed_fields,
    conflict_field_names,
    parse_snapshot,
)
from grantcompass.storage.table_eligibility import AssessmentRow
from grantcompass.storage.table_notice_analysis import (
    ChangeImpactRow,
    ChangeSetRow,
    FieldConflictRow,
    MergeCandidateRow,
)
from grantcompass.storage.table_programs import NoticeVersionRow, ProgramRow

_TITLE_SIMILARITY_THRESHOLD = 0.9
_CONFLICT_VALUES = TypeAdapter(tuple[ConflictValue, ...])


@dataclass(frozen=True, slots=True)
class VersionTransition:
    """Inputs required to persist one source notice change."""

    program_id: ProgramId
    previous: NoticeVersionRow
    current: NoticeVersionRow
    current_snapshot: NoticeSnapshot


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    """Normalized potential duplicate passed to the idempotent row writer."""

    program_id: ProgramId
    candidate_id: int
    similarity: float


class NoticeAnalyzer:
    """Analyze notice state inside a caller-owned ingestion transaction."""

    def __init__(self, session: AsyncSession, detected_at: datetime) -> None:
        """Bind transaction state and the deterministic collection instant."""
        self._session: AsyncSession = session
        self._detected_at: datetime = detected_at

    async def record_merge_candidate(self, program_id: ProgramId, raw: RawNotice) -> None:
        """Record only high-title-similarity cross-source pairs for review."""
        candidates = (
            await self._session.scalars(
                select(ProgramRow)
                .join(NoticeVersionRow, NoticeVersionRow.program_id == ProgramRow.id)
                .where(
                    ProgramRow.id != program_id,
                    NoticeVersionRow.source != raw.source.value,
                )
                .distinct()
            )
        ).all()
        incoming_title = _normalize_title(raw.title)
        for candidate in candidates:
            candidate_title = _normalize_title(candidate.title)
            similarity = SequenceMatcher(None, incoming_title, candidate_title).ratio()
            if similarity >= _TITLE_SIMILARITY_THRESHOLD:
                await self._insert_candidate(
                    CandidateMatch(
                        program_id=program_id,
                        candidate_id=candidate.id,
                        similarity=similarity,
                    )
                )

    async def _insert_candidate(self, match: CandidateMatch) -> None:
        left_id, right_id = sorted((int(match.program_id), match.candidate_id))
        existing = await self._session.scalar(
            select(MergeCandidateRow).where(
                MergeCandidateRow.left_program_id == left_id,
                MergeCandidateRow.right_program_id == right_id,
            )
        )
        if existing is None:
            self._session.add(
                MergeCandidateRow(
                    left_program_id=left_id,
                    right_program_id=right_id,
                    title_similarity=match.similarity,
                    status="pending",
                    detected_at=self._detected_at,
                )
            )

    async def sync_conflicts(self, program_id: ProgramId) -> None:
        """Replace current conflicts from the latest snapshot of every source identity."""
        snapshots = await self._latest_source_snapshots(program_id)
        _ = await self._session.execute(
            delete(FieldConflictRow).where(FieldConflictRow.program_id == program_id)
        )
        for field_name in conflict_field_names():
            values = tuple(
                ConflictValue(source=source, value=snapshot.conflict_values()[field_name])
                for source, snapshot in sorted(snapshots.items(), key=lambda item: item[0].value)
            )
            if len({item.value for item in values}) > 1:
                self._session.add(
                    FieldConflictRow(
                        program_id=program_id,
                        field_name=field_name,
                        values_json=_CONFLICT_VALUES.dump_json(values).decode(),
                        detected_at=self._detected_at,
                    )
                )
        await self._refresh_consensus_program(program_id, snapshots)

    async def _latest_source_snapshots(
        self,
        program_id: ProgramId,
    ) -> dict[SourceName, NoticeSnapshot]:
        rows = (
            await self._session.scalars(
                select(NoticeVersionRow)
                .where(NoticeVersionRow.program_id == program_id)
                .order_by(NoticeVersionRow.id)
            )
        ).all()
        latest: dict[SourceName, NoticeSnapshot] = {}
        for row in rows:
            snapshot = parse_snapshot(row.normalized_json)
            if snapshot is not None:
                latest[SourceName(row.source)] = snapshot
        return latest

    async def _refresh_consensus_program(
        self,
        program_id: ProgramId,
        snapshots: dict[SourceName, NoticeSnapshot],
    ) -> None:
        if not snapshots:
            return
        program = (
            await self._session.scalars(select(ProgramRow).where(ProgramRow.id == program_id))
        ).one()
        titles = {item.title for item in snapshots.values()}
        organizations = {item.organization for item in snapshots.values()}
        starts = {item.application_start for item in snapshots.values()}
        ends = {item.application_end for item in snapshots.values()}
        if len(titles) == 1:
            program.title = next(iter(titles))
        if len(organizations) == 1:
            program.organization = next(iter(organizations))
        if len(starts) == 1:
            program.application_start = next(iter(starts))
        if len(ends) == 1:
            program.application_end = next(iter(ends))
        new_key = canonical_key_from_fields(
            program.title,
            program.organization,
            program.application_end,
        )
        collision = await self._session.scalar(
            select(ProgramRow.id).where(
                ProgramRow.canonical_key == new_key,
                ProgramRow.id != program_id,
            )
        )
        if collision is None:
            program.canonical_key = new_key
        program.updated_at = self._detected_at

    async def record_change(
        self,
        transition: VersionTransition,
    ) -> tuple[ChangeSet | None, tuple[AssessmentId, ...]]:
        """Persist version differences, impacts, and review reopening."""
        previous_snapshot = parse_snapshot(transition.previous.normalized_json)
        if previous_snapshot is None:
            return None, ()
        fields = changed_fields(previous_snapshot, transition.current_snapshot)
        if not fields:
            return None, ()
        row = ChangeSetRow(
            source=transition.current.source,
            source_notice_id=transition.current.source_notice_id,
            kind="notice_changed",
            changed_fields_json=TypeAdapter(tuple[str, ...]).dump_json(fields).decode(),
            previous_version_id=transition.previous.id,
            current_version_id=transition.current.id,
            detected_at=self._detected_at,
        )
        self._session.add(row)
        await self._session.flush()
        assessment_ids = tuple(
            AssessmentId(item)
            for item in (
                await self._session.scalars(
                    select(AssessmentRow.id).where(
                        AssessmentRow.program_id == transition.program_id
                    )
                )
            ).all()
        )
        self._session.add_all(
            ChangeImpactRow(change_set_id=row.id, assessment_id=item) for item in assessment_ids
        )
        _ = await self._session.execute(
            update(AssessmentRow)
            .where(
                AssessmentRow.id.in_(assessment_ids),
                AssessmentRow.review_status == ReviewStatus.REVIEWED.value,
            )
            .values(review_status=ReviewStatus.REVIEW_REQUIRED.value)
        )
        return (
            ChangeSet(
                id=ChangeSetId(row.id),
                kind=row.kind,
                changed_fields=fields,
                previous_version_id=NoticeVersionId(row.previous_version_id),
                current_version_id=NoticeVersionId(row.current_version_id),
            ),
            assessment_ids,
        )


def _normalize_title(value: str) -> str:
    return " ".join(normalize("NFKC", value).casefold().split())
