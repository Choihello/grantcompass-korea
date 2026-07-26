"""FastAPI application factory for the institution workspace."""

from pathlib import Path
from secrets import token_bytes

from fastapi import FastAPI, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from grantcompass.clock import Clock, SystemClock
from grantcompass.config import Settings
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.web.request_limits import ManualRequestLimitMiddleware
from grantcompass.web.routes import router
from grantcompass.web.runtime import (
    WebRuntime,
    get_runtime,
    register_runtime,
    remove_runtime,
)
from grantcompass.web.security import SecurityBoundaryMiddleware

_TEMPLATE_DIRECTORY = Path(__file__).with_name("templates")


async def _empty_favicon() -> Response:
    return Response(status_code=204)


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    """Create one institution workspace bound to validated settings."""
    resolved = settings or Settings()
    engine = create_engine(resolved.database_url)
    app = FastAPI(title="GrantCompass 기관 검토대장", docs_url=None, redoc_url=None)
    signing_secret = (
        resolved.csrf_signing_secret.get_secret_value().encode()
        if resolved.csrf_signing_secret is not None
        else token_bytes(32)
    )
    app.add_middleware(
        SecurityBoundaryMiddleware,
        allowed_origins=resolved.allowed_origins,
        signing_secret=signing_secret,
    )
    app.add_middleware(ManualRequestLimitMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(resolved.allowed_hosts))
    register_runtime(
        app,
        WebRuntime(
            settings=resolved,
            engine=engine,
            session_factory=create_session_factory(engine),
            templates=Jinja2Templates(directory=_TEMPLATE_DIRECTORY),
            clock=clock or SystemClock(),
        ),
    )
    app.add_api_route(
        "/favicon.ico",
        _empty_favicon,
        methods=["GET"],
        status_code=204,
        include_in_schema=False,
    )
    app.include_router(router)
    return app


async def dispose_app(app: FastAPI) -> None:
    """Dispose the application database engine after embedded use."""
    runtime = remove_runtime(app)
    if runtime is not None:
        await runtime.engine.dispose()


__all__ = ["WebRuntime", "create_app", "dispose_app", "get_runtime"]
