"""Bounded, injected OCR contract for PDF pages."""

from dataclasses import dataclass
from math import isfinite
from typing import Final, Protocol

from grantcompass.domain.json_types import JsonValue

OCR_BBOX_COORDINATES: Final = 4


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
    """Untrusted OCR candidate returned by an injected provider."""

    text: JsonValue
    bbox: tuple[JsonValue, ...] | JsonValue
    confidence: JsonValue


@dataclass(frozen=True, slots=True)
class ValidatedOcrBlock:
    """Provider block parsed into evidence-safe coordinates and text."""

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True, slots=True)
class OcrFailure:
    """Stable provider failure safe to persist and display."""

    code: str


type OcrProviderOutput = OcrFailure | tuple[OcrBlock | JsonValue, ...] | JsonValue


class OcrProvider(Protocol):
    """Recognize one bounded page image without parser-owned external I/O."""

    async def recognize(self, page: OcrPage) -> OcrProviderOutput:
        """Return recognized blocks or a finite safe failure code."""
        ...


def validate_ocr_output(
    outcome: OcrProviderOutput,
    width: int,
    height: int,
) -> tuple[ValidatedOcrBlock, ...] | OcrFailure:
    """Parse untrusted provider output into finite evidence or failure."""
    if isinstance(outcome, OcrFailure):
        code = outcome.code
        safe = code if code.isascii() and code.replace("_", "").isalnum() else "provider"
        return OcrFailure(safe)
    if not isinstance(outcome, tuple):
        return OcrFailure("invalid_output")
    blocks: list[ValidatedOcrBlock] = []
    for candidate in outcome:
        if not isinstance(candidate, OcrBlock):
            return OcrFailure("invalid_output")
        text = candidate.text
        bbox = candidate.bbox
        confidence = candidate.confidence
        if (
            not isinstance(text, str)
            or not isinstance(bbox, tuple)
            or not isinstance(confidence, (int, float))
            or type(confidence) is bool
        ):
            return OcrFailure("invalid_output")
        coordinates = _parse_bbox(bbox, width, height)
        if (
            not text.strip()
            or not isfinite(confidence)
            or not 0 <= confidence <= 1
            or coordinates is None
        ):
            return OcrFailure("invalid_output")
        blocks.append(ValidatedOcrBlock(text, coordinates, float(confidence)))
    return tuple(blocks) if blocks else OcrFailure("invalid_output")


def _parse_bbox(
    bbox: tuple[JsonValue, ...],
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    if len(bbox) != OCR_BBOX_COORDINATES:
        return None
    x0 = _finite_number(bbox[0])
    y0 = _finite_number(bbox[1])
    x1 = _finite_number(bbox[2])
    y1 = _finite_number(bbox[3])
    if x0 is None or y0 is None or x1 is None or y1 is None:
        return None
    return (x0, y0, x1, y1) if 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height else None


def _finite_number(value: JsonValue) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None
