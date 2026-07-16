"""Stable document download and ingestion failures."""

from typing import Literal, final, override

DocumentIngestErrorCode = Literal[
    "attachment_missing",
    "attachment_too_large",
    "download_failed",
    "download_url_missing",
    "invalid_attachment_type",
    "redirect_limit",
    "redirect_loop",
    "unsafe_download_target",
]


@final
class DocumentIngestError(Exception):
    """Machine-readable attachment failure without response bodies or secrets."""

    def __init__(self, code: DocumentIngestErrorCode) -> None:
        """Store only the stable code safe for persistence."""
        self._code: DocumentIngestErrorCode = code
        super().__init__(code)

    @property
    def code(self) -> DocumentIngestErrorCode:
        """Return the stable machine-readable error code."""
        return self._code

    @override
    def __str__(self) -> str:
        """Avoid leaking target URLs, headers, or response bodies."""
        return self._code
