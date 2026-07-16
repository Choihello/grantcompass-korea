"""Deterministic HWPX/PDF rendering and manifest projection."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypedDict, runtime_checkable
from urllib.parse import quote
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pymupdf as fitz

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

    from grantcompass.rules.benchmark_cases import (
        BenchmarkExpectedValue,
        BenchmarkOperator,
        BenchmarkRuleKind,
        CaseSpec,
    )

FIXED_TIMESTAMP: Final = (2026, 1, 1, 0, 0, 0)
REVIEWER_ROLE: Final = "startup-support-program-manager"


class ManifestRule(TypedDict):
    """Serialized normalized rule fields."""

    kind: BenchmarkRuleKind
    operator: BenchmarkOperator
    expected_value: BenchmarkExpectedValue
    required: Literal[True]
    review_status: Literal["automatic"]
    rule_version: Literal["regex-v1"]


class ManifestLocation(TypedDict):
    """Serialized evidence coordinate fields."""

    document_id: str
    block_id: str
    source_url: str
    page: int | None
    section_path: str | None
    quote: str
    content_hash: str


class ManifestRow(TypedDict):
    """Serialized manifest row fields."""

    fixture_path: str
    document_id: str
    content_hash: str
    expected_rules: list[ManifestRule]
    expected_locations: list[ManifestLocation]
    reviewed_by_role: str


class _Font(Protocol):
    @property
    def name(self) -> str: ...


class _TextWriter(Protocol):
    def append(
        self,
        point: tuple[int, int],
        text: str,
        *,
        font: _Font,
        fontsize: int,
    ) -> None: ...

    def write_text(self, page: fitz.Page) -> None: ...


@runtime_checkable
class _PymupdfRuntime(Protocol):
    Font: Callable[[str], _Font]
    TextWriter: Callable[[fitz.Rect], _TextWriter]


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    """One generated source binary and its canonical relative path."""

    fixture_path: str
    content: bytes


def render_case(case: CaseSpec) -> GeneratedArtifact:
    """Render one case in its alternating real-parser source format."""
    suffix = ".hwpx" if case.number % 2 else ".pdf"
    filename = f"case-{case.number:02d}{suffix}"
    content = _hwpx(case.text) if suffix == ".hwpx" else _pdf(case.number, case.text)
    return GeneratedArtifact(f"documents/{filename}", content)


def manifest_row(case: CaseSpec, artifact: GeneratedArtifact) -> ManifestRow:
    """Project reviewed expectations onto the generated parser coordinates."""
    content_hash = sha256(artifact.content).hexdigest()
    document_id = f"benchmark-{case.number:02d}"
    is_hwpx = artifact.fixture_path.endswith(".hwpx")
    block_id = "section0:p0" if is_hwpx else "page1:text1"
    page = None if is_hwpx else 1
    section_path = "Contents/section0.xml" if is_hwpx else None
    source_url = f"grantcompass://documents/{quote(document_id, safe='')}"
    rules: list[ManifestRule] = [
        {
            "kind": rule.kind,
            "operator": rule.operator,
            "expected_value": rule.expected_value,
            "required": True,
            "review_status": "automatic",
            "rule_version": "regex-v1",
        }
        for rule in case.rules
    ]
    locations: list[ManifestLocation] = [
        {
            "document_id": document_id,
            "block_id": block_id,
            "source_url": source_url,
            "page": page,
            "section_path": section_path,
            "quote": rule.quote,
            "content_hash": content_hash,
        }
        for rule in case.rules
    ]
    return {
        "fixture_path": artifact.fixture_path,
        "document_id": document_id,
        "content_hash": content_hash,
        "expected_rules": rules,
        "expected_locations": locations,
        "reviewed_by_role": REVIEWER_ROLE,
    }


def _zip_entry(name: str, content: bytes, compression: int) -> tuple[ZipInfo, bytes]:
    info = ZipInfo(name, FIXED_TIMESTAMP)
    info.compress_type = compression
    info.create_system = 0
    info.external_attr = 0
    return info, content


def _hwpx(text: str) -> bytes:
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="urn:grantcompass:section" xmlns:hp="urn:grantcompass:paragraph">'
        f"<hp:p><hp:run><hp:t>{escape(text)}</hp:t></hp:run></hp:p>"
        "</hs:sec>"
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for info, content in (
            _zip_entry("mimetype", b"application/hwp+zip", ZIP_STORED),
            _zip_entry("Contents/section0.xml", section, ZIP_DEFLATED),
        ):
            _ = archive.writestr(info, content)
    return output.getvalue()


def _pdf(case_number: int, text: str) -> bytes:
    document = fitz.open()
    page = document.new_page(width=842, height=595)
    runtime = _pymupdf_runtime(fitz)
    writer = runtime.TextWriter(page.rect)
    font = runtime.Font("korea")
    writer.append(
        (72, 72),
        f"공개 합성 벤치마크 지원사업 {case_number:02d}",
        font=font,
        fontsize=12,
    )
    writer.append(
        (72, 96),
        f"{text} 재현성 검증 문서",
        font=font,
        fontsize=12,
    )
    writer.write_text(page)
    content = document.tobytes(garbage=4, deflate=True, no_new_id=True)
    document.close()
    return content


def _pymupdf_runtime(module: ModuleType) -> _PymupdfRuntime:
    if not isinstance(module, _PymupdfRuntime):
        message = "PyMuPDF runtime does not expose Font and TextWriter"
        raise TypeError(message)
    return module
