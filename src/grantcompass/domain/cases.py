"""Managed-company, case, and audit domain outcomes."""

from dataclasses import dataclass
from datetime import datetime
from typing import NewType

from grantcompass.domain.eligibility import ApplicantProfileId
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.programs import ProgramId

ManagedCompanyId = NewType("ManagedCompanyId", int)
CaseId = NewType("CaseId", int)
AuditEventId = NewType("AuditEventId", int)


@dataclass(frozen=True, slots=True)
class ManagedCompany:
    """Immutable institutional ownership link for an applicant profile."""

    id: ManagedCompanyId
    profile_id: ApplicantProfileId
    owner_name: str
    active: bool


@dataclass(frozen=True, slots=True)
class Case:
    """Immutable support-case snapshot."""

    id: CaseId
    managed_company_id: ManagedCompanyId
    program_id: ProgramId
    assignee_name: str | None
    stage: CaseStage
    note: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable attribution record for a state-changing action."""

    id: AuditEventId
    entity_type: str
    entity_id: str
    action: str
    actor_name: str
    reason: str
    before_json: str | None
    after_json: str | None
    created_at: datetime
