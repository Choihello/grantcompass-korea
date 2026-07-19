"""Atomic support-case transitions and append-only audit retrieval."""

from datetime import datetime
from typing import assert_never, final

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.cases import (
    AuditErrorCode,
    AuditEvent,
    AuditValidationError,
    Case,
    CaseId,
    CaseTransition,
    ManagedCompanyId,
)
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.ids import ProgramId
from grantcompass.domain.json_types import FrozenJsonObject, freeze_json_object
from grantcompass.storage.audit_chain import validate_case_after_state
from grantcompass.storage.audit_json import (
    audit_event_from_row,
    aware_utc,
    dump_audit_json,
    validate_attribution,
)
from grantcompass.storage.audit_schemas import CaseAuditState, parse_case_audit_state
from grantcompass.storage.read_scope import RepositoryReadScope
from grantcompass.storage.table_cases import AuditEventRow, CaseRow


@final
class CaseRepository:
    """Persist optimistic case transitions in one caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind case operations to one async unit of work."""
        self._session = session

    async def transition(self, command: CaseTransition) -> Case:
        """Move one case along the allowed graph and append one audit event."""
        actor, reason = validate_attribution(command.actor, command.reason, command.occurred_at)
        async with self._session.begin():
            row = await self._session.get(CaseRow, int(command.case_id))
            if row is None:
                raise AuditValidationError(AuditErrorCode.CASE_NOT_FOUND)
            before_stage = _case_stage(row.stage)
            if command.stage not in _next_stages(before_stage):
                raise AuditValidationError(AuditErrorCode.INVALID_TRANSITION)
            persisted_stage = await self._session.scalar(
                select(CaseRow.stage).where(CaseRow.id == row.id)
            )
            if persisted_stage != before_stage.value:
                raise AuditValidationError(AuditErrorCode.CONCURRENT_CHANGE)
            prior = await self._latest_audit_after(command.case_id)
            if prior is not None:
                validate_case_after_state(prior[1], row, before_stage)
            before = _case_snapshot(row, before_stage, row.updated_at)
            updated_id = await self._session.scalar(
                update(CaseRow)
                .where(CaseRow.id == row.id, CaseRow.stage == before_stage.value)
                .values(stage=command.stage.value, updated_at=command.occurred_at)
                .returning(CaseRow.id)
            )
            if updated_id != row.id:
                raise AuditValidationError(AuditErrorCode.CONCURRENT_CHANGE)
            after = _case_snapshot(row, command.stage, command.occurred_at)
            self._session.add(
                AuditEventRow(
                    entity_type="case",
                    entity_id=str(row.id),
                    action="transition",
                    actor_name=actor,
                    reason=reason,
                    before_json=dump_audit_json(before),
                    after_json=dump_audit_json(after),
                    created_at=command.occurred_at,
                )
            )
        return Case(
            id=CaseId(row.id),
            managed_company_id=ManagedCompanyId(row.managed_company_id),
            program_id=ProgramId(row.program_id),
            assignee_name=row.assignee_name,
            stage=command.stage,
            note=row.note,
            updated_at=command.occurred_at,
        )

    async def audit_events(self, case_id: CaseId) -> tuple[AuditEvent, ...]:
        """Return immutable case audit events oldest-first."""
        async with RepositoryReadScope(self._session):
            if await self._session.get(CaseRow, int(case_id)) is None:
                raise AuditValidationError(AuditErrorCode.CASE_NOT_FOUND)
            rows = (
                await self._session.scalars(
                    select(AuditEventRow)
                    .where(
                        AuditEventRow.entity_id == str(int(case_id)),
                        or_(
                            AuditEventRow.action == "transition",
                            AuditEventRow.entity_type == "case",
                        ),
                    )
                    .order_by(AuditEventRow.id)
                )
            ).all()
            return tuple(audit_event_from_row(row) for row in rows)

    async def _latest_audit_after(
        self,
        case_id: CaseId,
    ) -> tuple[FrozenJsonObject, CaseAuditState] | None:
        row = await self._session.scalar(
            select(AuditEventRow)
            .where(
                AuditEventRow.entity_id == str(int(case_id)),
                or_(
                    AuditEventRow.action == "transition",
                    AuditEventRow.entity_type == "case",
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
            state = parse_case_audit_state(dump_audit_json(event.after_json))
        except ValidationError:
            raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT) from None
        return event.after_json, state


def _case_stage(value: str) -> CaseStage:
    try:
        return CaseStage(value)
    except ValueError:
        raise AuditValidationError(AuditErrorCode.MALFORMED_CASE_STAGE) from None


def _next_stages(stage: CaseStage) -> frozenset[CaseStage]:
    next_stages: frozenset[CaseStage]
    match stage:
        case CaseStage.RECOMMENDED:
            next_stages = frozenset({CaseStage.CONTACTED, CaseStage.CLOSED})
        case CaseStage.CONTACTED:
            next_stages = frozenset({CaseStage.CONSULTED, CaseStage.CLOSED})
        case CaseStage.CONSULTED:
            next_stages = frozenset({CaseStage.APPLYING, CaseStage.CLOSED})
        case CaseStage.APPLYING:
            next_stages = frozenset({CaseStage.SUBMITTED, CaseStage.CLOSED})
        case CaseStage.SUBMITTED:
            next_stages = frozenset({CaseStage.SELECTED, CaseStage.NOT_SELECTED, CaseStage.CLOSED})
        case CaseStage.SELECTED | CaseStage.NOT_SELECTED:
            next_stages = frozenset({CaseStage.CLOSED})
        case CaseStage.CLOSED:
            next_stages = frozenset()
        case _:
            assert_never(stage)
    return next_stages


def _case_snapshot(
    row: CaseRow,
    stage: CaseStage,
    updated_at: datetime,
) -> FrozenJsonObject:
    return freeze_json_object(
        {
            "schema_version": 1,
            "entity_id": row.id,
            "stage": stage.value,
            "assignee_name": row.assignee_name,
            "note": row.note,
            "updated_at": aware_utc(updated_at).isoformat(),
        }
    )
