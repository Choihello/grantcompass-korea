import sys
from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess

import anyio
import fitz
import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from grantcompass.reports.pdf_runtime import PdfRenderError, WeasyPrintRenderer

pytestmark = pytest.mark.anyio


def _searchable_pdf(text: str = "GrantCompass PDF") -> bytes:
    stream = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))  # pyright: ignore[reportUnknownMemberType]
    canvas = Canvas(stream)
    canvas.setFont("HYSMyeongJo-Medium", 12)
    canvas.drawString(72, 720, text)
    canvas.save()
    return stream.getvalue()


def _unsearchable_pdf(*, image_only: bool) -> bytes:
    document = fitz.open()
    page = document.new_page()
    if image_only:
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)  # noqa: FBT003
        _ = page.insert_image(fitz.Rect(72, 72, 144, 144), pixmap=pixmap)
    payload = document.tobytes()
    document.close()
    return payload


async def test_portable_module_cli_uses_the_fixed_process_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: no deployment executable but a declared portable module runtime.
    monkeypatch.delenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", raising=False)
    observed: list[tuple[tuple[str, ...], bytes]] = []

    async def runner(argv: tuple[str, ...], payload: bytes) -> CompletedProcess[bytes]:
        observed.append((argv, payload))
        return CompletedProcess(argv, 0, stdout=_searchable_pdf(), stderr=b"")

    # When: rendering uses the runtime selector.
    result = await WeasyPrintRenderer(
        module_available=lambda: True,
        process_runner=runner,
    ).render("<p>safe</p>")

    # Then: Python's verified module CLI, never an in-process renderer, is invoked.
    assert result.startswith(b"%PDF")
    assert observed == [((sys.executable, "-m", "weasyprint", "-", "-"), b"<p>safe</p>")]


async def test_zero_exit_non_pdf_output_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a configured subprocess exits successfully with corrupt stdout.
    executable = tmp_path / "weasyprint.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))

    async def runner(argv: tuple[str, ...], _: bytes) -> CompletedProcess[bytes]:
        return CompletedProcess(argv, 0, stdout=b"not a PDF", stderr=b"")

    # When: the renderer accepts the process exit.
    with pytest.raises(PdfRenderError) as captured:
        _ = await WeasyPrintRenderer(process_runner=runner).render("<p>safe</p>")

    # Then: structural PDF validation returns a stable safe error.
    assert captured.value.code == "weasyprint_invalid_pdf"


@pytest.mark.parametrize("image_only", [False, True])
async def test_blank_and_image_only_pdf_output_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    image_only: bool,
) -> None:
    # Given: the subprocess returns an openable page with no searchable text.
    executable = tmp_path / "weasyprint.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))

    async def runner(argv: tuple[str, ...], _: bytes) -> CompletedProcess[bytes]:
        return CompletedProcess(
            argv,
            0,
            stdout=_unsearchable_pdf(image_only=image_only),
            stderr=b"",
        )

    # When: final accepted-output validation inspects extracted text.
    with pytest.raises(PdfRenderError) as captured:
        _ = await WeasyPrintRenderer(process_runner=runner).render("<p>expected text</p>")

    # Then: blank and image-only artifacts share one actionable searchable-PDF failure.
    assert captured.value.code == "weasyprint_unsearchable_pdf"


async def test_timeout_waits_for_process_runner_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the finite subprocess adapter is cancelled while it tracks cleanup.
    executable = tmp_path / "weasyprint.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))
    cleaned = False

    async def stalled(argv: tuple[str, ...], _: bytes) -> CompletedProcess[bytes]:
        nonlocal cleaned
        try:
            await anyio.sleep(10)
        finally:
            cleaned = True
        return CompletedProcess(argv, 0, stdout=_searchable_pdf(), stderr=b"")

    # When: the timeout expires.
    renderer = WeasyPrintRenderer(process_runner=stalled, timeout_seconds=0.01)
    with pytest.raises(PdfRenderError, match="weasyprint_render_timeout"):
        _ = await renderer.render("<p>x</p>")

    # Then: cancellation cleaned the child-process boundary before control returned.
    assert cleaned is True


async def test_missing_module_runtime_is_a_stable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: neither an executable nor a discoverable module runtime exists.
    monkeypatch.delenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", raising=False)

    # When: rendering begins.
    with pytest.raises(PdfRenderError) as captured:
        _ = await WeasyPrintRenderer(module_available=lambda: False).render("<p>x</p>")

    # Then: no ignored local binary path becomes an implicit fallback.
    assert captured.value.code == "weasyprint_runtime_unavailable"


async def test_valid_output_is_openable_with_a_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a configured process returns a real searchable PDF.
    executable = tmp_path / "weasyprint.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))

    async def runner(argv: tuple[str, ...], _: bytes) -> CompletedProcess[bytes]:
        return CompletedProcess(argv, 0, stdout=_searchable_pdf("정상 PDF"), stderr=b"")

    # When: production validation accepts its bytes.
    result = await WeasyPrintRenderer(process_runner=runner).render("<p>x</p>")

    # Then: the accepted contract is a structurally usable PDF.
    with fitz.open(stream=result, filetype="pdf") as document:
        assert document.page_count == 1
        assert "정상" in document[0].get_text()
