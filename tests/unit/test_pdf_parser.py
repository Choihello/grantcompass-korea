from dataclasses import dataclass
from math import nan
from pathlib import Path

import anyio
import pymupdf as fitz
import pytest

from grantcompass.documents.base import DocumentParseError
from grantcompass.documents.ocr import OcrBlock, OcrFailure, OcrPage
from grantcompass.documents.pdf import PdfParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "documents"
PDF_ENCRYPT_AES_256 = 5


@dataclass(frozen=True, slots=True)
class RecordingOcr:
    result: tuple[OcrBlock, ...] | OcrFailure
    pages: list[int]

    async def recognize(self, page: OcrPage) -> tuple[OcrBlock, ...] | OcrFailure:
        self.pages.append(page.page)
        return self.result


@dataclass(frozen=True, slots=True)
class SlowOcr:
    async def recognize(self, page: OcrPage) -> tuple[OcrBlock, ...] | OcrFailure:
        _ = page
        await anyio.sleep(1)
        return ()


def test_pdf_preserves_page_number_and_coordinates() -> None:
    # Given: a deterministic two-page text PDF.
    content = (FIXTURES / "text-layer.pdf").read_bytes()

    # When: its text layer is parsed.
    document = PdfParser().parse("doc-1", content, "notice.pdf")

    # Then: page-local provenance remains addressable.
    block = next(block for block in document.blocks if "early-stage" in block.text)
    assert block.page == 2
    assert str(block.block_id).startswith("page2:")
    assert block.bbox is not None
    assert block.provenance == "pdf_text"


def test_pdf_extracts_unique_table_cells() -> None:
    # Given: a PDF with aligned tabular text.
    content = (FIXTURES / "text-layer.pdf").read_bytes()

    # When: text and table layers are combined.
    document = PdfParser().parse("doc-table", content, "notice.pdf")

    # Then: table cells have deterministic references without duplicate cell blocks.
    cells = tuple(block for block in document.blocks if block.kind == "table_cell")
    assert cells
    assert len({(cell.page, cell.table_ref, cell.text) for cell in cells}) == len(cells)
    assert all(cell.bbox is not None for cell in cells)
    assert all(cell.table_ref is not None and "cell0" in cell.table_ref for cell in cells)


def test_scanned_pdf_without_ocr_requires_review() -> None:
    # Given: a PDF page without a text layer.
    content = (FIXTURES / "scanned-page.pdf").read_bytes()

    # When: no OCR provider is configured.
    document = PdfParser().parse("doc-2", content, "scan.pdf")

    # Then: an empty success is never reported.
    assert document.blocks == ()
    assert document.warnings == ("ocr_required:page1",)


def test_pdf_ocrs_only_text_deficient_pages() -> None:
    # Given: an OCR provider and a scanned page.
    provider = RecordingOcr(
        result=(OcrBlock("recognized", (1.0, 2.0, 20.0, 12.0), 0.91),),
        pages=[],
    )
    content = (FIXTURES / "scanned-page.pdf").read_bytes()

    # When: the PDF is parsed.
    document = PdfParser(ocr_provider=provider).parse("doc-ocr", content, "scan.pdf")

    # Then: OCR provenance and confidence are retained for that page only.
    assert provider.pages == [1]
    assert document.blocks[0].provenance == "ocr"
    assert document.blocks[0].confidence == 0.91
    assert document.warnings == ()


def test_pdf_preserves_stable_ocr_failure() -> None:
    # Given: an OCR provider that reports a safe provider code.
    provider = RecordingOcr(result=OcrFailure("provider_timeout"), pages=[])
    content = (FIXTURES / "scanned-page.pdf").read_bytes()

    # When: parsing requests OCR.
    document = PdfParser(ocr_provider=provider).parse("doc-failed", content, "scan.pdf")

    # Then: the failure is reviewable and contains no provider body.
    assert document.blocks == ()
    assert document.warnings == ("ocr_failed:provider_timeout:page1",)


def test_pdf_enforces_ocr_timeout() -> None:
    # Given: a provider slower than its parser-owned timeout.
    content = (FIXTURES / "scanned-page.pdf").read_bytes()

    # When: the deficient page requests OCR.
    document = PdfParser(ocr_provider=SlowOcr(), ocr_timeout_seconds=0.01).parse(
        "doc-timeout", content, "scan.pdf"
    )

    # Then: cancellation becomes a finite review warning.
    assert document.blocks == ()
    assert document.warnings == ("ocr_failed:timeout:page1",)


def test_pdf_rejects_invalid_ocr_coordinates() -> None:
    # Given: provider output with non-finite, out-of-bounds evidence coordinates.
    provider = RecordingOcr(result=(OcrBlock("unsafe", (nan, 0.0, 1.0, 1.0), 2.0),), pages=[])
    content = (FIXTURES / "scanned-page.pdf").read_bytes()

    # When: the provider output is validated.
    document = PdfParser(ocr_provider=provider).parse("doc-invalid-ocr", content, "scan.pdf")

    # Then: invalid evidence is excluded and the page remains reviewable.
    assert document.blocks == ()
    assert document.warnings == ("ocr_failed:invalid_output:page1",)


def test_pdf_ocrs_only_scanned_page_in_mixed_document() -> None:
    # Given: two text-layer pages followed by one scanned page.
    text = fitz.open(stream=(FIXTURES / "text-layer.pdf").read_bytes(), filetype="pdf")
    scanned = fitz.open(stream=(FIXTURES / "scanned-page.pdf").read_bytes(), filetype="pdf")
    mixed = fitz.open()
    mixed.insert_pdf(text)
    mixed.insert_pdf(scanned)
    content = mixed.tobytes(garbage=4, deflate=True, no_new_id=True)
    mixed.close()
    scanned.close()
    text.close()
    provider = RecordingOcr(result=(OcrBlock("page three", (1.0, 1.0, 30.0, 20.0), 0.9),), pages=[])

    # When: the mixed document is parsed.
    document = PdfParser(ocr_provider=provider).parse("doc-mixed", content, "mixed.pdf")

    # Then: only the deficient page crosses the OCR boundary.
    assert provider.pages == [3]
    assert any(block.page == 3 and block.provenance == "ocr" for block in document.blocks)


def test_pdf_rejects_encrypted_input() -> None:
    # Given: a password-protected PDF.
    source = fitz.open(stream=(FIXTURES / "text-layer.pdf").read_bytes(), filetype="pdf")
    content = source.tobytes(
        encryption=PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
    )
    source.close()

    # When: parsing is attempted without credentials.
    with pytest.raises(DocumentParseError) as caught:
        _ = PdfParser().parse("doc-encrypted", content, "encrypted.pdf")

    # Then: encryption has a finite boundary code.
    assert caught.value.code == "encrypted_pdf"


def test_pdf_rejects_page_count_over_limit() -> None:
    # Given: a structurally valid PDF above the parser page budget.
    source = fitz.open()
    for _ in range(101):
        _ = source.new_page()
    content = source.tobytes(garbage=4, deflate=True, no_new_id=True)
    source.close()

    # When: parsing is attempted.
    with pytest.raises(DocumentParseError) as caught:
        _ = PdfParser().parse("doc-pages", content, "many-pages.pdf")

    # Then: the page limit is enforced before extraction or OCR.
    assert caught.value.code == "pdf_page_limit"


@pytest.mark.parametrize(
    ("payload", "filename", "code"),
    [
        (b"not-a-pdf", "bad.pdf", "invalid_pdf"),
        (b"%PDF-truncated", "bad.pdf", "invalid_pdf"),
        (b"%PDF-1.4\n", "bad.txt", "unsupported_document"),
    ],
)
def test_pdf_rejects_invalid_boundaries(payload: bytes, filename: str, code: str) -> None:
    # Given: malformed PDF boundary input.

    # When: parsing is attempted.
    with pytest.raises(DocumentParseError) as caught:
        _ = PdfParser().parse("doc-bad", payload, filename)

    # Then: a finite stable code is exposed.
    assert caught.value.code == code
