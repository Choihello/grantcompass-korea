from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import FinalStatus, SourceName
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.reverse import ReverseMatchingError, ReverseMatchingErrorCode
from grantcompass.matching.reverse import ReverseMatchingService
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow
from tests.integration.task12_fixtures import (
    REFERENCE_TIME,
    program_id,
    seed_managed_company,
    seed_profile,
    seed_program,
    seed_rule,
)
from tests.integration.task12_reverse_fixtures import seed_reverse_matrix

pytestmark = pytest.mark.anyio


async def test_reverse_match_persists_assessment_for_every_managed_company(
    db_session: AsyncSession,
) -> None:
    # Given: a canonical program and one active managed company with complete evidence.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile = await seed_profile(db_session)
    company = await seed_managed_company(db_session, profile)
    await db_session.commit()

    # When: the institution reverse-matches the program at an injected UTC instant.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: the company is returned with the persisted deterministic assessment.
    assert tuple(item.managed_company_id for item in results) == (company.id,)
    assert results[0].assessment is not None
    assert results[0].assessment.id is not None
    assert results[0].assessment.final_status is FinalStatus.ELIGIBLE
    assert results[0].assessment.items[0].evidence_ids


async def test_reverse_match_returns_all_statuses_errors_and_current_content(
    db_session: AsyncSession,
) -> None:
    # Given: active and inactive companies spanning four statuses and one malformed profile.
    program = await seed_reverse_matrix(db_session)

    # When: every managed company is assessed from one canonical program input.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: nothing is hidden and status, source, and numeric ordering are deterministic.
    assert tuple(int(item.managed_company_id) for item in results) == (9, 40, 2, 4, 30, 12)
    assert tuple(item.active for item in results) == (False, True, False, True, True, True)
    assert tuple(
        None if item.assessment is None else item.assessment.final_status for item in results
    ) == (
        FinalStatus.ELIGIBLE,
        FinalStatus.ELIGIBLE,
        FinalStatus.CONDITIONAL,
        FinalStatus.NEEDS_REVIEW,
        FinalStatus.INELIGIBLE,
        None,
    )
    assert results[-1].input_error is not None
    assert all(item.assessment is None or item.assessment.id is not None for item in results)
    assert all(item.assessment is None or len(item.assessment.items) == 2 for item in results)
    assert tuple(identity.source for identity in results[0].content_identities) == (
        SourceName.BIZINFO,
        SourceName.KSTARTUP,
    )
    assert results[0].latest_content_hash == "c" * 64


async def test_repeat_reverse_match_references_only_new_immutable_assessments(
    db_session: AsyncSession,
) -> None:
    # Given: a reverse-matching matrix already assessed once at one instant.
    program = await seed_reverse_matrix(db_session)
    service = ReverseMatchingService(db_session)
    first = await service.reverse_match(program_id(program), REFERENCE_TIME)

    # When: the same program and timestamp are assessed again.
    second = await service.reverse_match(program_id(program), REFERENCE_TIME)

    # Then: the invocation returns new IDs while preserving every older row.
    first_ids = {item.assessment.id for item in first if item.assessment is not None}
    second_ids = {item.assessment.id for item in second if item.assessment is not None}
    assessment_count = await db_session.scalar(select(func.count(AssessmentRow.id)))
    item_count = await db_session.scalar(select(func.count(RuleAssessmentRow.id)))
    assert first_ids.isdisjoint(second_ids)
    assert assessment_count == 10
    assert item_count == 20


async def test_reverse_match_returns_empty_for_empty_institution(
    db_session: AsyncSession,
) -> None:
    # Given: one complete program and no managed-company rows.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    await db_session.commit()

    # When: reverse matching runs for the empty institution.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: the valid institution result is exactly empty.
    assert results == ()


@pytest.mark.parametrize(
    ("program", "assessed_at", "expected"),
    [
        (ProgramId(999), REFERENCE_TIME, ReverseMatchingErrorCode.UNKNOWN_PROGRAM),
        (
            ProgramId(999),
            REFERENCE_TIME.replace(tzinfo=None),
            ReverseMatchingErrorCode.NAIVE_ASSESSED_AT,
        ),
    ],
)
async def test_reverse_match_rejects_invalid_request_boundaries(
    db_session: AsyncSession,
    program: ProgramId,
    assessed_at: datetime,
    expected: ReverseMatchingErrorCode,
) -> None:
    # Given: a request with an unknown program or a naive assessment instant.
    service = ReverseMatchingService(db_session)

    # When: the invalid request crosses the service boundary.
    with pytest.raises(ReverseMatchingError) as captured:
        _ = await service.reverse_match(program, assessed_at)

    # Then: one finite request code is surfaced instead of empty success.
    assert captured.value.code is expected
