from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import FinalStatus, ReviewStatus, SourceName
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_eligibility import ApplicantProfileRow, AssessmentRow
from grantcompass.storage.table_notice_analysis import ChangeSetRow
from tests.factories import NoticeValues, make_notice


@pytest.mark.anyio
async def test_a_to_b_to_a_to_a_reuses_version_and_tracks_current(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    now: datetime,
) -> None:
    # Given: A was assessed, then B became current and the assessment was reviewed again.
    values_a = NoticeValues(summary="A 조건")
    values_b = replace(values_a, summary="B 조건")
    first_a = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-CURRENT-1", values_a), now
    )
    profile = ApplicantProfileRow(
        display_name="가상 기업",
        founded_on=None,
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
        program_id=first_a.program_id,
        profile_id=profile.id,
        final_status=FinalStatus.ELIGIBLE.value,
        review_status=ReviewStatus.REVIEWED.value,
        rule_version="rules-current",
        assessed_at=now,
    )
    db_session.add(assessment)
    await db_session.commit()
    version_b = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-CURRENT-1", values_b),
        now + timedelta(hours=1),
    )
    assessment.review_status = ReviewStatus.REVIEWED.value
    await db_session.commit()

    # When: historical A becomes current and is immediately collected once more.
    reactivated_a = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-CURRENT-1", values_a),
        now + timedelta(hours=2),
    )
    repeated_a = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-CURRENT-1", values_a),
        now + timedelta(hours=3),
    )

    # Then: A is reused, B→A is recorded once, and every public current read resolves A.
    current_id = await program_repository.current_notice_version(SourceName.KSTARTUP, "K-CURRENT-1")
    view = await program_repository.get_program(first_a.program_id)
    assert reactivated_a.notice_version_id == first_a.notice_version_id
    assert reactivated_a.notice_version_created is False
    assert reactivated_a.change_set is not None
    assert reactivated_a.change_set.previous_version_id == version_b.notice_version_id
    assert reactivated_a.change_set.current_version_id == first_a.notice_version_id
    assert reactivated_a.impacted_assessment_ids == (assessment.id,)
    assert repeated_a.change_set is None
    assert repeated_a.impacted_assessment_ids == ()
    assert current_id == first_a.notice_version_id
    assert await program_repository.count_notice_versions(first_a.program_id) == 2
    assert view.summary == "A 조건"
    assert view.conflicts == ()
    await db_session.refresh(assessment)
    assert assessment.review_status == ReviewStatus.REVIEW_REQUIRED.value


@pytest.mark.anyio
async def test_a_to_b_to_a_to_b_records_each_real_transition(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    now: datetime,
) -> None:
    # Given: two immutable snapshots have alternated through A -> B -> A.
    values_a = NoticeValues(summary="A recurring condition")
    values_b = replace(values_a, summary="B recurring condition")
    first_a = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-RECURRING-1", values_a), now
    )
    first_b = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-RECURRING-1", values_b),
        now + timedelta(hours=1),
    )
    second_a = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-RECURRING-1", values_a),
        now + timedelta(hours=2),
    )

    # When: the already-seen B content becomes current again.
    second_b = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-RECURRING-1", values_b),
        now + timedelta(hours=3),
    )

    # Then: version reuse stays idempotent while every pointer transition remains historical.
    rows = (await db_session.scalars(select(ChangeSetRow).order_by(ChangeSetRow.id))).all()
    assert second_a.notice_version_id == first_a.notice_version_id
    assert second_b.notice_version_id == first_b.notice_version_id
    assert second_b.notice_version_created is False
    assert [(row.previous_version_id, row.current_version_id) for row in rows] == [
        (int(first_a.notice_version_id), int(first_b.notice_version_id)),
        (int(first_b.notice_version_id), int(first_a.notice_version_id)),
        (int(first_a.notice_version_id), int(first_b.notice_version_id)),
    ]
    assert (
        await program_repository.current_notice_version(SourceName.KSTARTUP, "K-RECURRING-1")
        == first_b.notice_version_id
    )
