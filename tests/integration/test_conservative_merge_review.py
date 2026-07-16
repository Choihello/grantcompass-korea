from datetime import date, datetime

import pytest

from grantcompass.domain.enums import SourceName
from grantcompass.storage.repositories import ProgramRepository
from tests.factories import NoticeValues, make_notice


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("organization", "deadline"),
    [
        (None, date(2026, 7, 31)),
        ("가상창업지원원", None),
        (None, None),
    ],
)
async def test_missing_merge_identity_never_auto_merges(
    program_repository: ProgramRepository,
    now: datetime,
    organization: str | None,
    deadline: date | None,
) -> None:
    # Given: one complete notice and a same-title notice missing required identity fields.
    complete = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, "K-COMPLETE"), now
    )
    incomplete_raw = make_notice(
        SourceName.BIZINFO,
        f"B-{organization}-{deadline}",
        NoticeValues(organization=organization, application_end=deadline),
    )

    # When: the incomplete identity is ingested.
    incomplete = await program_repository.upsert_notice(incomplete_raw, now)

    # Then: it remains separate, exact lookup refuses it, and review receives a candidate.
    assert incomplete.program_id != complete.program_id
    assert await program_repository.find_merge_candidate(incomplete_raw) is None
    candidates = await program_repository.list_merge_candidates()
    candidate_programs = ({item.left_program_id, item.right_program_id} for item in candidates)
    assert any(incomplete.program_id in program_ids for program_ids in candidate_programs)
