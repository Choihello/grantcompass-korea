"""Final eligibility aggregation."""

from collections.abc import Sequence

from grantcompass.domain.enums import ConditionStatus, FinalStatus


def aggregate_final_status(statuses: Sequence[ConditionStatus]) -> FinalStatus:
    """Apply the fixed eligibility precedence to condition outcomes."""
    if not statuses:
        return FinalStatus.NEEDS_REVIEW
    if ConditionStatus.UNSATISFIED in statuses:
        return FinalStatus.INELIGIBLE
    if ConditionStatus.UNKNOWN in statuses or ConditionStatus.CONFLICT in statuses:
        return FinalStatus.NEEDS_REVIEW
    if ConditionStatus.CONDITIONAL in statuses:
        return FinalStatus.CONDITIONAL
    return FinalStatus.ELIGIBLE
