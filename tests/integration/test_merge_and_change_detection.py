from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import FinalStatus, ReviewStatus, SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import RawNotice
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_eligibility import ApplicantProfileRow, AssessmentRow


@dataclass(frozen=True, slots=True)
class _NoticeValues:
    title: str = "2026년 초기창업패키지 창업기업 모집공고"
    organization: str = "창업진흥원"
    deadline: date = date(2026, 7, 31)
    summary: str = "초기 창업기업 지원"


_DEFAULT_NOTICE = _NoticeValues()


def _notice(
    source: SourceName,
    notice_id: str,
    values: _NoticeValues = _DEFAULT_NOTICE,
) -> RawNotice:
    return RawNotice(
        source=source,
        source_notice_id=notice_id,
        title=values.title,
        organization=values.organization,
        summary=values.summary,
        application_start=date(2026, 7, 1),
        application_end=values.deadline,
        detail_url=HttpUrl(f"https://example.invalid/{source.value}/{notice_id}"),
        raw_payload=freeze_json_object({"source_id": notice_id, "summary": values.summary}),
    )


@pytest.mark.anyio
async def test_exact_cross_source_identity_merges_and_preserves_sources(
    program_repository: ProgramRepository,
    now: datetime,
) -> None:
    # Given: one persisted official notice.
    first = await program_repository.upsert_notice(_notice(SourceName.KSTARTUP, "K-001"), now)

    # When: another source publishes the exact normalized title, organization, and deadline.
    second = await program_repository.upsert_notice(_notice(SourceName.BIZINFO, "PBLN_001"), now)

    # Then: both immutable notices belong to one program and remain inspectable by source.
    assert second.program_id == first.program_id
    assert await program_repository.notice_sources(first.program_id) == frozenset(
        {SourceName.KSTARTUP, SourceName.BIZINFO}
    )
    assert await program_repository.count_notice_versions(first.program_id) == 2


@pytest.mark.anyio
async def test_title_similarity_only_creates_separate_program_and_review_candidate(
    program_repository: ProgramRepository,
    now: datetime,
) -> None:
    # Given: one source notice already has a canonical program.
    first = await program_repository.upsert_notice(_notice(SourceName.KSTARTUP, "K-001"), now)
    similar = _notice(
        SourceName.BIZINFO,
        "PBLN_002",
        replace(
            _DEFAULT_NOTICE,
            organization="다른 수행기관",
            deadline=date(2026, 8, 1),
        ),
    )

    # When: only the highly similar title matches.
    second = await program_repository.upsert_notice(similar, now)

    # Then: automatic merge is refused and an unresolved review candidate is recorded.
    candidates = await program_repository.list_merge_candidates()
    assert second.program_id != first.program_id
    assert len(candidates) == 1
    assert {candidates[0].left_program_id, candidates[0].right_program_id} == {
        first.program_id,
        second.program_id,
    }
    assert candidates[0].title_similarity == 1.0
    assert candidates[0].status == "pending"


@pytest.mark.anyio
async def test_changed_cross_source_deadline_creates_typed_conflict(
    program_repository: ProgramRepository,
    now: datetime,
) -> None:
    # Given: two sources were conservatively merged while their identity fields agreed.
    first = await program_repository.upsert_notice(_notice(SourceName.KSTARTUP, "K-001"), now)
    _ = await program_repository.upsert_notice(_notice(SourceName.BIZINFO, "PBLN_001"), now)
    changed = _notice(
        SourceName.BIZINFO,
        "PBLN_001",
        replace(_DEFAULT_NOTICE, deadline=date(2026, 8, 7)),
    )

    # When: one source later changes the deadline.
    result = await program_repository.upsert_notice(changed, now + timedelta(hours=1))

    # Then: neither source wins silently and the exact source values are inspectable.
    conflicts = await program_repository.get_field_conflicts(first.program_id)
    deadline_conflict = next(item for item in conflicts if item.field_name == "application_end")
    assert result.program_id == first.program_id
    assert {(value.source, value.value) for value in deadline_conflict.values} == {
        (SourceName.KSTARTUP, "2026-07-31"),
        (SourceName.BIZINFO, "2026-08-07"),
    }


@pytest.mark.anyio
async def test_notice_change_records_impact_and_reopens_review_without_losing_result(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    now: datetime,
) -> None:
    # Given: a reviewed assessment and its unchanged automatic result.
    stored = await program_repository.upsert_notice(_notice(SourceName.KSTARTUP, "K-001"), now)
    profile = ApplicantProfileRow(
        display_name="테스트 기업",
        founded_on=date(2025, 1, 1),
        regions_json="[]",
        representative_birth_year=None,
        industries_json="[]",
        performance_json="{}",
        benefit_history_json="[]",
        created_at=now,
    )
    db_session.add(profile)
    await db_session.flush()
    assessment = AssessmentRow(
        program_id=stored.program_id,
        profile_id=profile.id,
        final_status=FinalStatus.ELIGIBLE.value,
        review_status=ReviewStatus.REVIEWED.value,
        rule_version="rules-1",
        assessed_at=now,
    )
    db_session.add(assessment)
    await db_session.commit()
    changed = _notice(
        SourceName.KSTARTUP,
        "K-001",
        replace(_DEFAULT_NOTICE, summary="자격조건 변경"),
    )

    # When: source content changes after review.
    result = await program_repository.upsert_notice(changed, now + timedelta(hours=1))

    # Then: the change links both versions and impact while preserving the automatic decision.
    reopened = await db_session.scalar(
        select(AssessmentRow).where(AssessmentRow.id == assessment.id)
    )
    assert result.change_set is not None
    assert result.change_set.changed_fields == ("summary",)
    assert result.change_set.previous_version_id == stored.notice_version_id
    assert result.change_set.current_version_id == result.notice_version_id
    assert result.impacted_assessment_ids == (assessment.id,)
    assert reopened is not None
    assert reopened.review_status == ReviewStatus.REVIEW_REQUIRED.value
    assert reopened.final_status == FinalStatus.ELIGIBLE.value
    assert reopened.rule_version == "rules-1"


@pytest.mark.anyio
async def test_identical_reingest_does_not_create_change_or_reopen_review(
    program_repository: ProgramRepository,
    now: datetime,
) -> None:
    # Given: one stored source snapshot.
    raw = _notice(SourceName.KSTARTUP, "K-001")
    _ = await program_repository.upsert_notice(raw, now)

    # When: identical source content is collected again.
    result = await program_repository.upsert_notice(raw, now + timedelta(hours=1))

    # Then: the idempotent result carries no change impact.
    assert result.notice_version_created is False
    assert result.change_set is None
    assert result.impacted_assessment_ids == ()


def test_fixture_time_is_explicitly_utc() -> None:
    # Given: a boundary timestamp used by storage tests.
    timestamp = datetime(2026, 7, 15, tzinfo=UTC)

    # When: its offset is inspected.
    offset = timestamp.utcoffset()

    # Then: the test contract never depends on the workstation timezone.
    assert offset is not None
    assert offset.total_seconds() == 0
