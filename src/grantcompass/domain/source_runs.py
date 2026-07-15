"""Source collection run identity and terminal outcomes."""

from dataclasses import dataclass
from datetime import datetime
from typing import NewType

SourceRunId = NewType("SourceRunId", int)


@dataclass(frozen=True, slots=True)
class SourceRunSuccess:
    """Successful source-run values persisted as one state transition."""

    finished_at: datetime
    item_count: int
    response_hash: str | None


@dataclass(frozen=True, slots=True)
class SourceRunFailure:
    """Failed source-run values persisted without erasing prior source data."""

    finished_at: datetime
    item_count: int
    response_hash: str | None
    error_code: str
    error_message: str
