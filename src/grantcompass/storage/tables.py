"""Complete SQLAlchemy metadata for the GrantCompass SQLite schema."""

from grantcompass.storage.table_base import Base
from grantcompass.storage.table_cases import AuditEventRow, CaseRow, ManagedCompanyRow
from grantcompass.storage.table_documents import (
    DocumentBlockRow,
    DocumentRow,
    EvidenceRow,
    rule_evidence,
)
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    EligibilityRuleRow,
    RuleAssessmentRow,
)
from grantcompass.storage.table_notice_analysis import (
    AssessmentReviewNoteRow,
    ChangeImpactRow,
    ChangeSetRow,
    CurrentNoticeVersionRow,
    FieldConflictRow,
    MergeCandidateRow,
)
from grantcompass.storage.table_programs import (
    AttachmentRow,
    NoticeVersionRow,
    ProgramRow,
    SourceRunRow,
)

__all__ = [
    "ApplicantProfileRow",
    "AssessmentReviewNoteRow",
    "AssessmentRow",
    "AttachmentRow",
    "AuditEventRow",
    "Base",
    "CaseRow",
    "ChangeImpactRow",
    "ChangeSetRow",
    "CurrentNoticeVersionRow",
    "DocumentBlockRow",
    "DocumentRow",
    "EligibilityRuleRow",
    "EvidenceRow",
    "FieldConflictRow",
    "ManagedCompanyRow",
    "MergeCandidateRow",
    "NoticeVersionRow",
    "ProgramRow",
    "RuleAssessmentRow",
    "SourceRunRow",
    "rule_evidence",
]
