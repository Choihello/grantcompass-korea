"""Shared immutable document parsing contract."""

from typing import final

from grantcompass.domain.documents import DocumentBlock, ParsedDocument

__all__ = ["DocumentBlock", "DocumentParseError", "ParsedDocument", "parse_failure"]


@final
class DocumentParseError(Exception):
    """Stable, machine-readable failure at a document parsing boundary."""

    def __init__(self, code: str, message: str) -> None:
        """Store a stable code separately from human-readable context."""
        self.code: str = code
        self.message: str = message
        super().__init__(f"{code}: {message}")


def parse_failure(code: str, message: str) -> DocumentParseError:
    """Build a parse exception without coupling callers to display formatting."""
    return DocumentParseError(code, message)
