"""Finite command-line boundary errors."""

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Literal, override


@unique
class CliErrorCode(StrEnum):
    """Stable credential-safe error codes emitted by the CLI."""

    AMBIGUOUS_PROFILE_NAME = "ambiguous_profile_name"
    DUPLICATE_PROFILE_NAME = "duplicate_profile_name"
    FILESYSTEM_ERROR = "filesystem_error"
    INVALID_CLOCK = "invalid_clock"
    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_DATABASE_URL = "invalid_database_url"
    INVALID_PROFILE_INPUT = "invalid_profile_input"
    MALFORMED_PROFILE_RECORD = "malformed_profile_record"
    MISSING_EVIDENCE_ID = "missing_evidence_id"
    MISSING_PROFILE_ID = "missing_profile_id"
    OUTPUT_EXISTS = "output_exists"
    OUTPUT_PARENT_MISSING = "output_parent_missing"
    PROFILE_NOT_FOUND = "profile_not_found"
    REPORT_CLEANUP_FAILED = "report_cleanup_failed"
    REPORT_WRITE_FAILED = "report_write_failed"
    STORAGE_ERROR = "storage_error"
    UNSUPPORTED_SYNC_SOURCE = "unsupported_sync_source"


type CliExitCode = Literal[3, 4]


@dataclass(frozen=True, slots=True)
class CliError(Exception):
    """Carry a stable machine code and documented process exit code."""

    code: CliErrorCode
    exit_code: CliExitCode

    @override
    def __str__(self) -> str:
        """Return only the credential-safe machine code."""
        return self.code.value
