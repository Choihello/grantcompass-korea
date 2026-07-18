from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final

import httpx2
from pydantic import SecretStr

from grantcompass.cli.runtime import CliDependencies
from grantcompass.config import Settings
from grantcompass.domain.enums import SourceName
from grantcompass.http import create_async_client
from grantcompass.sources.base import SourceAdapter, SourcePage, SourceTransportError

FIXED_NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    instant: datetime = FIXED_NOW

    def now(self) -> datetime:
        return self.instant


@final
class SuccessfulAdapter:
    def __init__(self, name: SourceName) -> None:
        self.name: SourceName = name

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        del page_size
        return SourcePage(items=(), page=page, has_next=False, response_hash=f"{self.name}-hash")


@final
class FailingAdapter:
    def __init__(self, name: SourceName) -> None:
        self.name: SourceName = name

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        del page, page_size
        raise SourceTransportError(code="synthetic_upstream_stale", message="synthetic stale")


@dataclass(frozen=True, slots=True)
class StaticAdapterFactory:
    adapters: tuple[SourceAdapter, ...]

    def create(
        self,
        source: SourceName,
        client: httpx2.AsyncClient,
        service_key: SecretStr,
    ) -> SourceAdapter:
        del client, service_key
        for adapter in self.adapters:
            if adapter.name is source:
                return adapter
        raise AssertionError(source)


def make_dependencies(
    database_url: str,
    adapters: tuple[SourceAdapter, ...] = (),
    *,
    kstartup_key: str | None = None,
    bizinfo_key: str | None = None,
    client_factory: Callable[[], httpx2.AsyncClient] | None = None,
) -> CliDependencies:
    settings = Settings(
        database_url=database_url,
        kstartup_service_key=None if kstartup_key is None else SecretStr(kstartup_key),
        bizinfo_service_key=None if bizinfo_key is None else SecretStr(bizinfo_key),
    )

    def settings_provider() -> Settings:
        return settings

    return CliDependencies(
        settings_provider=settings_provider,
        clock=FixedClock(),
        adapter_factory=StaticAdapterFactory(adapters),
        client_factory=client_factory or create_async_client,
    )
