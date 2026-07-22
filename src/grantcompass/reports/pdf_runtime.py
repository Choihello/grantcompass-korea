"""Lazy native and fixed-argv WeasyPrint runtime boundary."""

import os
from collections.abc import Awaitable, Callable
from importlib import import_module
from subprocess import CompletedProcess
from typing import Protocol, cast, final

from anyio import Path as AsyncPath
from anyio import fail_after, run_process
from anyio.to_thread import run_sync

_WEASYPRINT_EXECUTABLE = "GRANTCOMPASS_WEASYPRINT_EXECUTABLE"
_RUNTIME_UNAVAILABLE = "weasyprint_runtime_unavailable"
_EXECUTABLE_NOT_FOUND = "weasyprint_executable_not_found"
_RENDER_TIMEOUT = "weasyprint_render_timeout"
_RENDER_FAILED = "weasyprint_render_failed"


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


NativeRenderer = Callable[[str], bytes]
ProcessRunner = Callable[
    [tuple[str, ...], bytes],
    Awaitable[CompletedProcess[bytes]],
]


@final
class WeasyPrintRenderer:
    """Prefer explicit approved CLI configuration, otherwise load native lazily."""

    def __init__(
        self,
        *,
        native_renderer: NativeRenderer | None = None,
        process_runner: ProcessRunner | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        """Bind controlled runtime adapters and a finite process budget."""
        self._native_renderer = native_renderer or _render_native
        self._process_runner = process_runner or _run_process
        self._timeout_seconds = timeout_seconds

    async def render(self, markup: str) -> bytes:
        """Render with configured CLI or the declared Python library."""
        executable = os.environ.get(_WEASYPRINT_EXECUTABLE)
        if executable is not None:
            return await self._render_cli(markup, executable)
        try:
            return await run_sync(self._native_renderer, markup, abandon_on_cancel=True)
        except NativePdfUnavailableError:
            raise PdfRenderError(_RUNTIME_UNAVAILABLE) from None

    async def _render_cli(self, markup: str, executable: str) -> bytes:
        if not await AsyncPath(executable).is_file():
            raise PdfRenderError(_EXECUTABLE_NOT_FOUND)
        try:
            with fail_after(self._timeout_seconds):
                completed = await self._process_runner(
                    (executable, "-", "-"),
                    markup.encode(),
                )
        except TimeoutError:
            raise PdfRenderError(_RENDER_TIMEOUT) from None
        if completed.returncode != 0:
            raise PdfRenderError(_RENDER_FAILED)
        return completed.stdout


def blocked_url_fetcher(url: str) -> dict[str, str]:
    """Reject every external, local-file, and data resource requested by WeasyPrint."""
    scheme = url.split(":", maxsplit=1)[0]
    message = f"external_resource_blocked:{scheme}"
    raise ValueError(message)


def _render_native(markup: str) -> bytes:
    try:
        module = import_module("weasyprint")
    except (ImportError, OSError):
        raise NativePdfUnavailableError from None
    html_factory = cast("_HtmlFactory", module.__dict__["HTML"])
    result = html_factory(string=markup, url_fetcher=blocked_url_fetcher).write_pdf()
    if not isinstance(result, bytes):
        raise NativePdfUnavailableError
    return result


class _HtmlDocument(Protocol):
    def write_pdf(self) -> bytes | None: ...


class _HtmlFactory(Protocol):
    def __call__(
        self,
        *,
        string: str,
        url_fetcher: Callable[[str], dict[str, str]],
    ) -> _HtmlDocument: ...


async def _run_process(
    argv: tuple[str, ...],
    payload: bytes,
) -> CompletedProcess[bytes]:
    return await run_process(argv, input=payload, stderr=-1, check=False)


__all__ = [
    "NativePdfUnavailableError",
    "PdfRenderError",
    "PdfRenderer",
    "WeasyPrintRenderer",
    "blocked_url_fetcher",
]
