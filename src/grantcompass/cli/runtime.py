"""Injectable CLI runtime dependencies and production factories."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, assert_never

import httpx2
from pydantic import SecretStr, ValidationError

from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.clock import Clock, SystemClock
from grantcompass.config import Settings
from grantcompass.domain.enums import SourceName
from grantcompass.http import create_async_client
from grantcompass.sources.base import SourceAdapter
from grantcompass.sources.bizinfo import BizinfoAdapter
from grantcompass.sources.kstartup import KStartupAdapter


class SourceAdapterFactory(Protocol):
    """Construct one official adapter around a caller-owned HTTP client."""

    def create(
        self,
        source: SourceName,
        client: httpx2.AsyncClient,
        service_key: SecretStr,
    ) -> SourceAdapter:
        """Return the pinned adapter for one configured source."""
        ...


class OfficialAdapterFactory:
    """Construct only the two configured official source adapters."""

    def create(
        self,
        source: SourceName,
        client: httpx2.AsyncClient,
        service_key: SecretStr,
    ) -> SourceAdapter:
        """Return an adapter whose credential destination is pinned."""
        match source:
            case SourceName.KSTARTUP:
                return KStartupAdapter(client, service_key)
            case SourceName.BIZINFO:
                return BizinfoAdapter(client, service_key)
            case SourceName.MANUAL:
                raise CliError(CliErrorCode.UNSUPPORTED_SYNC_SOURCE, 4)
            case _:
                assert_never(source)


@dataclass(frozen=True, slots=True)
class CliDependencies:
    """Own injectable settings, time, adapter, and HTTP construction seams."""

    settings_provider: Callable[[], Settings]
    clock: Clock
    adapter_factory: SourceAdapterFactory
    client_factory: Callable[[], httpx2.AsyncClient]


def default_dependencies() -> CliDependencies:
    """Return lazy production dependencies without reading settings at import."""
    return CliDependencies(
        settings_provider=_load_settings,
        clock=SystemClock(),
        adapter_factory=OfficialAdapterFactory(),
        client_factory=create_async_client,
    )


def _load_settings() -> Settings:
    return Settings()


def load_settings(dependencies: CliDependencies) -> Settings:
    """Load settings through the finite CLI configuration boundary."""
    try:
        return dependencies.settings_provider()
    except ValidationError:
        raise CliError(CliErrorCode.INVALID_CONFIGURATION, 4) from None
