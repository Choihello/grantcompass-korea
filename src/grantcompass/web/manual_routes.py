"""Institution-owned notice registration routes."""

from datetime import UTC
from pathlib import PurePath

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import ValidationError

from grantcompass.documents.errors import DocumentIngestError
from grantcompass.domain.cases import AuditValidationError
from grantcompass.storage.repositories import ManualNoticeCommand, ProgramRepository
from grantcompass.web.forms import parse_manual_request
from grantcompass.web.mutations import manual_raw_notice
from grantcompass.web.runtime import active_runtime

manual_router = APIRouter(default_response_class=HTMLResponse)
_SUPPORTED_DOCUMENTS = frozenset({".pdf", ".hwpx"})


@manual_router.get("/programs/manual")
async def manual_program_form(request: Request) -> Response:
    """Render the institution-owned notice registration desk."""
    return active_runtime().templates.TemplateResponse(
        request=request,
        name="manual_program_form.html",
        context={},
    )


@manual_router.post("/programs/manual")
async def create_manual_program(request: Request) -> Response:
    """Register and parse one attributed institution-owned notice."""
    runtime = active_runtime()
    try:
        form, document = await parse_manual_request(request)
    except (TypeError, ValidationError, ValueError):
        return PlainTextResponse("invalid_manual_program", status_code=422)
    filename = document.filename if document is not None else None
    if (
        document is not None
        and filename is not None
        and PurePath(filename).suffix.casefold() not in _SUPPORTED_DOCUMENTS
    ):
        await document.close()
        return PlainTextResponse("invalid_attachment_type", status_code=422)
    content = await document.read() if document is not None else None
    if document is not None:
        await document.close()
    now = runtime.clock.now().astimezone(UTC)
    raw = manual_raw_notice(form, filename, now.isoformat())
    try:
        async with runtime.session_factory() as session:
            result = await ProgramRepository(session).create_manual_notice(
                ManualNoticeCommand(raw, now, form.actor, form.reason, content, filename)
            )
    except AuditValidationError as error:
        return PlainTextResponse(error.code.value, status_code=422)
    except DocumentIngestError as error:
        return PlainTextResponse(error.code, status_code=422)
    return RedirectResponse(f"/programs/{int(result.program_id)}", status_code=303)


__all__ = ["manual_router"]
