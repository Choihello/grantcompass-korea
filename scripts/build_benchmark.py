#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pymupdf>=1.24,<2",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run scripts/build_benchmark.py
# 3. Or choose an output root:
#      uv run scripts/build_benchmark.py --output-root tests/fixtures/benchmark
# ──────────────────

"""Generate the deterministic public HWPX/PDF eligibility benchmark."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypedDict, runtime_checkable
from urllib.parse import quote
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pymupdf as fitz

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

type RuleKind = Literal[
    "business_age_months",
    "representative_age",
    "region",
    "industry",
]
type Operator = Literal["lte", "lt", "gte", "gt", "in", "not_in"]
type ExpectedValue = str | int


class _ManifestRule(TypedDict):
    kind: RuleKind
    operator: Operator
    expected_value: ExpectedValue
    required: Literal[True]
    review_status: Literal["automatic"]
    rule_version: Literal["regex-v1"]


class _ManifestLocation(TypedDict):
    document_id: str
    block_id: str
    source_url: str
    page: int | None
    section_path: str | None
    quote: str
    content_hash: str


class _ManifestRow(TypedDict):
    fixture_path: str
    document_id: str
    content_hash: str
    expected_rules: list[_ManifestRule]
    expected_locations: list[_ManifestLocation]
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


DEFAULT_OUTPUT: Final = Path("tests/fixtures/benchmark")
FIXED_TIMESTAMP: Final = (2026, 1, 1, 0, 0, 0)
REVIEWER_ROLE: Final = "startup-support-program-manager"
FULLWIDTH_COLON: Final = "\N{FULLWIDTH COLON}"
OUTPUT_ARGUMENT_COUNT: Final = 2


@dataclass(frozen=True, slots=True)
class _ExpectedRule:
    kind: RuleKind
    operator: Operator
    expected_value: ExpectedValue
    quote: str


@dataclass(frozen=True, slots=True)
class _CaseSpec:
    number: int
    text: str
    rules: tuple[_ExpectedRule, ...]


def _case(number: int, text: str, *rules: _ExpectedRule) -> _CaseSpec:
    return _CaseSpec(number, text, rules)


def _single_rule_case(
    number: int,
    text: str,
    kind: RuleKind,
    operator: Operator,
    value: ExpectedValue,
) -> _CaseSpec:
    return _case(number, text, _ExpectedRule(kind, operator, value, text))


CASES: Final = (
    _single_rule_case(1, "업력 0개월 이하", "business_age_months", "lte", 0),
    _case(2, "업력 제한은 별도 공고 예정"),
    _single_rule_case(3, "업력 6개월 이상", "business_age_months", "gte", 6),
    _single_rule_case(4, "업력 12개월 초과", "business_age_months", "gt", 12),
    _single_rule_case(5, "업력 1년 이내", "business_age_months", "lte", 12),
    _single_rule_case(6, "업력 2년 이하", "business_age_months", "lte", 24),
    _single_rule_case(7, "업력 3년 미만", "business_age_months", "lt", 36),
    _single_rule_case(8, "업력 4년 이상", "business_age_months", "gte", 48),
    _single_rule_case(9, "업력 5년 초과", "business_age_months", "gt", 60),
    _single_rule_case(10, "창업 후 7년 이내", "business_age_months", "lte", 84),
    _single_rule_case(11, "대표자 만 18세 이하", "representative_age", "lte", 18),
    _single_rule_case(12, "대표자 연령 만 19세 미만", "representative_age", "lt", 19),
    _single_rule_case(13, "대표자 나이 39세 이상", "representative_age", "gte", 39),
    _single_rule_case(14, "대표자 만 40세 초과", "representative_age", "gt", 40),
    _single_rule_case(15, "대표자 연령 50세 이하", "representative_age", "lte", 50),
    _single_rule_case(16, "서울특별시 소재 기업", "region", "in", "서울특별시"),
    _single_rule_case(17, "부산광역시 본사 소재", "region", "in", "부산광역시"),
    _single_rule_case(18, "세종특별자치시 소재", "region", "in", "세종특별자치시"),
    _single_rule_case(19, "제주특별자치도 소재 기업", "region", "in", "제주특별자치도"),
    _single_rule_case(20, "수원시 소재 기업", "region", "in", "수원시"),
    _single_rule_case(21, "서울특별시 소재 기업 제외", "region", "not_in", "서울특별시"),
    _single_rule_case(22, "부산광역시 소재 제외", "region", "not_in", "부산광역시"),
    _single_rule_case(23, "제주특별자치도 소재 기업 제외", "region", "not_in", "제주특별자치도"),
    _single_rule_case(24, "강남구 소재 제외", "region", "not_in", "강남구"),
    _single_rule_case(25, "수원시 소재 기업 제외", "region", "not_in", "수원시"),
    _single_rule_case(26, "도박업 제외", "industry", "not_in", "도박업"),
    _single_rule_case(27, "유흥주점업은 제외", "industry", "not_in", "유흥주점업"),
    _single_rule_case(28, "업종: 사행시설운영업 제외", "industry", "not_in", "사행시설운영업"),
    _single_rule_case(
        29,
        f"업종{FULLWIDTH_COLON}금융업 제외",
        "industry",
        "not_in",
        "금융업",
    ),
    _case(
        30,
        "업력 3년 이내, 대표자 만 39세 이하, 대전광역시 소재 기업, 도박업 제외",
        _ExpectedRule("business_age_months", "lte", 36, "업력 3년 이내"),
        _ExpectedRule("representative_age", "lte", 39, "대표자 만 39세 이하"),
        _ExpectedRule("region", "in", "대전광역시", "대전광역시 소재 기업"),
        _ExpectedRule("industry", "not_in", "도박업", "도박업 제외"),
    ),
)


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


def _manifest_row(case: _CaseSpec, fixture_path: str, content: bytes) -> _ManifestRow:
    content_hash = sha256(content).hexdigest()
    document_id = f"benchmark-{case.number:02d}"
    is_hwpx = fixture_path.endswith(".hwpx")
    block_id = "section0:p0" if is_hwpx else "page1:text1"
    page = None if is_hwpx else 1
    section_path = "Contents/section0.xml" if is_hwpx else None
    source_url = f"grantcompass://documents/{quote(document_id, safe='')}"
    rules: list[_ManifestRule] = [
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
    locations: list[_ManifestLocation] = [
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
        "fixture_path": fixture_path,
        "document_id": document_id,
        "content_hash": content_hash,
        "expected_rules": rules,
        "expected_locations": locations,
        "reviewed_by_role": REVIEWER_ROLE,
    }


def _pymupdf_runtime(module: ModuleType) -> _PymupdfRuntime:
    if not isinstance(module, _PymupdfRuntime):
        message = "PyMuPDF runtime does not expose Font and TextWriter"
        raise TypeError(message)
    return module


def build(output_root: Path) -> None:
    """Regenerate all synthetic sources and the JSONL manifest deterministically."""
    document_root = output_root / "documents"
    document_root.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for case in CASES:
        suffix = ".hwpx" if case.number % 2 else ".pdf"
        filename = f"case-{case.number:02d}{suffix}"
        content = _hwpx(case.text) if suffix == ".hwpx" else _pdf(case.number, case.text)
        _ = (document_root / filename).write_bytes(content)
        row = _manifest_row(case, f"documents/{filename}", content)
        rows.append(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    _ = (output_root / "documents.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")


def main(argv: tuple[str, ...] | None = None) -> None:
    """Parse the output directory and build the benchmark."""
    arguments = tuple(sys.argv[1:]) if argv is None else argv
    if not arguments:
        build(DEFAULT_OUTPUT)
        return
    if len(arguments) == OUTPUT_ARGUMENT_COUNT and arguments[0] == "--output-root":
        build(Path(arguments[1]))
        return
    message = "usage: build_benchmark.py [--output-root PATH]"
    raise SystemExit(message)


if __name__ == "__main__":
    main()
