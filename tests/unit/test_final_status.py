import pytest

from grantcompass.domain.enums import ConditionStatus, FinalStatus
from grantcompass.rules.aggregate import aggregate_final_status


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (
            (ConditionStatus.UNSATISFIED, ConditionStatus.UNKNOWN),
            FinalStatus.INELIGIBLE,
        ),
        (
            (ConditionStatus.CONFLICT, ConditionStatus.SATISFIED),
            FinalStatus.NEEDS_REVIEW,
        ),
        (
            (ConditionStatus.UNKNOWN, ConditionStatus.CONDITIONAL),
            FinalStatus.NEEDS_REVIEW,
        ),
        (
            (ConditionStatus.CONDITIONAL, ConditionStatus.SATISFIED),
            FinalStatus.CONDITIONAL,
        ),
        ((ConditionStatus.SATISFIED,), FinalStatus.ELIGIBLE),
        ((), FinalStatus.NEEDS_REVIEW),
    ],
)
def test_final_status_precedence(
    statuses: tuple[ConditionStatus, ...],
    expected: FinalStatus,
) -> None:
    # Given: a complete sequence of condition statuses.

    # When: the deterministic aggregate is calculated.
    result = aggregate_final_status(statuses)

    # Then: the exact precedence contract is preserved.
    assert result is expected
