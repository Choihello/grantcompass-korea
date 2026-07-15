from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import RawNotice
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.tables import Base


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def program_repository(db_session: AsyncSession) -> ProgramRepository:
    return ProgramRepository(db_session)


@pytest.fixture
def raw_notice() -> RawNotice:
    return RawNotice(
        source=SourceName.KSTARTUP,
        source_notice_id="K-2026-001",
        title="  청년   창업 지원사업  ",
        organization="중소벤처기업부",
        summary="초기 창업기업 지원",
        application_start=date(2026, 7, 1),
        application_end=date(2026, 7, 31),
        detail_url=HttpUrl("https://example.invalid/notices/K-2026-001"),
        raw_payload=freeze_json_object({"notice_id": "K-2026-001", "page": 1}),
    )


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 15, tzinfo=UTC)
