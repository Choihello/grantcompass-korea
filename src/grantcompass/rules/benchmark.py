"""Typed boundary models for the synthetic document benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, ClassVar, Final, Literal, override

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from grantcompass.domain.documents import Evidence
    from grantcompass.domain.eligibility import EligibilityRule

type BenchmarkRuleKind = Literal[
    "business_age_months",
    "representative_age",
    "region",
    "industry",
]
type BenchmarkOperator = Literal["lte", "lt", "gte", "gt", "in", "not_in"]
type BenchmarkValue = str | int
type ManifestErrorCode = Literal[
    "invalid_jsonl",
    "empty_manifest",
    "unsafe_fixture_path",
    "unsupported_fixture_type",
]

_AUTOMATIC: Final = "automatic"
_RULE_VERSION: Final = "regex-v1"
_INVALID_JSONL: Final[ManifestErrorCode] = "invalid_jsonl"
_EMPTY_MANIFEST: Final[ManifestErrorCode] = "empty_manifest"
_UNSAFE_FIXTURE_PATH: Final[ManifestErrorCode] = "unsafe_fixture_path"
_UNSUPPORTED_FIXTURE_TYPE: Final[ManifestErrorCode] = "unsupported_fixture_type"
_BENCHMARK_KINDS: Final[dict[str, BenchmarkRuleKind]] = {
    "business_age_months": "business_age_months",
    "representative_age": "representative_age",
    "region": "region",
    "industry": "industry",
}
_BENCHMARK_OPERATORS: Final[dict[str, BenchmarkOperator]] = {
    "lte": "lte",
    "lt": "lt",
    "gte": "gte",
    "gt": "gt",
    "in": "in",
    "not_in": "not_in",
}
_BENCHMARK_VALUE_ADAPTER: Final = TypeAdapter[BenchmarkValue](
    BenchmarkValue,
    config=ConfigDict(strict=True),
)


@dataclass(frozen=True, slots=True)
class BenchmarkManifestError(Exception):
    """Finite failure raised while parsing an untrusted benchmark manifest."""

    code: ManifestErrorCode
    line_number: int | None = None

    @override
    def __str__(self) -> str:
        """Return the stable code with an optional one-based line number."""
        return self.code if self.line_number is None else f"{self.code}:line{self.line_number}"


class BenchmarkRule(BaseModel):
    """Exact normalized rule expected from one benchmark source."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    kind: BenchmarkRuleKind
    operator: BenchmarkOperator
    expected_value: BenchmarkValue
    required: Literal[True]
    review_status: Literal["automatic"]
    rule_version: Literal["regex-v1"]

    @classmethod
    def from_rule(cls, rule: EligibilityRule) -> BenchmarkRule:
        """Project a deterministic domain rule into its serialized benchmark shape."""
        try:
            value = _BENCHMARK_VALUE_ADAPTER.validate_python(rule.expected_value)
        except ValidationError as error:
            raise BenchmarkManifestError(_INVALID_JSONL) from error
        return cls(
            kind=_benchmark_kind(rule.kind.value),
            operator=_benchmark_operator(rule.operator),
            expected_value=value,
            required=_benchmark_required(value=rule.required),
            review_status=_benchmark_review_status(rule.review_status.value),
            rule_version=_benchmark_rule_version(rule.rule_version),
        )


class BenchmarkLocation(BaseModel):
    """Exact evidence location expected from one normalized rule."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    block_id: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^grantcompass://documents/")
    page: int | None
    section_path: str | None
    quote: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_evidence(cls, evidence: Evidence) -> BenchmarkLocation:
        """Project domain evidence into its serialized benchmark shape."""
        return cls(
            document_id=str(evidence.document_id),
            block_id=str(evidence.block_id),
            source_url=evidence.source_url,
            page=evidence.page,
            section_path=evidence.section_path,
            quote=evidence.quote,
            content_hash=evidence.content_hash,
        )


class BenchmarkCase(BaseModel):
    """One reviewed synthetic binary and its exact expected extraction."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    fixture_path: str
    document_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_rules: tuple[BenchmarkRule, ...]
    expected_locations: tuple[BenchmarkLocation, ...]
    reviewed_by_role: Literal["startup-support-program-manager"]


def load_benchmark_cases(path: Path) -> tuple[BenchmarkCase, ...]:
    """Parse every non-empty JSONL row exactly once through Pydantic."""
    rows = path.read_bytes().splitlines()
    if not rows:
        raise BenchmarkManifestError(_EMPTY_MANIFEST)
    cases: list[BenchmarkCase] = []
    for line_number, row in enumerate(rows, start=1):
        try:
            case = BenchmarkCase.model_validate_json(row)
        except ValidationError as error:
            raise BenchmarkManifestError(_INVALID_JSONL, line_number) from error
        try:
            _ = resolve_benchmark_fixture(path.parent, case.fixture_path)
        except BenchmarkManifestError as error:
            raise BenchmarkManifestError(error.code, line_number) from error
        cases.append(case)
    return tuple(cases)


def resolve_benchmark_fixture(root: Path, fixture_path: str) -> Path:
    """Resolve one canonical fixture path while confining it to the benchmark root."""
    parts = fixture_path.split("/")
    if (
        "\\" in fixture_path
        or ":" in fixture_path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise BenchmarkManifestError(_UNSAFE_FIXTURE_PATH)
    posix_path = PurePosixPath(fixture_path)
    if posix_path.is_absolute():
        raise BenchmarkManifestError(_UNSAFE_FIXTURE_PATH)
    if posix_path.suffix.casefold() not in {".hwpx", ".pdf"}:
        raise BenchmarkManifestError(_UNSUPPORTED_FIXTURE_TYPE)
    resolved_root = root.resolve()
    resolved = resolved_root.joinpath(*parts).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise BenchmarkManifestError(_UNSAFE_FIXTURE_PATH)
    return resolved


def _benchmark_kind(value: str) -> BenchmarkRuleKind:
    kind = _BENCHMARK_KINDS.get(value)
    if kind is None:
        raise BenchmarkManifestError(_INVALID_JSONL)
    return kind


def _benchmark_operator(value: str) -> BenchmarkOperator:
    operator = _BENCHMARK_OPERATORS.get(value)
    if operator is None:
        raise BenchmarkManifestError(_INVALID_JSONL)
    return operator


def _benchmark_required(*, value: bool) -> Literal[True]:
    if not value:
        raise BenchmarkManifestError(_INVALID_JSONL)
    return True


def _benchmark_review_status(value: str) -> Literal["automatic"]:
    if value != _AUTOMATIC:
        raise BenchmarkManifestError(_INVALID_JSONL)
    return "automatic"


def _benchmark_rule_version(value: str) -> Literal["regex-v1"]:
    if value != _RULE_VERSION:
        raise BenchmarkManifestError(_INVALID_JSONL)
    return "regex-v1"
