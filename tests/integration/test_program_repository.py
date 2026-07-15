from datetime import datetime

import pytest

from grantcompass.domain.programs import RawNotice
from grantcompass.storage.repositories import ProgramRepository


@pytest.mark.anyio
async def test_upsert_same_notice_is_idempotent(
    program_repository: ProgramRepository,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: one stable notice and collection instant.

    # When: the same source notice is persisted twice.
    first = await program_repository.upsert_notice(raw_notice, now)
    second = await program_repository.upsert_notice(raw_notice, now)

    # Then: persistence returns the same program and does not duplicate the version.
    assert first.program_id == second.program_id
    assert first.notice_version_created is True
    assert second.notice_version_created is False
    assert await program_repository.count_notice_versions(first.program_id) == 1


@pytest.mark.anyio
async def test_changed_payload_creates_notice_version(
    program_repository: ProgramRepository,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: one persisted source notice and a changed boundary model.
    first = await program_repository.upsert_notice(raw_notice, now)
    changed = raw_notice.model_copy(update={"summary": "변경된 사업 개요"})

    # When: the changed notice is persisted.
    second = await program_repository.upsert_notice(changed, now)

    # Then: the program identity is stable and both immutable versions remain.
    assert second.program_id == first.program_id
    assert second.notice_version_created is True
    assert await program_repository.count_notice_versions(first.program_id) == 2
