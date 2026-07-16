"""Frozen boundary models for the independent assessment benchmark."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Final, Literal, override

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from grantcompass.domain.documents import (
    DocumentBlockId,
    DocumentId,
    Evidence,
    EvidenceId,
)
from grantcompass.domain.eligibility import (
    ApplicantProfile,
    EligibilityRule,
    EligibilityRuleId,
    ExpectedValue,
)
from grantcompass.domain.enums import (
    ConditionStatus,
    FinalStatus,
    ReviewStatus,
    RuleKind,
)
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.json_types import JsonScalar

type BenchmarkErrorCode = Literal[
    "invalid_jsonl",
    "wrong_case_count",
    "duplicate_case_id",
    "duplicate_input_signature",
]
type BenchmarkFeature = Literal[
    "boundary",
    "missing_fact",
    "malformed_expected",
    "unsupported_kind",
    "conflict",
    "unrelated_non_conflict",
    "conditional",
    "review_required",
    "evaluator_failure",
    "leap_day",
    "end_of_month",
]

_EXPECTED_CASE_COUNT: Final = 100
_INVALID_JSONL: Final[BenchmarkErrorCode] = "invalid_jsonl"
_WRONG_CASE_COUNT: Final[BenchmarkErrorCode] = "wrong_case_count"
_DUPLICATE_CASE_ID: Final[BenchmarkErrorCode] = "duplicate_case_id"
_DUPLICATE_INPUT_SIGNATURE: Final[BenchmarkErrorCode] = "duplicate_input_signature"


@dataclass(frozen=True, slots=True)
class AssessmentBenchmarkError(Exception):
    """Finite benchmark-manifest parsing failure."""

    code: BenchmarkErrorCode
    line_number: int | None = None

    @override
    def __str__(self) -> str:
        """Return the stable code and optional one-based line number."""
        return self.code if self.line_number is None else f"{self.code}:line{self.line_number}"


class BenchmarkRule(BaseModel):
    """Compact persisted rule input for one synthetic case."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    id: int
    program_id: int
    kind: RuleKind
    operator: str
    expected_value: JsonScalar | tuple[JsonScalar, ...]
    evidence_id: int
    source: str = Field(min_length=1)
    required: bool = True
    review_status: ReviewStatus = ReviewStatus.AUTOMATIC
    rule_version: str = "assessment-v1"

    def to_domain(self) -> EligibilityRule:
        """Build the immutable domain rule without calculating an expected result."""
        evidence = Evidence(
            id=EvidenceId(self.evidence_id),
            document_id=DocumentId(f"benchmark-{self.source}"),
            block_id=DocumentBlockId(f"rule-{self.id}"),
            source_url=f"https://example.invalid/{self.source}",
            page=1,
            section_path="eligibility",
            quote=f"rule-{self.id}",
            content_hash=f"{self.evidence_id:064x}",
        )
        return EligibilityRule(
            id=EligibilityRuleId(self.id),
            program_id=ProgramId(self.program_id),
            kind=self.kind,
            operator=self.operator,
            expected_value=_expected_value(self.expected_value),
            required=self.required,
            review_status=self.review_status,
            rule_version=self.rule_version,
            evidence=(evidence,),
        )

    def input_signature(self) -> str:
        """Return the substantive rule input without persistence identities."""
        return "|".join(
            (
                self.kind.value,
                self.operator,
                repr(self.expected_value),
                str(self.required),
                self.review_status.value,
                self.rule_version,
            )
        )


class ExpectedBenchmarkItem(BaseModel):
    """Independent exact oracle for one rule assessment."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    rule_id: int
    status: ConditionStatus
    evidence_ids: tuple[int, ...]
    error_id: str | None = None

    def domain_signature(
        self,
    ) -> tuple[EligibilityRuleId, ConditionStatus, str | None, tuple[EvidenceId, ...]]:
        """Project only the machine-consumed expected assessment fields."""
        return (
            EligibilityRuleId(self.rule_id),
            self.status,
            self.error_id,
            tuple(EvidenceId(value) for value in self.evidence_ids),
        )


class AssessmentBenchmarkCase(BaseModel):
    """One frozen profile/rules input and independently declared oracle."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    assessed_at: datetime
    profile: ApplicantProfile
    rules: tuple[BenchmarkRule, ...] = Field(min_length=1)
    expected_items: tuple[ExpectedBenchmarkItem, ...] = Field(min_length=1)
    expected_final_status: FinalStatus
    expected_review_status: ReviewStatus
    evaluator_failure_kind: RuleKind | None = None
    coverage: tuple[BenchmarkFeature, ...] = ()
    reviewed_by_role: Literal["startup-support-program-manager"]

    def input_signature(self) -> str:
        """Return a stable substantive signature excluding case and persistence IDs."""
        profile = self.profile.model_dump_json(exclude={"id", "display_name"})
        rules = "||".join(rule.input_signature() for rule in self.rules)
        failure = "" if self.evaluator_failure_kind is None else self.evaluator_failure_kind.value
        return f"{self.assessed_at.isoformat()}|{profile}|{rules}|{failure}"


def load_assessment_cases(path: Path) -> tuple[AssessmentBenchmarkCase, ...]:
    """Parse and validate exactly 100 unique JSONL cases."""
    cases: list[AssessmentBenchmarkCase] = []
    for line_number, row in enumerate(path.read_bytes().splitlines(), start=1):
        try:
            cases.append(AssessmentBenchmarkCase.model_validate_json(row))
        except ValidationError as error:
            raise AssessmentBenchmarkError(_INVALID_JSONL, line_number) from error
    if len(cases) != _EXPECTED_CASE_COUNT:
        raise AssessmentBenchmarkError(_WRONG_CASE_COUNT)
    if len({case.case_id for case in cases}) != len(cases):
        raise AssessmentBenchmarkError(_DUPLICATE_CASE_ID)
    if len({case.input_signature() for case in cases}) != len(cases):
        raise AssessmentBenchmarkError(_DUPLICATE_INPUT_SIGNATURE)
    return tuple(cases)


def _expected_value(value: JsonScalar | tuple[JsonScalar, ...]) -> ExpectedValue:
    return value
