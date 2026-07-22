from pathlib import Path

import pytest
from sqlalchemy import func, select

from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_documents import DocumentRow
from grantcompass.storage.table_programs import AttachmentRow, NoticeVersionRow, ProgramRow
from grantcompass.web import manual_routes
from grantcompass.web.app import get_runtime
from tests.e2e.test_institution_web import InstitutionHarness, institution_client

pytestmark = pytest.mark.anyio
__all__ = ["institution_client"]
FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"


def _payload(title: str) -> dict[str, str]:
    return {
        "title": title,
        "organization": "합성기관",
        "application_end": "2026-08-31",
        "source_url": "https://example.invalid/manual",
        "actor": "등록 담당자",
        "reason": "첨부 한도 검증",
    }


async def _row_counts(harness: InstitutionHarness) -> tuple[int, int, int, int, int]:
    runtime = get_runtime(harness.app)
    async with runtime.session_factory() as session:
        return (
            int(await session.scalar(select(func.count(ProgramRow.id))) or 0),
            int(await session.scalar(select(func.count(NoticeVersionRow.id))) or 0),
            int(await session.scalar(select(func.count(AttachmentRow.id))) or 0),
            int(await session.scalar(select(func.count(DocumentRow.id))) or 0),
            int(await session.scalar(select(func.count(AuditEventRow.id))) or 0),
        )


@pytest.mark.parametrize("filename", ["oversized.pdf", "oversized.hwpx"])
async def test_oversized_manual_upload_rolls_back_every_row(
    institution_client: InstitutionHarness,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    # Given: the upload exceeds the web boundary's configured byte ceiling.
    monkeypatch.setattr(manual_routes, "MAX_ATTACHMENT_BYTES", 8, raising=False)
    before = await _row_counts(institution_client)

    # When: the supported extension carries one byte beyond that ceiling.
    response = await institution_client.client.post(
        "/programs/manual",
        data=_payload(f"거부 {filename}"),
        files={"document": (filename, b"123456789", "application/octet-stream")},
    )

    # Then: rejection precedes every canonical and audit write.
    assert response.status_code == 422
    assert "attachment_too_large" in response.text
    assert await _row_counts(institution_client) == before
    runtime = get_runtime(institution_client.app)
    async with runtime.session_factory() as session:
        manual_count = await session.scalar(
            select(func.count(NoticeVersionRow.id)).where(NoticeVersionRow.source == "manual")
        )
    assert manual_count == 0


@pytest.mark.parametrize(
    ("filename", "fixture"),
    [("small.pdf", "text-layer.pdf"), ("small.hwpx", "eligibility-table.hwpx")],
)
async def test_small_supported_manual_uploads_still_use_canonical_pipeline(
    institution_client: InstitutionHarness,
    filename: str,
    fixture: str,
) -> None:
    # Given: a supported attachment remains below the production ceiling.
    # When: the institution registers it through the web boundary.
    response = await institution_client.client.post(
        "/programs/manual",
        data=_payload(f"허용 {filename}"),
        files={
            "document": (filename, (FIXTURES / fixture).read_bytes(), "application/octet-stream")
        },
    )

    # Then: canonical ingestion completes and redirects to the program dossier.
    assert response.status_code == 303, response.text
    detail = await institution_client.client.get(response.headers["location"])
    assert filename in detail.text
    assert "parsed" in detail.text
