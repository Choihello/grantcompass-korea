"""Form-to-domain adapters for institution mutations."""

from hashlib import sha256

from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import CaseId
from grantcompass.domain.eligibility import EligibilityRuleId
from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import freeze_json_object
from grantcompass.domain.programs import AttachmentRef, RawNotice
from grantcompass.domain.reviews import ConditionOverride, RuleAssessmentId
from grantcompass.storage.table_cases import CaseRow, ManagedCompanyRow
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow
from grantcompass.web.forms import ManualProgramForm, ReviewConditionForm

_INVALID_REVIEW_STATUS = "invalid_review_status"


def manual_raw_notice(
    form: ManualProgramForm,
    filename: str | None,
    instant: str,
) -> RawNotice:
    """Convert one validated registration form into a manual raw notice."""
    identity = sha256(
        f"{form.title}|{form.organization}|{form.application_end}|{form.source_url}|{instant}".encode()
    ).hexdigest()[:24]
    attachments = (
        (AttachmentRef(filename=filename, download_url=form.source_url),) if filename else ()
    )
    return RawNotice(
        source=SourceName.MANUAL,
        source_notice_id=f"manual-{identity}",
        title=form.title,
        organization=form.organization,
        application_end=form.application_end,
        detail_url=HttpUrl(str(form.source_url)),
        attachments=attachments,
        raw_payload=freeze_json_object({"registration": "institution"}),
    )


async def review_overrides(
    session: AsyncSession,
    assessment: AssessmentRow,
    requested: tuple[ReviewConditionForm, ...],
) -> tuple[ConditionOverride, ...]:
    """Resolve submitted condition identities to their persisted rule identities."""
    rows = tuple(
        (
            await session.scalars(
                select(RuleAssessmentRow)
                .where(RuleAssessmentRow.assessment_id == assessment.id)
                .order_by(RuleAssessmentRow.id)
            )
        ).all()
    )
    row_by_id = {row.id: row for row in rows}
    requested_ids = tuple(item.rule_assessment_id for item in requested)
    if len(set(requested_ids)) != len(requested_ids) or set(requested_ids) != set(row_by_id):
        raise ValueError(_INVALID_REVIEW_STATUS)
    return tuple(
        ConditionOverride(
            RuleAssessmentId(item.rule_assessment_id),
            EligibilityRuleId(row_by_id[item.rule_assessment_id].rule_id),
            item.status,
        )
        for item in requested
        if item.status is not None
    )


async def case_for_assessment(
    session: AsyncSession,
    program_id: int,
    profile_id: int,
) -> CaseId | None:
    """Resolve the support case linked to one program/profile assessment."""
    value = await session.scalar(
        select(CaseRow.id)
        .join(ManagedCompanyRow, ManagedCompanyRow.id == CaseRow.managed_company_id)
        .where(
            CaseRow.program_id == program_id,
            ManagedCompanyRow.profile_id == profile_id,
        )
        .limit(1)
    )
    return CaseId(value) if value is not None else None


__all__ = ["case_for_assessment", "manual_raw_notice", "review_overrides"]
