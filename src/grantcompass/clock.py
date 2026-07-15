"""Injectable UTC clock boundary."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Provide storage-ready current instants."""

    def now(self) -> datetime:
        """Return a timezone-aware current instant."""
        ...


class SystemClock:
    """Read the operating system clock in UTC."""

    def now(self) -> datetime:
        """Return the current UTC instant."""
        return datetime.now(tz=UTC)
