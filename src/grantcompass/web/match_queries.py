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
    assessments = tuple(latest_by_profile.values())
    if not assessments:
        return ()
    profile_ids = tuple(assessment.profile_id for assessment in assessments)
    profiles = tuple(
        (
            await session.scalars(
                select(ApplicantProfileRow).where(ApplicantProfileRow.id.in_(profile_ids))
            )
        ).all()
    )
    profiles_by_id = {profile.id: profile for profile in profiles}
    assessment_ids = tuple(assessment.id for assessment in assessments)
    condition_rows = await session.execute(
        select(RuleAssessmentRow, EligibilityRuleRow)
        .join(EligibilityRuleRow, EligibilityRuleRow.id == RuleAssessmentRow.rule_id)
        .where(RuleAssessmentRow.assessment_id.in_(assessment_ids))
        .order_by(RuleAssessmentRow.assessment_id, RuleAssessmentRow.id)
    )
    conditions_by_assessment: dict[int, list[tuple[RuleAssessmentRow, EligibilityRuleRow]]] = {}
    for row, rule in condition_rows.tuples():
        conditions_by_assessment.setdefault(row.assessment_id, []).append((row, rule))
    audit_rows = tuple(
        (
            await session.scalars(
                select(AuditEventRow)
                .where(
                    AuditEventRow.entity_type == "assessment",
                    AuditEventRow.entity_id.in_(tuple(str(value) for value in assessment_ids)),
                    AuditEventRow.action == "review",
                )
                .order_by(AuditEventRow.id.desc())
            )
        ).all()
    )
    latest_audit_by_assessment: dict[int, AuditEventRow] = {}
    for audit in audit_rows:
        _ = latest_audit_by_assessment.setdefault(int(audit.entity_id), audit)
    return tuple(
        _match_entry(
            assessment,
            profiles_by_id.get(assessment.profile_id),
            tuple(conditions_by_assessment.get(assessment.id, ())),
            latest_audit_by_assessment.get(assessment.id),
        )
        for assessment in assessments
    )


def _match_entry(
    assessment: AssessmentRow,
    profile: ApplicantProfileRow | None,
    rows: tuple[tuple[RuleAssessmentRow, EligibilityRuleRow], ...],
    audit: AuditEventRow | None,
) -> MatchEntry:
    if profile is None:
        message = "assessment_profile_not_found"
        raise LookupError(message)
    state = (
        parse_assessment_audit_state(audit.after_json)
        if audit is not None and audit.after_json is not None
        else None
    )
    override_by_id = (
        {item.rule_assessment_id: item.status for item in state.overrides} if state else {}
    )
    conditions: list[MatchConditionEntry] = []
    for row, rule in rows:
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
