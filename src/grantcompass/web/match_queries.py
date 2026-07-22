"""Latest-only reverse-match review read models."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.storage.audit_schemas import parse_assessment_audit_state
from grantcompass.storage.table_cases import AuditEventRow, ManagedCompanyRow
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    EligibilityRuleRow,
    RuleAssessmentRow,
)


@dataclass(frozen=True, slots=True)
class MatchConditionEntry:
    """Automatic and human-effective state for one condition identity."""

    rule_assessment_id: int
    kind: str
    automatic_status: str
    override_status: str | None
    effective_status: str


@dataclass(frozen=True, slots=True)
class MatchEntry:
    """One deterministic latest assessment for a managed profile."""

    assessment_id: int
    company_name: str
    automatic_final_status: str
    effective_final_status: str
    review_status: str
    review_revision: int
    reviewer: str
    review_reason: str
    conditions: tuple[MatchConditionEntry, ...]


async def latest_matches(session: AsyncSession, program_id: int) -> tuple[MatchEntry, ...]:
    """Return exactly one latest assessment per managed profile."""
    candidates = (
        await session.scalars(
            select(AssessmentRow)
            .join(ManagedCompanyRow, ManagedCompanyRow.profile_id == AssessmentRow.profile_id)
            .where(AssessmentRow.program_id == program_id)
            .order_by(
                AssessmentRow.profile_id,
                AssessmentRow.assessed_at.desc(),
                AssessmentRow.id.desc(),
            )
        )
    ).all()
    latest_by_profile: dict[int, AssessmentRow] = {}
    for assessment in candidates:
        _ = latest_by_profile.setdefault(assessment.profile_id, assessment)
    return tuple(
        [await _match_entry(session, assessment) for assessment in latest_by_profile.values()]
    )


async def _match_entry(session: AsyncSession, assessment: AssessmentRow) -> MatchEntry:
    profile = await session.get(ApplicantProfileRow, assessment.profile_id)
    if profile is None:
        message = "assessment_profile_not_found"
        raise LookupError(message)
    rows = (
        await session.scalars(
            select(RuleAssessmentRow)
            .where(RuleAssessmentRow.assessment_id == assessment.id)
            .order_by(RuleAssessmentRow.id)
        )
    ).all()
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
    state = (
        parse_assessment_audit_state(audit.after_json)
        if audit is not None and audit.after_json is not None
        else None
    )
    override_by_id = (
        {item.rule_assessment_id: item.status for item in state.overrides} if state else {}
    )
    conditions: list[MatchConditionEntry] = []
    for row in rows:
        rule = await session.get(EligibilityRuleRow, row.rule_id)
        if rule is None:
            message = "assessment_rule_not_found"
            raise LookupError(message)
        override = override_by_id.get(row.id)
        conditions.append(
            MatchConditionEntry(
                rule_assessment_id=row.id,
                kind=rule.kind,
                automatic_status=row.status,
                override_status=override,
                effective_status=override or row.status,
            )
        )
    return MatchEntry(
        assessment_id=assessment.id,
        company_name=profile.display_name,
        automatic_final_status=assessment.final_status,
        effective_final_status=state.effective_final_status if state else assessment.final_status,
        review_status=assessment.review_status,
        review_revision=assessment.review_revision,
        reviewer=audit.actor_name if audit else "-",
        review_reason=audit.reason if audit else "-",
        conditions=tuple(conditions),
    )


__all__ = ["MatchConditionEntry", "MatchEntry", "latest_matches"]
