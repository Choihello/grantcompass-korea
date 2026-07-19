"""Finite translation of reused query and assessment boundary errors."""

from typing import assert_never

from grantcompass.cli.errors import CliErrorCode
from grantcompass.domain.reverse import CompanyInputErrorCode
from grantcompass.rules.deterministic import AssessmentInputErrorCode


def profile_input_error(code: CliErrorCode) -> CompanyInputErrorCode:
    """Translate all CLI profile failures into reverse-matching input failures."""
    match code:
        case CliErrorCode.PROFILE_NOT_FOUND:
            return CompanyInputErrorCode.PROFILE_NOT_FOUND
        case (
            CliErrorCode.AMBIGUOUS_PROFILE_NAME
            | CliErrorCode.DUPLICATE_PROFILE_NAME
            | CliErrorCode.FILESYSTEM_ERROR
            | CliErrorCode.INVALID_CLOCK
            | CliErrorCode.INVALID_CONFIGURATION
            | CliErrorCode.INVALID_DATABASE_URL
            | CliErrorCode.INVALID_PROFILE_INPUT
            | CliErrorCode.MALFORMED_PROFILE_RECORD
            | CliErrorCode.MISSING_EVIDENCE_ID
            | CliErrorCode.MISSING_PROFILE_ID
            | CliErrorCode.OUTPUT_EXISTS
            | CliErrorCode.OUTPUT_PARENT_MISSING
            | CliErrorCode.REPORT_CLEANUP_FAILED
            | CliErrorCode.REPORT_WRITE_FAILED
            | CliErrorCode.STORAGE_ERROR
            | CliErrorCode.UNSUPPORTED_SYNC_SOURCE
        ):
            return CompanyInputErrorCode.MALFORMED_PROFILE
        case _:
            assert_never(code)


def assessment_input_error(code: AssessmentInputErrorCode) -> CompanyInputErrorCode:
    """Translate every deterministic-engine input failure without raw leakage."""
    match code:
        case "mixed_rule_versions":
            return CompanyInputErrorCode.MIXED_RULE_VERSIONS
        case (
            "empty_rules"
            | "missing_profile_id"
            | "missing_rule_id"
            | "missing_program_id"
            | "missing_evidence_id"
            | "mixed_programs"
            | "naive_assessed_at"
        ):
            return CompanyInputErrorCode.ASSESSMENT_INPUT
        case _:
            assert_never(code)


def program_input_error(errors: tuple[str, ...]) -> CompanyInputErrorCode:
    """Translate query-layer program analysis failures into finite categories."""
    if "missing_rules" in errors:
        return CompanyInputErrorCode.MISSING_RULES
    if "missing_evidence" in errors:
        return CompanyInputErrorCode.MISSING_EVIDENCE
    return CompanyInputErrorCode.MALFORMED_RULE
