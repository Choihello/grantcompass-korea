"""Reviewed synthetic benchmark case specifications."""

from dataclasses import dataclass
from typing import Final, Literal

type BenchmarkRuleKind = Literal[
    "business_age_months",
    "representative_age",
    "region",
    "industry",
]
type BenchmarkOperator = Literal["lte", "lt", "gte", "gt", "in", "not_in"]
type BenchmarkExpectedValue = str | int

FULLWIDTH_COLON: Final = "\N{FULLWIDTH COLON}"


@dataclass(frozen=True, slots=True)
class ExpectedRule:
    """Normalized machine fields and quote for one generated rule."""

    kind: BenchmarkRuleKind
    operator: BenchmarkOperator
    expected_value: BenchmarkExpectedValue
    quote: str


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """One distinct generated document and its reviewed expected rules."""

    number: int
    text: str
    rules: tuple[ExpectedRule, ...]


def _case(number: int, text: str, *rules: ExpectedRule) -> CaseSpec:
    return CaseSpec(number, text, rules)


def _single_rule_case(
    number: int,
    text: str,
    kind: BenchmarkRuleKind,
    operator: BenchmarkOperator,
    value: BenchmarkExpectedValue,
) -> CaseSpec:
    return _case(number, text, ExpectedRule(kind, operator, value, text))


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
        ExpectedRule("business_age_months", "lte", 36, "업력 3년 이내"),
        ExpectedRule("representative_age", "lte", 39, "대표자 만 39세 이하"),
        ExpectedRule("region", "in", "대전광역시", "대전광역시 소재 기업"),
        ExpectedRule("industry", "not_in", "도박업", "도박업 제외"),
    ),
)
