import os
from importlib.util import find_spec

import fitz
import pytest

from grantcompass.reports.pdf_runtime import (
    WeasyPrintRenderer,
    is_recognized_weasyprint_native_loader_error,
    probe_weasyprint_module,
)

pytestmark = pytest.mark.anyio


async def test_functional_weasyprint_runtime_renders_searchable_pdf() -> None:
    # Given: an explicitly configured executable or a loadable native module runtime.
    configured = os.environ.get("GRANTCOMPASS_WEASYPRINT_EXECUTABLE")
    if configured is None and find_spec("weasyprint") is None:
        pytest.fail("required weasyprint module is not installed")
    if configured is None:
        diagnostic = await probe_weasyprint_module()
        if diagnostic is not None:
            if is_recognized_weasyprint_native_loader_error(diagnostic):
                pytest.skip("weasyprint native dependencies are unavailable")
            pytest.fail(f"weasyprint import failed: {diagnostic[-500:]}")

    # When: the real subprocess renderer receives safe Korean consultation content.
    result = await WeasyPrintRenderer().render("<p>공식 출처 · 검토자 · 수정 사유</p>")

    # Then: a genuine subprocess PDF opens and retains searchable evidence text.
    with fitz.open(stream=result, filetype="pdf") as document:
        extracted = "".join(page.get_text() for page in document)
        assert document.page_count >= 1
    assert "공식 출처" in extracted
