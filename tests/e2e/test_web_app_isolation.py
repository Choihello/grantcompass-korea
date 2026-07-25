from datetime import UTC, date, datetime
from pathlib import Path

import httpx2
import pytest
from pydantic import HttpUrl

from grantcompass.config import Settings
from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import RawNotice
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.repositories import ProgramRepository
from grantcompass.storage.tables import Base
from grantcompass.web.app import create_app, dispose_app

pytestmark = pytest.mark.anyio


async def _database(path: Path, title: str) -> str:
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        _ = await ProgramRepository(session).upsert_notice(
            RawNotice(
                source=SourceName.MANUAL,
                source_notice_id=title,
                title=title,
                organization="Isolated institution",
                application_end=date(2030, 1, 1),
                detail_url=HttpUrl(f"https://example.invalid/{title}"),
                raw_payload=freeze_json_object({"title": title}),
            ),
            datetime(2026, 7, 22, tzinfo=UTC),
        )
    await engine.dispose()
    return url


async def test_two_fastapi_instances_keep_routes_bound_to_their_own_runtime(tmp_path: Path) -> None:
    first_url = await _database(tmp_path / "first.db", "FIRST APP PROGRAM")
    second_url = await _database(tmp_path / "second.db", "SECOND APP PROGRAM")
    first_app = create_app(Settings(database_url=first_url))
    second_app = create_app(Settings(database_url=second_url))
    try:
        async with (
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=first_app),
                base_url="http://first.test",
            ) as first_client,
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=second_app),
                base_url="http://second.test",
            ) as second_client,
        ):
            first = await first_client.get("/programs")
            second = await second_client.get("/programs")
        assert "FIRST APP PROGRAM" in first.text
        assert "SECOND APP PROGRAM" not in first.text
        assert "SECOND APP PROGRAM" in second.text
        assert "FIRST APP PROGRAM" not in second.text
    finally:
        await dispose_app(first_app)
        await dispose_app(second_app)
