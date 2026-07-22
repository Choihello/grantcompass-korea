from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess

import anyio
import pytest
from anyio import Path as AsyncPath
from reportlab.pdfgen.canvas import Canvas

import grantcompass.reports.pdf as pdf_module

pytestmark = pytest.mark.anyio


def _valid_pdf() -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream)
    canvas.drawString(72, 720, "GrantCompass")
    canvas.save()
    return stream.getvalue()


async def test_configured_cli_is_honored_before_native_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: deployment supplies an approved executable.
    executable = tmp_path / "weasyprint-approved.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))
    observed: list[tuple[tuple[str, ...], bytes]] = []

    async def process_runner(
        argv: tuple[str, ...],
        payload: bytes,
    ) -> CompletedProcess[bytes]:
        observed.append((argv, payload))
        return CompletedProcess(argv, 0, stdout=_valid_pdf(), stderr=b"")

    renderer = pdf_module.WeasyPrintRenderer(
        module_available=lambda: False,
        process_runner=process_runner,
    )

    # When: secure markup is rendered.
    result = await renderer.render("<p>safe</p>")

    # Then: fixed argv and stdin/stdout honor the supplied CLI without native probing.
    assert result.startswith(b"%PDF")
    assert observed == [((str(executable), "-", "-"), b"<p>safe</p>")]


async def test_missing_native_and_cli_returns_stable_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: neither a configured CLI nor a discoverable module runtime is available.
    monkeypatch.delenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", raising=False)
    renderer = pdf_module.WeasyPrintRenderer(module_available=lambda: False)

    # When: rendering reaches the production runtime selector.
    with pytest.raises(pdf_module.PdfRenderError) as captured:
        _ = await renderer.render("<p>safe</p>")

    # Then: callers receive only the stable deployment-safe code.
    assert captured.value.code == "weasyprint_runtime_unavailable"


async def test_invalid_configured_executable_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: configuration names a path that does not exist.
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(tmp_path / "missing.exe"))
    renderer = pdf_module.WeasyPrintRenderer()

    # When: the configured CLI boundary validates the path.
    with pytest.raises(pdf_module.PdfRenderError) as captured:
        _ = await renderer.render("<p>safe</p>")

    # Then: no fallback masks the invalid explicit deployment configuration.
    assert captured.value.code == "weasyprint_executable_not_found"


async def test_nonzero_cli_exit_returns_stable_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the approved executable starts but returns a nonzero status.
    executable = tmp_path / "weasyprint.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))

    async def failed_runner(
        argv: tuple[str, ...],
        payload: bytes,
    ) -> CompletedProcess[bytes]:
        return CompletedProcess(argv, 7, stdout=b"", stderr=payload)

    renderer = pdf_module.WeasyPrintRenderer(process_runner=failed_runner)

    # When: the CLI reports failure.
    with pytest.raises(pdf_module.PdfRenderError) as captured:
        _ = await renderer.render("<p>safe</p>")

    # Then: process diagnostics do not leak through the stable boundary.
    assert captured.value.code == "weasyprint_render_failed"


async def test_cli_timeout_cancels_runner_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a configured renderer stalls and tracks cancellation cleanup.
    executable = tmp_path / "weasyprint.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))
    cleaned = False

    async def stalled_runner(
        argv: tuple[str, ...],
        _payload: bytes,
    ) -> CompletedProcess[bytes]:
        nonlocal cleaned
        try:
            await anyio.sleep(10)
        finally:
            cleaned = True
        return CompletedProcess(argv, 0, stdout=_valid_pdf(), stderr=b"")

    renderer = pdf_module.WeasyPrintRenderer(
        process_runner=stalled_runner,
        timeout_seconds=0.01,
    )

    # When: the finite render budget expires.
    with pytest.raises(pdf_module.PdfRenderError) as captured:
        _ = await renderer.render("<p>safe</p>")

    # Then: the stable timeout is returned only after runner cleanup executes.
    assert captured.value.code == "weasyprint_render_timeout"
    assert cleaned is True


async def test_cli_boundary_creates_no_temporary_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an otherwise empty controlled directory contains only the executable.
    executable = tmp_path / "weasyprint.exe"
    executable.touch()
    monkeypatch.setenv("GRANTCOMPASS_WEASYPRINT_EXECUTABLE", str(executable))

    async def successful_runner(
        argv: tuple[str, ...],
        payload: bytes,
    ) -> CompletedProcess[bytes]:
        return CompletedProcess(argv, 0, stdout=_valid_pdf(), stderr=payload[:0])

    renderer = pdf_module.WeasyPrintRenderer(process_runner=successful_runner)

    # When: markup crosses the fixed stdin/stdout process boundary.
    result = await renderer.render("<p>safe</p>")

    # Then: no input/output/temp artifact requires cleanup from the filesystem.
    assert result.startswith(b"%PDF")
    entries = tuple([item async for item in AsyncPath(tmp_path).iterdir()])
    assert entries == (AsyncPath(executable),)
