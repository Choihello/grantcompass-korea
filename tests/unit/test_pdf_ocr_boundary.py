from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import anyio
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from grantcompass.documents.ocr import (
    OcrBlock,
    OcrFailure,
    OcrPage,
    validate_ocr_output,
)
from grantcompass.documents.pdf import PdfParser
from grantcompass.domain.json_types import JsonValue

FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"
type UntrustedOcrResult = OcrFailure | tuple[OcrBlock | JsonValue, ...] | JsonValue


@dataclass(frozen=True, slots=True)
class UntrustedOcr:
    result: UntrustedOcrResult

    async def recognize(self, page: OcrPage) -> UntrustedOcrResult:
        _ = page
        return self.result


@dataclass(frozen=True, slots=True)
class CancellingOcr:
    raised_types: list[type[BaseException]]

    async def recognize(self, page: OcrPage) -> tuple[OcrBlock, ...] | OcrFailure:
        _ = page
        cancellation = anyio.get_cancelled_exc_class()
        self.raised_types.append(cancellation)
        raise cancellation()


def _partial_text_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output, pagesize=A4, invariant=1, pageCompression=0)
    canvas.drawString(72, 770, "tiny")
    canvas.save()
    return output.getvalue()


async def _cancellation_type() -> type[BaseException]:
    return anyio.get_cancelled_exc_class()


@pytest.mark.parametrize("code", [None, 7])
def test_ocr_maps_non_string_provider_failure_code_to_invalid_output(code: JsonValue) -> None:
    # Given: a runtime provider returning malformed failure metadata.
    failure = OcrFailure(code)

    # When: the provider failure crosses the OCR trust boundary.
    result = validate_ocr_output(failure, width=100, height=100)

    # Then: malformed failure metadata becomes the finite invalid-output code.
    assert result == OcrFailure("invalid_output")


@pytest.mark.parametrize(
    "output",
    [
        None,
        [],
        ["not-a-block"],
        ("not-a-block",),
        ({"text": 7, "bbox": [0, 0, 10, 10], "confidence": 0.9},),
        ({"text": "bad", "bbox": [0, 0, 10], "confidence": "high"},),
    ],
)
def test_pdf_maps_malformed_ocr_output_to_finite_warning(output: UntrustedOcrResult) -> None:
    # Given: an injected provider returning an untrusted runtime shape.
    content = (FIXTURES / "scanned-page.pdf").read_bytes()

    # When: the provider output crosses the parser boundary.
    document = PdfParser(ocr_provider=UntrustedOcr(output)).parse(
        "doc-untrusted", content, "scan.pdf"
    )

    # Then: malformed output cannot escape or become evidence.
    assert document.blocks == ()
    assert document.warnings == ("ocr_failed:invalid_output:page1",)


def test_pdf_does_not_swallow_provider_cancellation() -> None:
    # Given: an OCR provider cancelled during recognition.
    provider = CancellingOcr(raised_types=[])
    content = (FIXTURES / "scanned-page.pdf").read_bytes()
    cancellation = anyio.run(_cancellation_type)

    # When: parsing reaches the provider cancellation point.
    with pytest.raises(cancellation):
        _ = PdfParser(ocr_provider=provider).parse("doc-cancel", content, "scan.pdf")

    # Then: structured cancellation propagates unchanged.
    assert provider.raised_types == [cancellation]


def test_successful_ocr_replaces_deficient_native_page_blocks() -> None:
    # Given: a page with partial native text and successful whole-page OCR.
    provider = UntrustedOcr((OcrBlock("tiny", (1.0, 1.0, 20.0, 12.0), 0.9),))

    # When: the deficient page is parsed.
    document = PdfParser(ocr_provider=provider).parse(
        "doc-partial-success", _partial_text_pdf(), "partial.pdf"
    )

    # Then: whole-page OCR replaces rather than duplicates partial native evidence.
    assert tuple(block.provenance for block in document.blocks) == ("ocr",)
    assert document.warnings == ()


def test_failed_ocr_retains_deficient_native_page_blocks() -> None:
    # Given: a page with partial native text and a finite OCR failure.
    provider = UntrustedOcr(OcrFailure("provider_timeout"))

    # When: OCR fails for the deficient page.
    document = PdfParser(ocr_provider=provider).parse(
        "doc-partial-failure", _partial_text_pdf(), "partial.pdf"
    )

    # Then: native evidence remains available for human review.
    assert tuple(block.provenance for block in document.blocks) == ("pdf_text",)
    assert document.warnings == ("ocr_failed:provider_timeout:page1",)
