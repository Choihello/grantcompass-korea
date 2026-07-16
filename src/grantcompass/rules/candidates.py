"""Deterministic eligibility-rule candidates with exact parser evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override
from urllib.parse import quote

from grantcompass.domain.documents import DocumentBlock, Evidence, ParsedDocument
from grantcompass.domain.eligibility import EligibilityRule, ExpectedValue
from grantcompass.domain.enums import ReviewStatus, RuleKind

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

type EvidenceIntegrityErrorCode = Literal[
    "missing_evidence",
    "unknown_block_id",
    "document_id_mismatch",
    "content_hash_mismatch",
    "source_url_mismatch",
    "page_mismatch",
    "section_path_mismatch",
    "quote_not_in_block",
]

_BUSINESS_AGE: Final = re.compile(
    r"(?:업력|창업\s*후)\s*(?P<value>\d{1,3})\s*(?P<unit>년|개월)\s*(?P<operator>이내|이하|미만|이상|초과)"
)
_REPRESENTATIVE_AGE: Final = re.compile(
    r"대표자(?:\s*(?:연령|나이))?\s*(?:만\s*)?(?P<value>\d{1,3})\s*세\s*(?P<operator>이하|미만|이상|초과)"
)
_REGION_NAME: Final = r"[가-힣]{2,}(?:특별자치시|특별자치도|특별시|광역시|도|시|군|구)"
_REGION_EXCLUSION: Final = re.compile(rf"(?P<value>{_REGION_NAME})\s*소재\s*(?:기업\s*)?제외")
_REGION_INCLUSION: Final = re.compile(
    rf"(?P<value>{_REGION_NAME})\s*(?:소재(?:\s*기업)?|본사\s*소재)"
)
_INDUSTRY_EXCLUSION: Final = re.compile(
    r"(?:업종\s*[:\N{FULLWIDTH COLON}]?\s*)?(?P<value>[가-힣A-Za-z0-9·]+업)\s*(?:은\s*)?제외"
)
_OPERATORS: Final = {
    "이내": "lte",
    "이하": "lte",
    "미만": "lt",
    "이상": "gte",
    "초과": "gt",
}
_RULE_VERSION: Final = "regex-v1"
_MISSING_EVIDENCE: Final[EvidenceIntegrityErrorCode] = "missing_evidence"
_UNKNOWN_BLOCK_ID: Final[EvidenceIntegrityErrorCode] = "unknown_block_id"


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityError(Exception):
    """Finite evidence-integrity failure safe for boundary handling."""

    code: EvidenceIntegrityErrorCode

    @override
    def __str__(self) -> str:
        """Return the stable machine-readable integrity code."""
        return self.code


@dataclass(frozen=True, slots=True)
class _RuleMatch:
    kind: RuleKind
    operator: str
    expected_value: ExpectedValue
    span: tuple[int, int]
    quote: str


class RegexRuleCandidateProvider:
    """Extract the intentionally narrow deterministic rule families."""

    def extract(self, document: ParsedDocument) -> tuple[EligibilityRule, ...]:
        """Return candidates in parser block and source-text order."""
        rules = tuple(
            self._build_rule(document, block, candidate)
            for block in document.blocks
            for candidate in _matches(block.text)
        )
        return validate_candidates(rules, document)

    @staticmethod
    def _build_rule(
        document: ParsedDocument,
        block: DocumentBlock,
        candidate: _RuleMatch,
    ) -> EligibilityRule:
        evidence = Evidence(
            document_id=document.document_id,
            block_id=block.block_id,
            source_url=_source_url(str(document.document_id)),
            page=block.page,
            section_path=block.section_path,
            quote=candidate.quote,
            content_hash=document.content_hash,
        )
        return EligibilityRule(
            kind=candidate.kind,
            operator=candidate.operator,
            expected_value=candidate.expected_value,
            required=True,
            review_status=ReviewStatus.AUTOMATIC,
            rule_version=_RULE_VERSION,
            evidence=(evidence,),
        )


def validate_candidates(
    rules: Sequence[EligibilityRule],
    document: ParsedDocument,
) -> tuple[EligibilityRule, ...]:
    """Reject candidates whose evidence does not exactly match parser output."""
    blocks = {block.block_id: block for block in document.blocks}
    expected_url = _source_url(str(document.document_id))
    for rule in rules:
        if not rule.evidence:
            raise EvidenceIntegrityError(_MISSING_EVIDENCE)
        for evidence in rule.evidence:
            block = blocks.get(evidence.block_id)
            if block is None:
                raise EvidenceIntegrityError(_UNKNOWN_BLOCK_ID)
            _validate_evidence(evidence, block, document, expected_url)
    return tuple(rules)


def _validate_evidence(
    evidence: Evidence,
    block: DocumentBlock,
    document: ParsedDocument,
    expected_url: str,
) -> None:
    checks: tuple[tuple[bool, EvidenceIntegrityErrorCode], ...] = (
        (evidence.document_id == document.document_id, "document_id_mismatch"),
        (evidence.content_hash == document.content_hash, "content_hash_mismatch"),
        (evidence.source_url == expected_url, "source_url_mismatch"),
        (evidence.page == block.page, "page_mismatch"),
        (evidence.section_path == block.section_path, "section_path_mismatch"),
        (evidence.quote in block.text, "quote_not_in_block"),
    )
    for valid, code in checks:
        if not valid:
            raise EvidenceIntegrityError(code)


def _matches(text: str) -> tuple[_RuleMatch, ...]:
    matches = [
        *_pattern_matches(_BUSINESS_AGE, text, RuleKind.BUSINESS_AGE_MONTHS, _business_value),
        *_pattern_matches(
            _REPRESENTATIVE_AGE,
            text,
            RuleKind.REPRESENTATIVE_AGE,
            _integer_value,
        ),
        *_pattern_matches(_REGION_EXCLUSION, text, RuleKind.REGION, _string_value, "not_in"),
        *_pattern_matches(_REGION_INCLUSION, text, RuleKind.REGION, _string_value, "in"),
        *_pattern_matches(
            _INDUSTRY_EXCLUSION,
            text,
            RuleKind.INDUSTRY,
            _string_value,
            "not_in",
        ),
    ]
    selected: list[_RuleMatch] = []
    for candidate in sorted(
        matches, key=lambda item: (item.span[0], -(item.span[1] - item.span[0]))
    ):
        if not any(_overlaps(candidate.span, existing.span) for existing in selected):
            selected.append(candidate)
    return tuple(selected)


def _pattern_matches(
    pattern: re.Pattern[str],
    text: str,
    kind: RuleKind,
    value_builder: Callable[[re.Match[str]], ExpectedValue],
    fixed_operator: str | None = None,
) -> tuple[_RuleMatch, ...]:
    return tuple(
        _RuleMatch(
            kind=kind,
            operator=fixed_operator or _OPERATORS[match["operator"]],
            expected_value=value_builder(match),
            span=match.span(),
            quote=match.group(),
        )
        for match in pattern.finditer(text)
    )


def _business_value(match: re.Match[str]) -> int:
    value = int(match["value"])
    return value * 12 if match["unit"] == "년" else value


def _integer_value(match: re.Match[str]) -> int:
    return int(match["value"])


def _string_value(match: re.Match[str]) -> str:
    return match["value"]


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _source_url(document_id: str) -> str:
    return f"grantcompass://documents/{quote(document_id, safe='')}"
