from collections.abc import AsyncIterator
from pathlib import Path
from re import search
from secrets import token_urlsafe

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError

from grantcompass.config import Settings
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.tables import Base
from grantcompass.web.app import create_app, dispose_app
from tests.e2e.institution_seed import seed_institution

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "overrides",
    [{"allowed_hosts": ("*",)}, {"allowed_origins": ("*",)}],
)
def test_wildcard_web_trust_configuration_is_rejected(
    overrides: dict[str, tuple[str, ...]],
) -> None:
    with pytest.raises(ValidationError):
        _ = Settings.model_validate(overrides)


@pytest.fixture
async def security_app(tmp_path: Path) -> AsyncIterator[FastAPI]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'security.db'}"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await seed_institution(session)
    await engine.dispose()
    app = create_app(
        Settings(
            database_url=database_url,
            allowed_hosts=("institution.test",),
            allowed_origins=("http://institution.test",),
            csrf_signing_secret=SecretStr(token_urlsafe(32)),
        )
    )
    yield app
    await dispose_app(app)


async def test_hostile_host_is_rejected_at_the_http_boundary(security_app: FastAPI) -> None:
    # A missing host allowlist check would let this request reach the favicon route.
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=security_app),
        base_url="http://evil.example:8000",
    ) as client:
        response = await client.get("/favicon.ico")

    assert response.status_code == 400


async def test_hostile_origin_is_rejected_before_normal_post_validation(
    security_app: FastAPI,
) -> None:
    # A missing origin check would expose the route's ordinary actor validation (422).
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=security_app),
        base_url="http://institution.test",
    ) as client:
        response = await client.post(
            "/programs/1/reverse-match",
            headers={"Origin": "https://evil.example"},
            data={"actor": "", "reason": "hostile request", "csrf_token": "invalid"},
        )

    assert response.status_code == 403
    assert response.text == "origin_not_allowed"


@pytest.mark.parametrize("token", [None, "invalid-token"])
async def test_missing_or_invalid_csrf_is_rejected_without_mutation(
    security_app: FastAPI,
    token: str | None,
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=security_app),
        base_url="http://institution.test",
    ) as client:
        page = await client.get("/programs/1")
        assert page.status_code == 200
        data = {"actor": "담당자", "reason": "경계 검증"}
        if token is not None:
            data["csrf_token"] = token
        response = await client.post(
            "/programs/1/reverse-match",
            headers={"Origin": "http://institution.test"},
            data=data,
        )

    assert response.status_code == 403
    assert response.text == "csrf_invalid"


async def test_rendered_session_csrf_token_preserves_valid_form_flow(
    security_app: FastAPI,
) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=security_app),
        base_url="http://institution.test",
        follow_redirects=False,
    ) as client:
        page = await client.get("/programs/1")
        match = search(r'name="csrf_token" type="hidden" value="([^"]+)"', page.text)
        assert match is not None
        token = match.group(1)
        response = await client.post(
            "/programs/1/reverse-match",
            headers={"Origin": "http://institution.test"},
            data={"actor": "담당자", "reason": "정상 요청", "csrf_token": token},
        )

    assert response.status_code == 303


async def test_every_response_denies_framing(security_app: FastAPI) -> None:
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=security_app),
        base_url="http://institution.test",
    ) as client:
        response = await client.get("/programs")

    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert response.headers["x-frame-options"] == "DENY"
