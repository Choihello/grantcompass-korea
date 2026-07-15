from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.programs import RawNotice
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.table_programs import AttachmentRow, ProgramRow


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


@pytest.mark.anyio
async def test_reingesting_historical_hash_is_idempotent(
    program_repository: ProgramRepository,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: a notice whose original content has already been superseded.
    original = await program_repository.upsert_notice(raw_notice, now)
    changed = raw_notice.model_copy(update={"summary": "변경된 사업 개요"})
    _ = await program_repository.upsert_notice(changed, now + timedelta(minutes=1))

    # When: the source publishes the original content again.
    repeated = await program_repository.upsert_notice(raw_notice, now + timedelta(minutes=2))

    # Then: the historical version is reused without violating version uniqueness.
    assert repeated.program_id == original.program_id
    assert repeated.notice_version_id == original.notice_version_id
    assert repeated.notice_version_created is False
    assert await program_repository.count_notice_versions(original.program_id) == 2


@pytest.mark.anyio
async def test_changed_notice_refreshes_canonical_program(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: a canonical program linked to an existing source notice.
    original = await program_repository.upsert_notice(raw_notice, now)
    changed_at = now + timedelta(days=1)
    changed = raw_notice.model_copy(
        update={
            "title": "청년 창업 도약 지원사업",
            "organization": "창업진흥원",
            "application_start": date(2026, 8, 1),
            "application_end": date(2026, 8, 31),
        }
    )

    # When: the changed source notice is persisted.
    refreshed = await program_repository.upsert_notice(changed, changed_at)

    # Then: the same program row reflects every supplied canonical field.
    program = await db_session.scalar(
        select(ProgramRow).where(ProgramRow.id == original.program_id)
    )
    assert program is not None
    assert refreshed.program_id == original.program_id
    assert program.title == "청년 창업 도약 지원사업"
    assert program.organization == "창업진흥원"
    assert program.application_start == date(2026, 8, 1)
    assert program.application_end == date(2026, 8, 31)
    assert program.canonical_key.endswith("|창업진흥원|2026-08-31")
    assert program.updated_at == changed_at.replace(tzinfo=None)


@pytest.mark.anyio
async def test_sqlite_connections_enforce_foreign_keys(db_session: AsyncSession) -> None:
    # Given: an attachment referencing a notice version that does not exist.
    orphan = AttachmentRow(
        notice_version_id=999_999,
        filename="orphan.pdf",
        download_url="https://example.invalid/orphan.pdf",
        media_type="application/pdf",
        content_hash=None,
        local_path=None,
        parse_status="pending",
    )
    db_session.add(orphan)

    # When: the orphan is flushed to SQLite.
    with pytest.raises(IntegrityError):
        await db_session.flush()

    # Then: SQLite rejects the invalid foreign-key reference.


@pytest.mark.anyio
async def test_count_notice_versions_preserves_caller_transaction(
    program_repository: ProgramRepository,
    db_session: AsyncSession,
    raw_notice: RawNotice,
    now: datetime,
) -> None:
    # Given: one stored notice and a caller-owned transaction.
    stored = await program_repository.upsert_notice(raw_notice, now)
    transaction = await db_session.begin()

    # When: the repository performs a read-only count.
    count = await program_repository.count_notice_versions(stored.program_id)

    # Then: the count is returned without committing the caller's transaction.
    assert count == 1
    assert transaction.is_active is True
    await transaction.rollback()
