"""Extract layout-aware PDF tables behind a finite parse-failure boundary."""

from io import BytesIO
from typing import Final

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError

from grantcompass.documents.base import DocumentBlock, ParseErrorCode, parse_failure
from grantcompass.domain.documents import DocumentBlockId

INVALID_PDF: Final[ParseErrorCode] = "invalid_pdf"
MALFORMED_TABLE_MESSAGE: Final = "PDF table structure is malformed"


def extract_table_blocks(
    content: bytes,
    text_blocks: list[DocumentBlock],
) -> tuple[DocumentBlock, ...]:
    """Return page-positioned cells in deterministic numeric table order."""
    blocks: list[DocumentBlock] = []
    try:
        with pdfplumber.open(BytesIO(content)) as document:
            for page_index, page in enumerate(document.pages):
                page_number = page_index + 1
                for table_index, table in enumerate(page.find_tables()):
                    for row_index, (values, row) in enumerate(
                        zip(table.extract(), table.rows, strict=True)
                    ):
                        for column_index, (cell, bbox) in enumerate(
                            zip(values, row.cells, strict=True)
                        ):
                            if bbox is None:
                                continue
                            text = " ".join((cell or "").split())
                            normalized_bbox = (
                                float(bbox[0]),
                                float(bbox[1]),
                                float(bbox[2]),
                                float(bbox[3]),
                            )
                            if not text or _duplicates_native(
                                page_number, text, normalized_bbox, text_blocks
                            ):
                                continue
                            cell_index = row_index * len(values) + column_index
                            table_ref = f"table{table_index}:cell{cell_index:04d}"
                            blocks.append(
                                DocumentBlock(
                                    block_id=DocumentBlockId(f"page{page_number}:{table_ref}"),
                                    ordinal=len(blocks),
                                    kind="table_cell",
                                    text=text,
                                    page=page_number,
                                    section_path=None,
                                    table_ref=table_ref,
                                    bbox=normalized_bbox,
                                    provenance="pdf_table",
                                )
                            )
    except (PDFSyntaxError, ValueError):
        raise parse_failure(INVALID_PDF, MALFORMED_TABLE_MESSAGE) from None
    return tuple(blocks)


def _duplicates_native(
    page: int,
    text: str,
    bbox: tuple[float, float, float, float],
    native_blocks: list[DocumentBlock],
) -> bool:
    return any(
        block.page == page
        and block.text == text
        and block.bbox is not None
        and _overlaps(block.bbox, bbox)
        for block in native_blocks
    )


def _overlaps(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return max(left[0], right[0]) < min(left[2], right[2]) and max(left[1], right[1]) < min(
        left[3], right[3]
    )
