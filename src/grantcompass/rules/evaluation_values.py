"""Typed parsing and comparison of normalized rule values."""

from collections.abc import Callable
from operator import ge, gt, le, lt
from typing import Final
from unicodedata import normalize

from pydantic import ConfigDict, TypeAdapter, ValidationError

from grantcompass.domain.eligibility import ExpectedValue
from grantcompass.domain.json_types import FrozenJsonValue
from grantcompass.rules.evaluation_types import EvaluationOutcome, satisfied, unknown

type Numeric = int | float

_CODE_TUPLE_ADAPTER: Final = TypeAdapter[tuple[str, ...]](
    tuple[str, ...],
    config=ConfigDict(strict=True),
)
_CODE_ADAPTER: Final = TypeAdapter[str](str, config=ConfigDict(strict=True))
_PERFORMANCE_ADAPTER: Final = TypeAdapter[tuple[str, Numeric]](
    tuple[str, Numeric],
    config=ConfigDict(strict=True),
)
_NUMBER_ADAPTER: Final = TypeAdapter[Numeric](Numeric, config=ConfigDict(strict=True))
_NUMERIC_COMPARATORS: Final[dict[str, Callable[[Numeric, Numeric], bool]]] = {
    "lte": le,
    "lt": lt,
    "gte": ge,
    "gt": gt,
}


def expected_codes(value: ExpectedValue) -> frozenset[str] | None:
    """Parse a nonempty scalar or tuple of normalized codes."""
    try:
        codes = _CODE_TUPLE_ADAPTER.validate_python(value)
    except ValidationError:
        try:
            codes = (_CODE_ADAPTER.validate_python(value),)
        except ValidationError:
            return None
    if not codes or any(not code.strip() for code in codes):
        return None
    return frozenset(normalized_code(code) for code in codes)


def performance_expected(value: ExpectedValue) -> tuple[str, Numeric] | None:
    """Parse the exact `(metric_key, numeric_threshold)` schema."""
    try:
        metric, threshold = _PERFORMANCE_ADAPTER.validate_python(value)
    except ValidationError:
        return None
    if not metric.strip():
        return None
    return normalized_code(metric), threshold


def numeric_value(value: ExpectedValue | FrozenJsonValue) -> Numeric | None:
    """Parse a strict JSON number while rejecting booleans and containers."""
    try:
        return _NUMBER_ADAPTER.validate_python(value)
    except ValidationError:
        return None


def numeric_comparison(
    actual: Numeric,
    operator: str,
    expected: Numeric,
) -> EvaluationOutcome:
    """Evaluate a supported numeric operator or return a visible failure."""
    comparator = _NUMERIC_COMPARATORS.get(operator)
    if comparator is None:
        return unknown("unsupported_operator")
    return satisfied(value=comparator(actual, expected))


def normalized_code(value: str) -> str:
    """Normalize one official region, industry, metric, or program code."""
    return " ".join(normalize("NFKC", value).casefold().split())
