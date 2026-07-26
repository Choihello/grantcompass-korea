from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from grantcompass.config import Settings
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.table_cases import AuditEventRow, CaseRow
from grantcompass.storage.table_eligibility import ApplicantProfileRow, AssessmentRow
from grantcompass.storage.tables import Base
from grantcompass.web.app import create_app, dispose_app, get_runtime
from grantcompass.web.security import CSRF_COOKIE
from tests.e2e.institution_seed import seed_institution

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"


@dataclass(frozen=True, slots=True)
class InstitutionHarness:
    app: FastAPI
    client: httpx2.AsyncClient


async def _mutation_state(
    harness: InstitutionHarness,
) -> tuple[tuple[tuple[int, int, str], ...], tuple[tuple[int, str], ...], int]:
    runtime = get_runtime(harness.app)
    async with runtime.session_factory() as session:
        assessments = (
            await session.scalars(select(AssessmentRow).order_by(AssessmentRow.id))
        ).all()
        cases = (await session.scalars(select(CaseRow).order_by(CaseRow.id))).all()
        events = (await session.scalars(select(AuditEventRow.id))).all()
    return (
        tuple((row.id, row.review_revision, row.review_status) for row in assessments),
        tuple((row.id, row.stage) for row in cases),
        len(events),
    )


@pytest.fixture
async def institution_client(tmp_path: Path) -> AsyncIterator[InstitutionHarness]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'institution.db'}"
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

    async def authorize_mutation(request: httpx2.Request) -> None:
        if request.method != "POST":
            return
        cookie_header = next(
            (
                value.decode("latin-1")
                for key, value in request.headers.raw
                if key.lower() == b"cookie"
            ),
            "",
        )
        cookie_token = next(
            (
                value
                for item in cookie_header.split(";")
                for key, separator, value in (item.strip().partition("="),)
                if separator and key == CSRF_COOKIE
            ),
            "",
        )
        request.headers["Origin"] = "http://institution.test"
        request.headers["X-CSRF-Token"] = cookie_token

    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://institution.test",
        follow_redirects=False,
        event_hooks={"request": [authorize_mutation]},
    ) as client:
        primed = await client.get("/programs")
        assert primed.status_code == 200
        yield InstitutionHarness(app, client)
    await dispose_app(app)


async def test_institution_flow(institution_client: InstitutionHarness) -> None:
    # Given: a seeded institution workspace with official evidence and one company.
    detail = await institution_client.client.get("/programs/1")
    assert detail.status_code == 200
    assert "역매칭" in detail.text
    assert "공식 출처" in detail.text
    assert "문서 위치" in detail.text

    # When: the attributed reverse match is requested once.
    matched = await institution_client.client.post(
        "/programs/1/reverse-match",
        data={"actor": "담당자", "reason": "상담 후보 갱신"},
    )

    # Then: PRG returns to detail and exposes the persisted assessment.
    assert matched.status_code == 303
    refreshed = await institution_client.client.get(matched.headers["location"])
    assert "합성기업" in refreshed.text
    assert "eligible" in refreshed.text


async def test_browser_icon_request_is_quiet(
    institution_client: InstitutionHarness,
) -> None:
    # Given: a real browser asks every workspace for its conventional icon.
    # When: the favicon request reaches the institution application.
    response = await institution_client.client.get("/favicon.ico")

    # Then: the browser console remains free of an avoidable 404 error.
    assert response.status_code == 204


async def test_review_and_case_transition_append_visible_audit(
    institution_client: InstitutionHarness,
) -> None:
    # Given: a seeded automatic assessment and recommended case.
    # When: each authoritative repository receives one attributed mutation.
    reviewed = await institution_client.client.post(
        "/assessments/1/review",
        data={
            "actor": "담당자",
            "reason": "사업자등록증 확인",
            "expected_review_revision": "0",
            "condition_status_1": "",
            "condition_status_2": "",
        },
    )
    transitioned = await institution_client.client.post(
        "/cases/1/transition",
        data={"actor": "담당자", "reason": "전화 상담 완료", "stage": "contacted"},
    )

    # Then: both writes use PRG and immutable reasons appear in the case dossier.
    assert reviewed.status_code == 303, reviewed.text
    assert transitioned.status_code == 303
    audit = await institution_client.client.get("/cases/1")
    assert audit.status_code == 200
    assert "사업자등록증 확인" in audit.text
    assert "전화 상담 완료" in audit.text
    assert "recommended" in audit.text
    assert "contacted" in audit.text


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/programs/1/reverse-match", {"actor": "", "reason": "근거"}),
        (
            "/assessments/1/review",
            {
                "actor": "담당자",
                "reason": "",
                "expected_review_revision": "0",
                "condition_status_1": "",
                "condition_status_2": "",
            },
        ),
        ("/cases/1/transition", {"actor": "", "reason": "근거", "stage": "contacted"}),
    ],
)
async def test_mutating_posts_reject_missing_attribution_without_writes(
    institution_client: InstitutionHarness,
    path: str,
    data: dict[str, str],
) -> None:
    # Given: one mutation with a missing actor or reason.
    before = await _mutation_state(institution_client)

    # When: the invalid form crosses the HTTP boundary.
    response = await institution_client.client.post(path, data=data)

    # Then: no assessment, case, revision, review status, or audit side effect survives.
    assert response.status_code == 422
    assert "actor_required" in response.text or "reason_required" in response.text
    assert await _mutation_state(institution_client) == before


async def test_invalid_case_transition_is_safe(institution_client: InstitutionHarness) -> None:
    # Given: a recommended case cannot jump directly to submitted.
    # When: the malformed transition reaches the domain repository.
    response = await institution_client.client.post(
        "/cases/1/transition",
        data={"actor": "담당자", "reason": "잘못된 전이", "stage": "submitted"},
    )

    # Then: the stable domain error is surfaced and no partial redirect occurs.
    assert response.status_code == 409
    assert "invalid_transition" in response.text


async def test_institution_can_register_and_parse_own_program(
    institution_client: InstitutionHarness,
) -> None:
    # Given: a valid institution-owned notice and PDF attachment.
    payload = {
        "title": "기관 자체 합성 지원사업",
        "organization": "합성창업지원기관",
        "application_end": "2026-08-31",
        "source_url": "https://example.invalid/manual-notice",
        "actor": "담당자",
        "reason": "기관 자체사업 등록",
    }

    # When: it is submitted through the manual-program form.
    created = await institution_client.client.post(
        "/programs/manual",
        data=payload,
        files={
            "document": (
                "공고.pdf",
                (FIXTURES / "text-layer.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )

    # Then: the canonical notice and canonical document pipeline results are visible.
    assert created.status_code == 303, created.text
    detail = await institution_client.client.get(created.headers["location"])
    assert "기관 자체 합성 지원사업" in detail.text
    assert "manual" in detail.text
    assert "parsed" in detail.text


async def test_manual_program_rejects_unsafe_upload_without_partial_notice(
    institution_client: InstitutionHarness,
) -> None:
    # Given: a manual notice carrying an unsupported executable attachment.
    # When: validation occurs before canonical notice persistence.
    response = await institution_client.client.post(
        "/programs/manual",
        data={
            "title": "거부할 공고",
            "organization": "합성기관",
            "application_end": "2026-08-31",
            "source_url": "https://example.invalid/rejected",
            "actor": "담당자",
            "reason": "파일 검증",
        },
        files={"document": ("unsafe.exe", b"MZ", "application/octet-stream")},
    )

    # Then: no detail is created and the list remains free of the rejected title.
    assert response.status_code == 422
    listing = await institution_client.client.get("/programs")
    assert "거부할 공고" not in listing.text


async def test_html_escapes_persisted_source_text(institution_client: InstitutionHarness) -> None:
    # Given: hostile markup is persisted as an ordinary company name.
    runtime = get_runtime(institution_client.app)
    async with runtime.session_factory() as session:
        profile = await session.get(ApplicantProfileRow, 1)
        assert profile is not None
        profile.display_name = '<script id="unsafe">alert(1)</script>'
        await session.commit()

    # When: the companies ledger is rendered.
    response = await institution_client.client.get("/companies")

    # Then: markup remains text and cannot become an executable element.
    assert response.status_code == 200
    assert '<script id="unsafe">' not in response.text
    assert "&lt;script" in response.text
