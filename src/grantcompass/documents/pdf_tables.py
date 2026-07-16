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
    existing = {(block.page, block.text) for block in text_blocks}
    try:
        with pdfplumber.open(BytesIO(content)) as document:
            for page_index, page in enumerate(document.pages):
                page_number = page_index + 1
                for table_index, table in enumerate(page.find_tables()):
                    values = [cell for row in table.extract() for cell in row]
                    for cell_index, (cell, bbox) in enumerate(
                        zip(values, table.cells, strict=False)
                    ):
                        text = " ".join((cell or "").split())
                        if not text or (page_number, text) in existing:
                            continue
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
                                bbox=(
                                    float(bbox[0]),
                                    float(bbox[1]),
                                    float(bbox[2]),
                                    float(bbox[3]),
                                ),
                                provenance="pdf_table",
                            )
                        )
    except (PDFSyntaxError, ValueError):
        raise parse_failure(INVALID_PDF, MALFORMED_TABLE_MESSAGE) from None
    return tuple(blocks)
