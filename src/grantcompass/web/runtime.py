"""Typed application resources for institution request handlers."""

from dataclasses import dataclass
from typing import cast
from weakref import WeakKeyDictionary

from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.requests import Request

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


@dataclass(slots=True)
class _RuntimeRegistry:
    runtimes: WeakKeyDictionary[Starlette, WebRuntime]


_REGISTRY = _RuntimeRegistry(WeakKeyDictionary())


def register_runtime(app: Starlette, runtime: WebRuntime) -> None:
    """Associate typed resources with one application instance."""
    _REGISTRY.runtimes[app] = runtime


def get_runtime(app: Starlette) -> WebRuntime:
    """Return the typed resources associated with one application."""
    return _REGISTRY.runtimes[app]


def runtime_for(request: Request) -> WebRuntime:
    """Return resources bound to the application handling this request."""
    return get_runtime(cast("Starlette", request.app))


def remove_runtime(app: Starlette) -> WebRuntime | None:
    """Remove and return an application's typed resources."""
    return _REGISTRY.runtimes.pop(app, None)


__all__ = [
    "WebRuntime",
    "get_runtime",
    "register_runtime",
    "remove_runtime",
    "runtime_for",
]
