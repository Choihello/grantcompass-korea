"""Current official-source freshness queries."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.enums import FreshnessStatus, SourceName
from grantcompass.storage.table_programs import SourceRunRow

OFFICIAL_SOURCES = (SourceName.KSTARTUP, SourceName.BIZINFO)


@dataclass(frozen=True, slots=True)
class FreshnessRecord:
    """One source's latest run and last successful collection time."""

    source: SourceName
    status: FreshnessStatus
    observed_at: datetime | None
    last_successful_at: datetime | None
    error_code: str | None


async def load_source_freshness(session: AsyncSession) -> tuple[FreshnessRecord, ...]:
    """Load both official sources in stable public order."""
    return tuple([await load_one_source_freshness(session, source) for source in OFFICIAL_SOURCES])


async def load_one_source_freshness(
    session: AsyncSession,
    source: SourceName,
) -> FreshnessRecord:
    """Load one latest run plus its independently retained last success."""
    latest = await session.scalar(
        select(SourceRunRow)
        .where(SourceRunRow.source == source.value)
        .order_by(SourceRunRow.id.desc())
        .limit(1)
    )
    success = await session.scalar(
        select(SourceRunRow)
        .where(SourceRunRow.source == source.value, SourceRunRow.status == "succeeded")
        .order_by(SourceRunRow.id.desc())
        .limit(1)
    )
    observed_at = None if latest is None else _as_utc(latest.finished_at or latest.started_at)
    last_successful_at = (
        None if success is None else _as_utc(success.finished_at or success.started_at)
    )
    if latest is None:
        return FreshnessRecord(
            source,
            FreshnessStatus.STALE,
            None,
            last_successful_at,
            "no_source_run",
        )
    if latest.status == "succeeded":
        return FreshnessRecord(
            source,
            FreshnessStatus.FRESH,
            observed_at,
            last_successful_at,
            None,
        )
    error_code = latest.error_code or (
        "source_run_failed" if latest.status == "failed" else "malformed_source_run_status"
    )
    return FreshnessRecord(
        source,
        FreshnessStatus.STALE,
        observed_at,
        last_successful_at,
        error_code,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
