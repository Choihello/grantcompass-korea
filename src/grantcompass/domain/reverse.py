"""Immutable institutional reverse-matching results and finite errors."""

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import override

from grantcompass.domain.cases import ManagedCompanyId
from grantcompass.domain.eligibility import ApplicantProfileId, AssessmentResult
from grantcompass.domain.enums import SourceName
from grantcompass.domain.ids import NoticeVersionId


@unique
class ReverseMatchingErrorCode(StrEnum):
    """Finite request-level reverse-matching failures."""

    UNKNOWN_PROGRAM = "unknown_program"
    NAIVE_ASSESSED_AT = "naive_assessed_at"
    NON_UTC_ASSESSED_AT = "non_utc_assessed_at"


@dataclass(frozen=True, slots=True)
class ReverseMatchingError(Exception):
    """Carry one stable reverse-matching request failure."""

    code: ReverseMatchingErrorCode

    @override
    def __str__(self) -> str:
        """Return the stable machine-readable failure code."""
        return self.code.value


@unique
class CompanyInputErrorCode(StrEnum):
    """Finite stored-input failures visible for one managed company."""

    PROFILE_NOT_FOUND = "profile_not_found"
    MALFORMED_PROFILE = "malformed_profile"
    MISSING_RULES = "missing_rules"
    MISSING_EVIDENCE = "missing_evidence"
    MALFORMED_RULE = "malformed_rule"
    MISSING_CURRENT_NOTICE = "missing_current_notice"
    MALFORMED_NOTICE_SOURCE = "malformed_notice_source"
    MIXED_RULE_VERSIONS = "mixed_rule_versions"
    ASSESSMENT_INPUT = "assessment_input"


@dataclass(frozen=True, slots=True)
class CompanyInputError:
    """Visible finite reason why one company was not assessed."""

    code: CompanyInputErrorCode


@dataclass(frozen=True, slots=True)
class NoticeContentIdentity:
    """One current official source content identity."""

    source: SourceName
    notice_version_id: NoticeVersionId
    content_hash: str


@dataclass(frozen=True, slots=True)
class CompanyMatch:
    """One managed company returned exactly once from reverse matching."""

    managed_company_id: ManagedCompanyId
    profile_id: ApplicantProfileId
    profile_name: str | None
    owner_name: str
    active: bool
    assessment: AssessmentResult | None
    content_identities: tuple[NoticeContentIdentity, ...]
    latest_content_hash: str | None
    input_error: CompanyInputError | None = None
