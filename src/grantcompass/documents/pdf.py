"""Pure-bytes PDF text, table, and selective OCR parser."""

from hashlib import sha256
from math import ceil, isfinite
from pathlib import PurePath
from typing import Final, Protocol

import anyio
import pymupdf as fitz

from grantcompass.documents.base import DocumentBlock, ParsedDocument, ParseErrorCode, parse_failure
from grantcompass.documents.ocr import OcrBlock, OcrFailure, OcrPage, OcrProvider
from grantcompass.documents.pdf_tables import extract_table_blocks
from grantcompass.domain.documents import DocumentBlockId, DocumentId

PARSER_NAME: Final = "pdf"
PARSER_VERSION: Final = "1.0.0"
MAX_PAGES: Final = 100
OCR_DPI: Final = 144
MAX_OCR_PIXELS: Final = 8_000_000
OCR_TIMEOUT_SECONDS: Final = 30.0
INVALID_PDF: Final[ParseErrorCode] = "invalid_pdf"
ENCRYPTED_PDF: Final[ParseErrorCode] = "encrypted_pdf"
PDF_PAGE_LIMIT: Final[ParseErrorCode] = "pdf_page_limit"
UNSUPPORTED_DOCUMENT: Final[ParseErrorCode] = "unsupported_document"
INVALID_DOCUMENT_ID: Final[ParseErrorCode] = "invalid_document_id"
INVALID_MIN_TEXT_MESSAGE: Final = "min_text_chars_per_page must be non-negative"
INVALID_OCR_TIMEOUT_MESSAGE: Final = "ocr_timeout_seconds must be positive"
MALFORMED_PDF_MESSAGE: Final = "PDF structure is malformed"
ENCRYPTED_PDF_MESSAGE: Final = "Password-protected PDF is unsupported"
PDF_PAGE_LIMIT_MESSAGE: Final = "PDF exceeds the page limit"
PDF_FILENAME_MESSAGE: Final = "PDF parser requires a .pdf filename"
DOCUMENT_ID_MESSAGE: Final = "Document identifier is empty"
PDF_SIGNATURE_MESSAGE: Final = "PDF signature is missing"


class _PageRenderer(Protocol):
    def get_pixmap(self, *, matrix: fitz.Matrix, alpha: bool) -> fitz.Pixmap: ...


class PdfParser:
    """Extract deterministic PDF evidence while OCRing only deficient pages."""

    def __init__(
        self,
        ocr_provider: OcrProvider | None = None,
        min_text_chars_per_page: int = 20,
        ocr_timeout_seconds: float = OCR_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the optional injected OCR boundary and text threshold."""
        if min_text_chars_per_page < 0:
            raise ValueError(INVALID_MIN_TEXT_MESSAGE)
        if ocr_timeout_seconds <= 0:
            raise ValueError(INVALID_OCR_TIMEOUT_MESSAGE)
        self._ocr_provider: OcrProvider | None = ocr_provider
        self._min_text_chars: int = min_text_chars_per_page
        self._ocr_timeout_seconds: float = ocr_timeout_seconds

    def parse(self, document_id: str, content: bytes, filename: str) -> ParsedDocument:
        """Parse caller-owned bytes without filesystem, network, or OS OCR I/O."""
        self._validate_boundary(document_id, content, filename)
        try:
            source = fitz.open(stream=content, filetype="pdf")
        except RuntimeError:
            raise parse_failure(INVALID_PDF, MALFORMED_PDF_MESSAGE) from None
        with source:
            if source.needs_pass or source.is_encrypted:
                raise parse_failure(ENCRYPTED_PDF, ENCRYPTED_PDF_MESSAGE)
            if source.page_count > MAX_PAGES:
                raise parse_failure(PDF_PAGE_LIMIT, PDF_PAGE_LIMIT_MESSAGE)
            blocks, warnings = self._extract_pages(source)
        table_blocks = extract_table_blocks(content, blocks)
        all_blocks = (*blocks, *table_blocks)
        ordered = tuple(sorted(all_blocks, key=self._block_sort_key))
        normalized = tuple(
            DocumentBlock(
                block_id=block.block_id,
                ordinal=ordinal,
                kind=block.kind,
                text=block.text,
                page=block.page,
                section_path=block.section_path,
                table_ref=block.table_ref,
                bbox=block.bbox,
                confidence=block.confidence,
                provenance=block.provenance,
            )
            for ordinal, block in enumerate(ordered)
        )
        return ParsedDocument(
            document_id=DocumentId(document_id),
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            content_hash=sha256(content).hexdigest(),
            blocks=normalized,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _validate_boundary(document_id: str, content: bytes, filename: str) -> None:
        if PurePath(filename).suffix.casefold() != ".pdf":
            raise parse_failure(UNSUPPORTED_DOCUMENT, PDF_FILENAME_MESSAGE)
        if not document_id.strip():
            raise parse_failure(INVALID_DOCUMENT_ID, DOCUMENT_ID_MESSAGE)
        if not content.startswith(b"%PDF-"):
            raise parse_failure(INVALID_PDF, PDF_SIGNATURE_MESSAGE)

    def _extract_pages(self, source: fitz.Document) -> tuple[list[DocumentBlock], list[str]]:
        blocks: list[DocumentBlock] = []
        warnings: list[str] = []
        for page_index in range(source.page_count):
            page = source.load_page(page_index)
            page_number = page_index + 1
            page_blocks = self._text_blocks(page, page_number)
            blocks.extend(page_blocks)
            normalized_chars = sum(len("".join(block.text.split())) for block in page_blocks)
            if normalized_chars < self._min_text_chars:
                ocr_blocks, warning = self._ocr_page(page, page_number)
                blocks.extend(ocr_blocks)
                if warning is not None:
                    warnings.append(warning)
        return blocks, warnings

    @staticmethod
    def _text_blocks(page: fitz.Page, page_number: int) -> tuple[DocumentBlock, ...]:
        raw_blocks: list[tuple[float, float, float, float, str, int, int]] = page.get_text("blocks")
        relevant = sorted(
            (raw for raw in raw_blocks if raw[4].strip()),
            key=lambda raw: (raw[1], raw[0], raw[3], raw[2], raw[5]),
        )
        return tuple(
            DocumentBlock(
                block_id=DocumentBlockId(f"page{page_number}:text{index}"),
                ordinal=index,
                kind="paragraph",
                text=" ".join(raw[4].split()),
                page=page_number,
                section_path=None,
                bbox=(raw[0], raw[1], raw[2], raw[3]),
                provenance="pdf_text",
            )
            for index, raw in enumerate(relevant)
        )

    def _ocr_page(
        self,
        page: fitz.Page,
        page_number: int,
    ) -> tuple[tuple[DocumentBlock, ...], str | None]:
        if self._ocr_provider is None:
            return (), f"ocr_required:page{page_number}"
        prepared = self._prepare_ocr_request(page, page_number)
        if prepared is None:
            return (), f"ocr_failed:pixel_limit:page{page_number}"
        request, pixmap, scale = prepared
        try:
            outcome = anyio.run(self._recognize_with_timeout, request)
        except TimeoutError:
            return (), f"ocr_failed:timeout:page{page_number}"
        except Exception:  # noqa: BLE001
            return (), f"ocr_failed:provider:page{page_number}"
        match outcome:
            case OcrFailure(code=code):
                safe_code = (
                    code if code.isascii() and code.replace("_", "").isalnum() else "provider"
                )
                return (), f"ocr_failed:{safe_code}:page{page_number}"
            case tuple() as recognized:
                valid = tuple(block for block in recognized if self._valid_ocr_block(block, pixmap))
                warning = (
                    f"ocr_failed:invalid_output:page{page_number}"
                    if len(valid) != len(recognized)
                    else None
                )
                return self._map_ocr_blocks(valid, page_number, scale), warning

    def _prepare_ocr_request(
        self,
        page: fitz.Page,
        page_number: int,
    ) -> tuple[OcrPage, fitz.Pixmap, float] | None:
        scale = OCR_DPI / 72
        expected_width = ceil(page.rect.width * scale)
        expected_height = ceil(page.rect.height * scale)
        if expected_width * expected_height > MAX_OCR_PIXELS:
            return None
        pixmap = self._render_page(page, scale)
        if pixmap.width * pixmap.height > MAX_OCR_PIXELS:
            return None
        request = OcrPage(
            page=page_number,
            png=pixmap.tobytes("png"),
            width=pixmap.width,
            height=pixmap.height,
            dpi=OCR_DPI,
            max_pixels=MAX_OCR_PIXELS,
            timeout_seconds=self._ocr_timeout_seconds,
        )
        return request, pixmap, scale

    @staticmethod
    def _render_page(renderer: _PageRenderer, scale: float) -> fitz.Pixmap:
        return renderer.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)

    async def _recognize_with_timeout(
        self,
        request: OcrPage,
    ) -> tuple[OcrBlock, ...] | OcrFailure:
        if self._ocr_provider is None:
            return OcrFailure("provider")
        with anyio.fail_after(self._ocr_timeout_seconds):
            return await self._ocr_provider.recognize(request)

    @staticmethod
    def _valid_ocr_block(block: OcrBlock, pixmap: fitz.Pixmap) -> bool:
        x0, y0, x1, y1 = block.bbox
        values = (*block.bbox, block.confidence)
        return (
            all(isfinite(value) for value in values)
            and 0 <= x0 < x1 <= pixmap.width
            and 0 <= y0 < y1 <= pixmap.height
            and 0 <= block.confidence <= 1
        )

    @staticmethod
    def _map_ocr_blocks(
        recognized: tuple[OcrBlock, ...],
        page_number: int,
        scale: float,
    ) -> tuple[DocumentBlock, ...]:
        ordered = sorted(recognized, key=lambda block: (*block.bbox, block.text))
        return tuple(
            DocumentBlock(
                block_id=DocumentBlockId(f"page{page_number}:ocr{index}"),
                ordinal=index,
                kind="ocr_text",
                text=" ".join(block.text.split()),
                page=page_number,
                section_path=None,
                bbox=(
                    block.bbox[0] / scale,
                    block.bbox[1] / scale,
                    block.bbox[2] / scale,
                    block.bbox[3] / scale,
                ),
                confidence=block.confidence,
                provenance="ocr",
            )
            for index, block in enumerate(ordered)
            if block.text.strip()
        )

    @staticmethod
    def _block_sort_key(block: DocumentBlock) -> tuple[int, float, float, str]:
        bbox = block.bbox or (0.0, 0.0, 0.0, 0.0)
        return (block.page or 0, bbox[1], bbox[0], str(block.block_id))
