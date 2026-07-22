"""Human-effective assessment state for consultation reports."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.storage.audit_schemas import parse_assessment_audit_state
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import AssessmentRow


@dataclass(frozen=True, slots=True)
class OverrideState:
    """One effective condition override loaded from immutable audit state."""

    rule_assessment_id: int
    status: str


@dataclass(frozen=True, slots=True)
class CurrentReviewState:
    """Latest human-effective aggregate and attribution for one assessment."""

    effective_final_status: str
    reviewer: str
    reason: str
    overrides: tuple[OverrideState, ...]

    def override_for(self, rule_assessment_id: int) -> str | None:
        """Return the explicit override for one condition identity."""
        return next(
            (
                item.status
                for item in self.overrides
                if item.rule_assessment_id == rule_assessment_id
            ),
            None,
        )


async def load_current_review(
    session: AsyncSession,
    assessment: AssessmentRow,
) -> CurrentReviewState:
    """Load the latest valid attributed review or the untouched automatic state."""
    audit = await session.scalar(
        select(AuditEventRow)
        .where(
            AuditEventRow.entity_type == "assessment",
            AuditEventRow.entity_id == str(assessment.id),
            AuditEventRow.action == "review",
        )
        .order_by(AuditEventRow.id.desc())
        .limit(1)
    )
    if audit is None or audit.after_json is None:
        return CurrentReviewState(assessment.final_status, "-", "-", ())
    state = parse_assessment_audit_state(audit.after_json)
    return CurrentReviewState(
        effective_final_status=state.effective_final_status,
        reviewer=audit.actor_name,
        reason=audit.reason,
        overrides=tuple(
            OverrideState(item.rule_assessment_id, item.status) for item in state.overrides
        ),
    )


__all__ = ["CurrentReviewState", "OverrideState", "load_current_review"]
