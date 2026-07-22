"""Secure evidence-rich consultation PDF rendering."""

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, final, override
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.clock import Clock, SystemClock
from grantcompass.domain.cases import CaseId
from grantcompass.reports.consultation_data import (
    ConsultationData,
    load_consultation_data,
)
from grantcompass.reports.pdf_runtime import (
    NativePdfUnavailableError,
    PdfRenderer,
    PdfRenderError,
    WeasyPrintRenderer,
    blocked_url_fetcher,
)

_TEMPLATE_DIR = Path(__file__).with_name("templates")
_ENVIRONMENT = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(("html",)),
)
_RESOURCE_ATTRIBUTES: Final = frozenset({"src", "srcset", "href", "xlink:href", "poster", "data"})
_CSS_RESOURCE = re.compile(r"(?:url\s*\(|@import\b)", flags=re.IGNORECASE)


@final
class ConsultationReportService:
    """Load canonical case data and render it with a hardened WeasyPrint boundary."""

    def __init__(
        self,
        session: AsyncSession,
        clock: Clock | None = None,
        timezone: str = "Asia/Seoul",
        renderer: PdfRenderer | None = None,
    ) -> None:
        """Bind report generation to one caller-owned async session."""
        self._session = session
        self._clock = clock or SystemClock()
        self._timezone = ZoneInfo(timezone)
        self._renderer = renderer or WeasyPrintRenderer()

    async def load(self, case_id: int) -> ConsultationData:
        """Load the complete dossier used by both HTML and PDF surfaces."""
        return await load_consultation_data(
            self._session,
            CaseId(case_id),
            self._clock.now(),
            self._timezone,
        )

    async def render_consultation_pdf(self, case_id: int) -> bytes:
        """Render one searchable PDF without permitting external resource access."""
        data = await self.load(case_id)
        markup = _ENVIRONMENT.get_template("consultation.html").render(report=data)
        return await render_secure_pdf(markup, self._renderer)


async def render_secure_pdf(markup: str, renderer: PdfRenderer) -> bytes:
    """Validate render-boundary markup before invoking the selected renderer."""
    _reject_resource_markup(markup)
    return await renderer.render(markup)


def _reject_resource_markup(markup: str) -> None:
    _ResourceMarkupGuard().feed(markup)


@final
class _ResourceMarkupGuard(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_style = False

    @override
    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._inspect_attributes(attrs)
        self._inside_style = tag.casefold() == "style"

    @override
    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        _ = tag
        self._inspect_attributes(attrs)

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "style":
            self._inside_style = False

    @override
    def handle_data(self, data: str) -> None:
        if self._inside_style and _CSS_RESOURCE.search(data) is not None:
            self._blocked()

    def _inspect_attributes(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.casefold() in _RESOURCE_ATTRIBUTES:
                self._blocked()
            if (
                name.casefold() == "style"
                and value is not None
                and _CSS_RESOURCE.search(value) is not None
            ):
                self._blocked()

    @staticmethod
    def _blocked() -> None:
        message = "external_resource_markup_blocked"
        raise ValueError(message)


__all__ = [
    "ConsultationData",
    "ConsultationReportService",
    "NativePdfUnavailableError",
    "PdfRenderError",
    "PdfRenderer",
    "WeasyPrintRenderer",
    "blocked_url_fetcher",
    "render_secure_pdf",
]
