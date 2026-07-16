"""Pure-bytes HWPX parser with deterministic evidence coordinates."""

from hashlib import sha256
from pathlib import PurePath
from typing import Final

from grantcompass.documents.archive import read_sections
from grantcompass.documents.base import DocumentBlock, ParsedDocument, ParseErrorCode, parse_failure
from grantcompass.documents.hwpx_xml import map_section
from grantcompass.domain.documents import DocumentId

PARSER_NAME = "hwpx"
PARSER_VERSION = "1.0.0"
UNSUPPORTED_DOCUMENT: Final[ParseErrorCode] = "unsupported_document"
INVALID_DOCUMENT_ID: Final[ParseErrorCode] = "invalid_document_id"


class HwpxParser:
    """Convert bounded HWPX ZIP/XML bytes into immutable addressable blocks."""

    def parse(self, document_id: str, content: bytes, filename: str) -> ParsedDocument:
        """Parse caller-owned bytes without filesystem or network access."""
        if PurePath(filename).suffix.casefold() != ".hwpx":
            raise parse_failure(
                UNSUPPORTED_DOCUMENT,
                "HWPX parser requires a .hwpx filename",
            )
        if not document_id.strip():
            raise parse_failure(INVALID_DOCUMENT_ID, "Document identifier is empty")
        blocks: list[DocumentBlock] = []
        ordinal = 0
        table = 0
        for section in read_sections(content):
            mapped = map_section(section, ordinal, table)
            blocks.extend(mapped.blocks)
            ordinal = mapped.next_ordinal
            table = mapped.next_table
        return ParsedDocument(
            document_id=DocumentId(document_id),
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            content_hash=sha256(content).hexdigest(),
            blocks=tuple(blocks),
        )
