"""Atomic human assessment reviews with append-only audit history."""

from typing import final

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import (
    AuditErrorCode,
    AuditEvent,
    AuditValidationError,
)
from grantcompass.domain.enums import ReviewStatus
from grantcompass.domain.ids import AssessmentId
from grantcompass.domain.json_types import FrozenJsonObject
from grantcompass.domain.reviews import AssessmentReview, AssessmentReviewCommand
from grantcompass.storage.audit_chain import validate_assessment_after_state
from grantcompass.storage.audit_json import (
    audit_event_from_row,
    dump_audit_json,
    validate_attribution,
)
from grantcompass.storage.audit_schemas import (
    AssessmentAuditState,
    parse_assessment_audit_state,
)
from grantcompass.storage.read_scope import RepositoryReadScope
from grantcompass.storage.review_builders import (
    ReviewSource,
    automatic_review_snapshot,
    build_assessment_review,
    completed_review_snapshot,
    parse_review_status,
    validate_review_overrides,
)
from grantcompass.storage.table_cases import AuditEventRow
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow


@final
class AssessmentRepository:
    """Review immutable automatic assessments in one async unit of work."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind review operations to one caller-owned session."""
        self._session = session

    async def review(self, command: AssessmentReviewCommand) -> AssessmentReview:
        """Persist review progress and one attributed audit event atomically."""
        actor, reason = validate_attribution(command.actor, command.reason, command.reviewed_at)
        async with self._session.begin():
            assessment = await self._session.get(AssessmentRow, int(command.assessment_id))
            if assessment is None:
                raise AuditValidationError(AuditErrorCode.ASSESSMENT_NOT_FOUND)
            original_status = parse_review_status(assessment.review_status)
            observed_revision = _validated_review_revision(assessment.review_revision)
            persisted_revision = await self._session.scalar(
                select(AssessmentRow.review_revision).where(AssessmentRow.id == assessment.id)
            )
            if persisted_revision != observed_revision:
                raise AuditValidationError(AuditErrorCode.CONCURRENT_CHANGE)
            next_revision = observed_revision + 1
            conditions = tuple(
                (
                    await self._session.scalars(
                        select(RuleAssessmentRow)
                        .where(RuleAssessmentRow.assessment_id == assessment.id)
                        .order_by(RuleAssessmentRow.id)
                    )
                ).all()
            )
            requested_ids = tuple(int(item.rule_assessment_id) for item in command.overrides)
            persisted_overrides = (
                tuple(
                    (
                        await self._session.scalars(
                            select(RuleAssessmentRow).where(RuleAssessmentRow.id.in_(requested_ids))
                        )
                    ).all()
                )
                if requested_ids
                else ()
            )
            override_by_id = validate_review_overrides(
                command.assessment_id,
                command.overrides,
                persisted_overrides,
            )
            review = build_assessment_review(
                ReviewSource(assessment, conditions, override_by_id),
                command.reviewed_at,
            )
            prior = await self._latest_audit_after(command.assessment_id)
            before = (
                automatic_review_snapshot(review, original_status, observed_revision)
                if prior is None
                else prior[0]
            )
            if prior is not None:
                validate_assessment_after_state(
                    prior[1],
                    review,
                    original_status,
                    observed_revision,
                )
            updated_id = await self._session.scalar(
                update(AssessmentRow)
                .where(
                    AssessmentRow.id == assessment.id,
                    AssessmentRow.review_status == assessment.review_status,
                    AssessmentRow.review_revision == observed_revision,
                )
                .values(
                    review_status=ReviewStatus.REVIEWED.value,
                    review_revision=next_revision,
                )
                .returning(AssessmentRow.id)
            )
            if updated_id != assessment.id:
                raise AuditValidationError(AuditErrorCode.CONCURRENT_CHANGE)
            after = completed_review_snapshot(review, next_revision)
            self._session.add(
                AuditEventRow(
                    entity_type="assessment",
                    entity_id=str(assessment.id),
                    action="review",
                    actor_name=actor,
                    reason=reason,
                    before_json=dump_audit_json(before),
                    after_json=dump_audit_json(after),
                    created_at=command.reviewed_at,
                )
            )
            return review

    async def audit_events(self, assessment_id: AssessmentId) -> tuple[AuditEvent, ...]:
        """Return immutable assessment audit events oldest-first."""
        async with RepositoryReadScope(self._session):
            if await self._session.get(AssessmentRow, int(assessment_id)) is None:
                raise AuditValidationError(AuditErrorCode.ASSESSMENT_NOT_FOUND)
            rows = (
                await self._session.scalars(
                    select(AuditEventRow)
                    .where(
                        AuditEventRow.entity_id == str(int(assessment_id)),
                        or_(
                            AuditEventRow.action == "review",
                            AuditEventRow.entity_type == "assessment",
                        ),
                    )
                    .order_by(AuditEventRow.id)
                )
            ).all()
            return tuple(audit_event_from_row(row) for row in rows)

    async def _latest_audit_after(
        self,
        assessment_id: AssessmentId,
    ) -> tuple[FrozenJsonObject, AssessmentAuditState] | None:
        row = await self._session.scalar(
            select(AuditEventRow)
            .where(
                AuditEventRow.entity_id == str(int(assessment_id)),
                or_(
                    AuditEventRow.action == "review",
                    AuditEventRow.entity_type == "assessment",
                ),
            )
            .order_by(AuditEventRow.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        event = audit_event_from_row(row)
        if event.after_json is None:
            raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT)
        try:
            state = parse_assessment_audit_state(dump_audit_json(event.after_json))
        except ValidationError:
            raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT) from None
        return event.after_json, state


def _validated_review_revision(value: int) -> int:
    if isinstance(value, bool) or value < 0:
        raise AuditValidationError(AuditErrorCode.MALFORMED_ASSESSMENT)
    return value
