"""Typed application resources for institution request handlers."""

from dataclasses import dataclass
from weakref import WeakKeyDictionary

from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette

from grantcompass.clock import Clock
from grantcompass.config import Settings


@dataclass(frozen=True, slots=True)
class WebRuntime:
    """Typed resources shared by institution request handlers."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    templates: Jinja2Templates
    clock: Clock


_RUNTIME_NOT_REGISTERED = "web_runtime_not_registered"


@dataclass(slots=True)
class _RuntimeRegistry:
    runtimes: WeakKeyDictionary[Starlette, WebRuntime]
    active: WebRuntime | None = None


_REGISTRY = _RuntimeRegistry(WeakKeyDictionary())


def register_runtime(app: Starlette, runtime: WebRuntime) -> None:
    """Associate typed resources with one application instance."""
    _REGISTRY.runtimes[app] = runtime
    _REGISTRY.active = runtime


def get_runtime(app: Starlette) -> WebRuntime:
    """Return the typed resources associated with one application."""
    return _REGISTRY.runtimes[app]


def active_runtime() -> WebRuntime:
    """Return the single institution application's active runtime."""
    if _REGISTRY.active is None:
        raise RuntimeError(_RUNTIME_NOT_REGISTERED)
    return _REGISTRY.active


def remove_runtime(app: Starlette) -> WebRuntime | None:
    """Remove and return an application's typed resources."""
    runtime = _REGISTRY.runtimes.pop(app, None)
    if runtime is _REGISTRY.active:
        _REGISTRY.active = None
    return runtime


__all__ = [
    "WebRuntime",
    "active_runtime",
    "get_runtime",
    "register_runtime",
    "remove_runtime",
]
