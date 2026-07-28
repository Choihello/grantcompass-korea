"""Lazy native and fixed-argv WeasyPrint runtime boundary."""

import os
import sys
from collections.abc import Awaitable, Callable
from importlib.util import find_spec
from subprocess import DEVNULL, PIPE, CompletedProcess
from typing import Protocol, final

import fitz
from anyio import Path as AsyncPath
from anyio import fail_after, run_process

_WEASYPRINT_EXECUTABLE = "GRANTCOMPASS_WEASYPRINT_EXECUTABLE"
_RUNTIME_UNAVAILABLE = "weasyprint_runtime_unavailable"
_EXECUTABLE_NOT_FOUND = "weasyprint_executable_not_found"
_RENDER_TIMEOUT = "weasyprint_render_timeout"
_RENDER_FAILED = "weasyprint_render_failed"
_INVALID_PDF = "weasyprint_invalid_pdf"
_UNSEARCHABLE_PDF = "weasyprint_unsearchable_pdf"
_MIN_SEARCHABLE_TEXT_CHARACTERS = 4
_NATIVE_LOADER_PHRASES = (
    "cannot load library",
    "cannot open shared object file",
    "module could not be found",
)
_WEASYPRINT_NATIVE_LIBRARIES = (
    "libgobject-2.0",
    "gobject-2.0",
    "libpango-1.0",
    "pango-1.0",
    "libcairo-2",
    "cairo-2",
)


class NativePdfUnavailableError(RuntimeError):
    """Signal that lazy native WeasyPrint dependencies cannot load."""


@final
class PdfRenderError(RuntimeError):
    """Carry one stable actionable consultation PDF failure code."""

    def __init__(self, code: str) -> None:
        """Store a finite code without leaking process diagnostics."""
        self.code = code
        super().__init__(code)


class PdfRenderer(Protocol):
    """Render already-validated HTML markup to PDF bytes."""

    async def render(self, markup: str) -> bytes:
        """Return a complete PDF byte stream."""
        ...


ModuleAvailable = Callable[[], bool]
ProcessRunner = Callable[
    [tuple[str, ...], bytes],
    Awaitable[CompletedProcess[bytes]],
]
ImportProbeRunner = Callable[[tuple[str, ...]], Awaitable[CompletedProcess[bytes]]]


@final
class WeasyPrintRenderer:
    """Run configured or portable WeasyPrint only through a finite subprocess."""

    def __init__(
        self,
        *,
        module_available: ModuleAvailable | None = None,
        process_runner: ProcessRunner | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        """Bind controlled subprocess adapters and a finite process budget."""
        self._module_available = module_available or _module_available
        self._process_runner = process_runner or _run_process
        self._timeout_seconds = timeout_seconds

    async def render(self, markup: str) -> bytes:
        """Render with configured CLI or the portable Python module CLI."""
        executable = os.environ.get(_WEASYPRINT_EXECUTABLE)
        if executable is not None:
            if not await AsyncPath(executable).is_file():
                raise PdfRenderError(_EXECUTABLE_NOT_FOUND)
            command = (executable, "--encoding", "utf-8", "-", "-")
        elif self._module_available():
            command = (
                sys.executable,
                "-m",
                "weasyprint",
                "--encoding",
                "utf-8",
                "-",
                "-",
            )
        else:
            raise PdfRenderError(_RUNTIME_UNAVAILABLE) from None
        return await self._render_process(markup, command)

    async def _render_process(self, markup: str, command: tuple[str, ...]) -> bytes:
        try:
            with fail_after(self._timeout_seconds):
                completed = await self._process_runner(command, markup.encode())
        except TimeoutError:
            raise PdfRenderError(_RENDER_TIMEOUT) from None
        if completed.returncode != 0:
            raise PdfRenderError(_RENDER_FAILED)
        return validate_pdf_output(completed.stdout)


def blocked_url_fetcher(url: str) -> dict[str, str]:
    """Reject every external, local-file, and data resource requested by WeasyPrint."""
    scheme = url.split(":", maxsplit=1)[0]
    message = f"external_resource_blocked:{scheme}"
    raise ValueError(message)


def is_recognized_weasyprint_native_loader_error(diagnostic: str) -> bool:
    """Return whether an import diagnostic is a known optional native-library failure."""
    normalized = diagnostic.casefold()
    has_loader_phrase = any(phrase in normalized for phrase in _NATIVE_LOADER_PHRASES)
    has_native_library = any(library in normalized for library in _WEASYPRINT_NATIVE_LIBRARIES)
    return has_loader_phrase and has_native_library


async def probe_weasyprint_module(
    *,
    process_runner: ImportProbeRunner | None = None,
    timeout_seconds: float = 5,
) -> str | None:
    """Return finite import stderr while allowing timeout to remain a hard failure."""
    runner = process_runner or _run_import_probe
    with fail_after(timeout_seconds):
        completed = await runner((sys.executable, "-c", "import weasyprint"))
    if completed.returncode == 0:
        return None
    return (completed.stderr or b"").decode(errors="replace")


def _module_available() -> bool:
    return find_spec("weasyprint") is not None


def validate_pdf_output(payload: bytes) -> bytes:
    """Reject malformed or non-searchable renderer output."""
    if not payload.startswith(b"%PDF"):
        raise PdfRenderError(_INVALID_PDF)
    try:
        with fitz.open(stream=payload, filetype="pdf") as document:
            if document.page_count < 1:
                raise PdfRenderError(_INVALID_PDF)
            text = "".join(page.get_text() for page in document)
    except RuntimeError:
        raise PdfRenderError(_INVALID_PDF) from None
    searchable = "".join(text.split())
    if len(searchable) < _MIN_SEARCHABLE_TEXT_CHARACTERS or not any(
        character.isalnum() for character in searchable
    ):
        raise PdfRenderError(_UNSEARCHABLE_PDF)
    return payload


async def _run_process(
    argv: tuple[str, ...],
    payload: bytes,
) -> CompletedProcess[bytes]:
    return await run_process(argv, input=payload, stderr=-1, check=False)


async def _run_import_probe(argv: tuple[str, ...]) -> CompletedProcess[bytes]:
    return await run_process(argv, stdout=DEVNULL, stderr=PIPE, check=False)


__all__ = [
    "NativePdfUnavailableError",
    "PdfRenderError",
    "PdfRenderer",
    "WeasyPrintRenderer",
    "blocked_url_fetcher",
    "is_recognized_weasyprint_native_loader_error",
    "probe_weasyprint_module",
    "validate_pdf_output",
]
