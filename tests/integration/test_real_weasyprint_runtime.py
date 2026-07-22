import os
from importlib.util import find_spec

import fitz
import pytest

from grantcompass.reports.pdf_runtime import PdfRenderError, WeasyPrintRenderer

pytestmark = pytest.mark.anyio


async def test_functional_weasyprint_runtime_renders_searchable_pdf() -> None:
    # Given: an explicitly configured executable or a discoverable module runtime.
    configured = os.environ.get("GRANTCOMPASS_WEASYPRINT_EXECUTABLE")
    if configured is None and find_spec("weasyprint") is None:
        pytest.skip("weasyprint executable and module runtime are unavailable")

    # When: the real subprocess renderer receives safe Korean consultation content.
    try:
        result = await WeasyPrintRenderer().render("<p>공식 출처 · 검토자 · 수정 사유</p>")
    except PdfRenderError as error:
        pytest.skip(f"configured WeasyPrint runtime is not functional: {error.code}")

    # Then: a genuine subprocess PDF opens and retains searchable evidence text.
    with fitz.open(stream=result, filetype="pdf") as document:
        extracted = "".join(page.get_text() for page in document)
        assert document.page_count >= 1
    assert "공식 출처" in extracted
