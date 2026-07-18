"""Bounded official-source synchronization service."""

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import assert_never

import httpx2
from pydantic import SecretStr

from grantcompass.cli.database import create_cli_engine
from grantcompass.cli.freshness import load_one_source_freshness
from grantcompass.cli.runtime import CliDependencies, load_settings
from grantcompass.cli.schemas import SyncOutput, SyncResultOutput
from grantcompass.config import Settings
from grantcompass.domain.enums import FreshnessStatus, SourceName
from grantcompass.sources.base import CollectionResult
from grantcompass.sources.collector import Collector
from grantcompass.storage.db import create_session_factory
from grantcompass.storage.repositories import ProgramRepository


@unique
class SourceSelection(StrEnum):
    """Supported CLI source selectors."""

    KSTARTUP = "kstartup"
    BIZINFO = "bizinfo"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class _CollectionContext:
    dependencies: CliDependencies
    settings: Settings
    client: httpx2.AsyncClient
    repository: ProgramRepository


async def synchronize_sources(
    dependencies: CliDependencies,
    selection: SourceSelection,
) -> SyncOutput:
    """Synchronize selected configured sources with one owned HTTP client."""
    settings = load_settings(dependencies)
    synced_at = dependencies.clock.now()
    sources = _selected_sources(selection)
    engine = create_cli_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            configured = tuple(
                source for source in sources if _service_key(settings, source) is not None
            )
            collected: dict[SourceName, CollectionResult] = {}
            if configured:
                async with dependencies.client_factory() as client:
                    outcomes = await _collect_sources(
                        _CollectionContext(
                            dependencies=dependencies,
                            settings=settings,
                            client=client,
                            repository=ProgramRepository(session),
                        ),
                        configured,
                    )
                    collected = dict(outcomes)
            results: list[SyncResultOutput] = []
            for source in sources:
                freshness = await load_one_source_freshness(session, source)
                outcome = collected.get(source)
                if outcome is None:
                    results.append(
                        SyncResultOutput(
                            source=source,
                            stored=0,
                            unchanged=0,
                            failed=1,
                            freshness=FreshnessStatus.STALE,
                            error_code="missing_service_key",
                            last_successful_at=freshness.last_successful_at,
                        )
                    )
                else:
                    results.append(
                        SyncResultOutput(
                            source=source,
                            stored=outcome.stored,
                            unchanged=outcome.unchanged,
                            failed=outcome.failed,
                            freshness=outcome.freshness,
                            error_code=outcome.error_code,
                            last_successful_at=freshness.last_successful_at,
                        )
                    )
            return SyncOutput(synced_at=synced_at, results=tuple(results))
    finally:
        await engine.dispose()


async def _collect_sources(
    context: _CollectionContext,
    sources: tuple[SourceName, ...],
) -> tuple[tuple[SourceName, CollectionResult], ...]:
    collector = Collector(context.repository, context.dependencies.clock)
    results: list[tuple[SourceName, CollectionResult]] = []
    for source in sources:
        service_key = _service_key(context.settings, source)
        if service_key is None:
            continue
        adapter = context.dependencies.adapter_factory.create(source, context.client, service_key)
        result = await collector.collect(adapter, context.settings.source_page_size)
        results.append((source, result))
    return tuple(results)


def _service_key(settings: Settings, source: SourceName) -> SecretStr | None:
    match source:
        case SourceName.KSTARTUP:
            return _configured_secret(settings.kstartup_service_key)
        case SourceName.BIZINFO:
            return _configured_secret(settings.bizinfo_service_key)
        case SourceName.MANUAL:
            return None
        case _:
            assert_never(source)


def _configured_secret(value: SecretStr | None) -> SecretStr | None:
    if value is None or not value.get_secret_value().strip():
        return None
    return value


def _selected_sources(selection: SourceSelection) -> tuple[SourceName, ...]:
    match selection:
        case SourceSelection.KSTARTUP:
            return (SourceName.KSTARTUP,)
        case SourceSelection.BIZINFO:
            return (SourceName.BIZINFO,)
        case SourceSelection.ALL:
            return (SourceName.KSTARTUP, SourceName.BIZINFO)
        case _:
            assert_never(selection)
