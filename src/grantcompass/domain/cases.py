"""Managed-company, case, and audit domain outcomes."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import NewType, override

from grantcompass.domain.eligibility import ApplicantProfileId
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.json_types import FrozenJsonObject
from grantcompass.domain.programs import ProgramId
from grantcompass.domain.reviews import AssessmentReviewCommand

ManagedCompanyId = NewType("ManagedCompanyId", int)
CaseId = NewType("CaseId", int)
AuditEventId = NewType("AuditEventId", int)


@unique
class AuditErrorCode(StrEnum):
    """Finite validation and concurrency failures for institutional writes."""

    ACTOR_REQUIRED = "actor_required"
    ACTOR_TOO_LONG = "actor_too_long"
    REASON_REQUIRED = "reason_required"
    REASON_TOO_LONG = "reason_too_long"
    NAIVE_TIME = "naive_time"
    NON_UTC_TIME = "non_utc_time"
    CASE_NOT_FOUND = "case_not_found"
    ASSESSMENT_NOT_FOUND = "assessment_not_found"
    INVALID_TRANSITION = "invalid_transition"
    MALFORMED_CASE_STAGE = "malformed_case_stage"
    MALFORMED_ASSESSMENT = "malformed_assessment"
    MALFORMED_AUDIT = "malformed_audit"
    INVALID_OVERRIDE_IDENTITY = "invalid_override_identity"
    DUPLICATE_OVERRIDE = "duplicate_override"
    UNKNOWN_RULE_ASSESSMENT = "unknown_rule_assessment"
    FOREIGN_RULE_ASSESSMENT = "foreign_rule_assessment"
    CONCURRENT_CHANGE = "concurrent_change"


@dataclass(frozen=True, slots=True)
class AuditValidationError(Exception):
    """Carry one stable institutional write failure code."""

    code: AuditErrorCode

    @override
    def __str__(self) -> str:
        """Return the stable machine-readable failure code."""
        return self.code.value


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
class CaseTransition:
    """One attributed request to move a support case forward."""

    case_id: CaseId
    stage: CaseStage
    actor: str
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable attribution record for a state-changing action."""

    id: AuditEventId
    entity_type: str
    entity_id: str
    action: str
    actor_name: str
    reason: str
    before_json: FrozenJsonObject | None
    after_json: FrozenJsonObject | None
    created_at: datetime


__all__ = [
    "AssessmentReviewCommand",
    "AuditErrorCode",
    "AuditEvent",
    "AuditEventId",
    "AuditValidationError",
    "Case",
    "CaseId",
    "CaseTransition",
    "ManagedCompany",
    "ManagedCompanyId",
]
