"""Bounded, injected OCR contract for PDF pages."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OcrPage:
    """Rendered page image and hard resource limits supplied to OCR."""

    page: int
    png: bytes
    width: int
    height: int
    dpi: int
    max_pixels: int
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class OcrBlock:
    """One OCR text block with page-local coordinates and confidence."""

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True, slots=True)
class OcrFailure:
    """Stable provider failure safe to persist and display."""

    code: str


class OcrProvider(Protocol):
    """Recognize one bounded page image without parser-owned external I/O."""

    async def recognize(self, page: OcrPage) -> tuple[OcrBlock, ...] | OcrFailure:
        """Return recognized blocks or a finite safe failure code."""
        ...
