"""Public serialized values used across GrantCompass domain boundaries."""

from enum import StrEnum, unique


@unique
class SourceName(StrEnum):
    """Supported announcement sources."""

    KSTARTUP = "kstartup"
    BIZINFO = "bizinfo"
    MANUAL = "manual"


@unique
class ConditionStatus(StrEnum):
    """Evaluation state for one eligibility condition."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@unique
class FinalStatus(StrEnum):
    """Aggregated eligibility decision."""

    ELIGIBLE = "eligible"
    CONDITIONAL = "conditional"
    INELIGIBLE = "ineligible"
    NEEDS_REVIEW = "needs_review"


@unique
class ReviewStatus(StrEnum):
    """Human-review progress for a decision."""

    AUTOMATIC = "automatic"
    REVIEW_REQUIRED = "review_required"
    REVIEWED = "reviewed"


@unique
class FreshnessStatus(StrEnum):
    """Freshness state of collected source data."""

    FRESH = "fresh"
    STALE = "stale"


@unique
class CaseStage(StrEnum):
    """Lifecycle stage of a recommended support case."""

    RECOMMENDED = "recommended"
    CONTACTED = "contacted"
    CONSULTED = "consulted"
    APPLYING = "applying"
    SUBMITTED = "submitted"
    SELECTED = "selected"
    NOT_SELECTED = "not_selected"
    CLOSED = "closed"


@unique
class RuleKind(StrEnum):
    """Supported kinds of eligibility rule."""

    BUSINESS_AGE_MONTHS = "business_age_months"
    REGION = "region"
    REPRESENTATIVE_AGE = "representative_age"
    INDUSTRY = "industry"
    PERFORMANCE = "performance"
    DUPLICATE_BENEFIT = "duplicate_benefit"
    NATURAL_LANGUAGE = "natural_language"
