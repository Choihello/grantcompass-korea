"""Typed contracts shared by official source adapters."""

from dataclasses import dataclass
from typing import ClassVar, Protocol, override

from pydantic import BaseModel, ConfigDict, Field

from grantcompass.domain.enums import FreshnessStatus, SourceName
from grantcompass.domain.programs import RawNotice


class SourcePage(BaseModel):
    """Validated immutable page returned by one source adapter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    items: tuple[RawNotice, ...]
    page: int = Field(ge=1)
    has_next: bool
    response_hash: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """Immutable source-level outcome visible to callers and health surfaces."""

    source: SourceName
    stored: int
    unchanged: int
    failed: int
    freshness: FreshnessStatus
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class SourceContractError(Exception):
    """Stable failure raised when a source response violates its declared contract."""

    code: str
    message: str

    @override
    def __str__(self) -> str:
        """Return the adapter-safe diagnostic without including secrets."""
        return self.message


@dataclass(frozen=True, slots=True)
class SourceTransportError(Exception):
    """Stable failure raised when transport cannot obtain a source response."""

    code: str
    message: str

    @override
    def __str__(self) -> str:
        """Return the adapter-safe diagnostic without including secrets."""
        return self.message


class SourceAdapter(Protocol):
    """Fetch validated notice pages for one official source."""

    name: SourceName

    async def fetch_page(self, page: int, page_size: int) -> SourcePage:
        """Return one page of canonical source notices."""
        ...
