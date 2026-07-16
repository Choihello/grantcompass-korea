import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.domain.programs import IngestResult, RawNotice
from grantcompass.storage.notice_ingest import NoticeIngestor
from grantcompass.storage.repositories import IngestRaceExhaustedError, ProgramRepository
from tests.factories import make_notice


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message",
    [
        "FOREIGN KEY constraint failed",
        "UNIQUE constraint failed: applicant_profiles.display_name",
        "CHECK constraint failed: ck_unrelated",
        "unknown integrity failure",
    ],
)
async def test_unrelated_integrity_error_bubbles_unchanged_after_one_call(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    message: str,
) -> None:
    # Given: ingestion raises an unrelated integrity failure outside the race allowlist.
    original = _integrity_error(message)
    calls = 0
    rollback = AsyncMock(wraps=db_session.rollback)

    async def fail_once(
        ingestor: NoticeIngestor,
        raw: RawNotice,
        collected_at: datetime,
    ) -> IngestResult:
        nonlocal calls
        del ingestor, raw, collected_at
        calls += 1
        raise original

    monkeypatch.setattr(NoticeIngestor, "upsert", fail_once)
    monkeypatch.setattr(db_session, "rollback", rollback)

    # When: the public repository receives the unrelated failure.
    with pytest.raises(IntegrityError) as captured:
        _ = await program_repository.upsert_notice(make_notice(SourceName.KSTARTUP, "K-ERROR"), now)

    # Then: no retry or wrapping changes its identity, type, or traceback-bearing instance.
    assert captured.value is original
    assert calls == 1
    rollback.assert_awaited_once_with()

    monkeypatch.undo()
    _ = await program_repository.upsert_notice(
        make_notice(SourceName.KSTARTUP, f"K-AFTER-{message}"), now
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message",
    [
        "UNIQUE constraint failed: programs.canonical_key",
        (
            "UNIQUE constraint failed: notice_versions.source, "
            "notice_versions.source_notice_id, notice_versions.content_hash"
        ),
        (
            "UNIQUE constraint failed: current_notice_versions.source, "
            "current_notice_versions.source_notice_id"
        ),
        "UNIQUE constraint failed: current_notice_versions.version_id",
    ],
)
async def test_allowlisted_race_exhaustion_uses_stable_wrapper(
    program_repository: ProgramRepository,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    message: str,
) -> None:
    # Given: every attempt loses an allowlisted first-ingest race.
    race = _integrity_error(message)
    calls = 0

    async def always_race(
        ingestor: NoticeIngestor,
        raw: RawNotice,
        collected_at: datetime,
    ) -> IngestResult:
        nonlocal calls
        del ingestor, raw, collected_at
        calls += 1
        raise race

    monkeypatch.setattr(NoticeIngestor, "upsert", always_race)

    # When: the bounded retry budget is exhausted.
    with pytest.raises(IngestRaceExhaustedError) as captured:
        _ = await program_repository.upsert_notice(make_notice(SourceName.KSTARTUP, "K-RACE"), now)

    # Then: only this allowlisted race retries and raw database detail is not chained.
    assert calls == 3
    assert captured.value.__cause__ is None
    assert "UNIQUE" not in str(captured.value)


def _integrity_error(message: str) -> IntegrityError:
    return IntegrityError("fictional statement", {}, sqlite3.IntegrityError(message))
