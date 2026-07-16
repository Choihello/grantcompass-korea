"""Shared immutable document parsing contract."""

from typing import Literal, final

from grantcompass.domain.documents import DocumentBlock, ParsedDocument

ParseErrorCode = Literal[
    "archive_too_large",
    "invalid_archive",
    "invalid_document_id",
    "invalid_pdf",
    "invalid_xml",
    "encrypted_pdf",
    "missing_content",
    "pdf_page_limit",
    "unsafe_archive_path",
    "unsupported_document",
]

__all__ = [
    "DocumentBlock",
    "DocumentParseError",
    "ParseErrorCode",
    "ParsedDocument",
    "parse_failure",
]


@final
class DocumentParseError(Exception):
    """Stable, machine-readable failure at a document parsing boundary."""

    def __init__(self, code: ParseErrorCode, message: str) -> None:
        """Store a stable code separately from human-readable context."""
        self._code: ParseErrorCode = code
        self._message: str = message
        super().__init__(f"{code}: {message}")

    @property
    def code(self) -> ParseErrorCode:
        """Return the immutable machine-readable failure code."""
        return self._code

    @property
    def message(self) -> str:
        """Return the immutable human-readable failure context."""
        return self._message


def parse_failure(code: ParseErrorCode, message: str) -> DocumentParseError:
    """Build a parse exception without coupling callers to display formatting."""
    return DocumentParseError(code, message)
