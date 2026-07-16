"""Deterministic eligibility-rule candidates with exact parser evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from grantcompass.domain.documents import DocumentBlock, Evidence, ParsedDocument
from grantcompass.domain.eligibility import EligibilityRule, ExpectedValue
from grantcompass.domain.enums import ReviewStatus, RuleKind
from grantcompass.rules.candidate_evidence import (
    EvidenceIntegrityError,
    EvidenceIntegrityErrorCode,
    source_url_for_document,
    validate_candidates,
)

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = (
    "EvidenceIntegrityError",
    "EvidenceIntegrityErrorCode",
    "RegexRuleCandidateProvider",
    "validate_candidates",
)

_FULLWIDTH_COLON: Final = "\N{FULLWIDTH COLON}"
_COLON_CLASS: Final = rf"[:{_FULLWIDTH_COLON}]"
_PUNCTUATION_CLASS: Final = rf"[,.;:{_FULLWIDTH_COLON}]"
_BUSINESS_AGE: Final = re.compile(
    "".join(
        (
            rf"(?:업력(?:\s*[은는])?|창업\s*후)\s*{_COLON_CLASS}?\s*",
            r"(?P<value>\d{1,3})\s*(?P<unit>년|개월)\s*",
            r"(?P<operator>이내|이하|미만|이상|초과)",
        )
    )
)
_REPRESENTATIVE_AGE: Final = re.compile(
    r"대표자(?:\s*(?:연령|나이))?\s*(?:만\s*)?(?P<value>\d{1,3})\s*세\s*(?P<operator>이하|미만|이상|초과)"
)
_REGION_NAME: Final = r"[가-힣]{2,}(?:특별자치시|특별자치도|특별시|광역시|도|시|군|구)"
_REGION_EXCLUSION: Final = re.compile(
    "".join(
        (
            rf"(?P<value>{_REGION_NAME})\s*",
            r"(?:소재(?:\s*기업)?|본사\s*소재)\s*",
            rf"(?:[은는을를]\s*)?(?:{_PUNCTUATION_CLASS}\s*)?제외",
        )
    )
)
_REGION_INCLUSION: Final = re.compile(
    rf"(?P<value>{_REGION_NAME})\s*(?:소재(?:\s*기업)?|본사\s*소재)"
)
_INDUSTRY_EXCLUSION: Final = re.compile(
    "".join(
        (
            rf"(?:업종\s*{_COLON_CLASS}?\s*)?",
            r"(?P<value>[가-힣A-Za-z0-9·]+업)\s*(?:[은는을를]\s*)?제외",
        )
    )
)
_FOLLOWING_NEGATION: Final = re.compile(
    rf"\s*(?:{_PUNCTUATION_CLASS}\s*)?(?:지원\s*)?(?:불가|제외)"
)
_FOLLOWING_AGE_BOUND: Final = re.compile(r"\s+\d{1,3}\s*(?:년|개월)\s*(?:이내|이하|미만|이상|초과)")
_GENERIC_INDUSTRY_NOUNS: Final = frozenset({"기업", "창업"})
_OPERATORS: Final = {
    "이내": "lte",
    "이하": "lte",
    "미만": "lt",
    "이상": "gte",
    "초과": "gt",
}
_RULE_VERSION: Final = "regex-v1"


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
            source_url=source_url_for_document(str(document.document_id)),
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


def _matches(text: str) -> tuple[_RuleMatch, ...]:
    business_age = tuple(
        candidate
        for candidate in _pattern_matches(
            _BUSINESS_AGE,
            text,
            RuleKind.BUSINESS_AGE_MONTHS,
            _business_value,
        )
        if not _has_following_negation(text, candidate)
        and not _has_following_age_bound(text, candidate)
    )
    representative_age = tuple(
        candidate
        for candidate in _pattern_matches(
            _REPRESENTATIVE_AGE,
            text,
            RuleKind.REPRESENTATIVE_AGE,
            _integer_value,
        )
        if not _has_following_negation(text, candidate)
    )
    industries = tuple(
        candidate
        for candidate in _pattern_matches(
            _INDUSTRY_EXCLUSION,
            text,
            RuleKind.INDUSTRY,
            _string_value,
            "not_in",
        )
        if candidate.expected_value not in _GENERIC_INDUSTRY_NOUNS
    )
    matches = [
        *business_age,
        *representative_age,
        *_pattern_matches(_REGION_EXCLUSION, text, RuleKind.REGION, _string_value, "not_in"),
        *_pattern_matches(_REGION_INCLUSION, text, RuleKind.REGION, _string_value, "in"),
        *industries,
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


def _has_following_negation(text: str, candidate: _RuleMatch) -> bool:
    return _FOLLOWING_NEGATION.match(text, candidate.span[1]) is not None


def _has_following_age_bound(text: str, candidate: _RuleMatch) -> bool:
    return _FOLLOWING_AGE_BOUND.match(text, candidate.span[1]) is not None
