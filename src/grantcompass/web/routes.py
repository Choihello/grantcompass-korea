"""Server-rendered institution routes and attributed mutation boundaries."""

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from pydantic import ValidationError
from sqlalchemy.exc import NoResultFound

from grantcompass.domain.cases import (
    AuditValidationError,
    CaseId,
    CaseTransition,
)
from grantcompass.domain.enums import CaseStage
from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.domain.reviews import AssessmentReviewCommand
from grantcompass.matching.reverse import ReverseMatchingService
from grantcompass.reports.pdf import ConsultationReportService
from grantcompass.storage.audit_json import validate_attribution
from grantcompass.storage.repositories import (
    AssessmentRepository,
    CaseRepository,
)
from grantcompass.storage.table_eligibility import AssessmentRow
from grantcompass.web.company_queries import list_companies
from grantcompass.web.failures import FailureHealth, load_failure_snapshot
from grantcompass.web.forms import (
    AttributionForm,
    TransitionForm,
    parse_review_request,
)
from grantcompass.web.manual_routes import manual_router
from grantcompass.web.mutations import (
    case_for_assessment,
    review_overrides,
)
from grantcompass.web.queries import get_program_detail, list_programs
from grantcompass.web.runtime import active_runtime

router = APIRouter(default_response_class=HTMLResponse)
router.include_router(manual_router)


@router.get("/")
async def index() -> RedirectResponse:
    """Redirect the workspace root to the program review ledger."""
    return RedirectResponse("/programs", status_code=303)


@router.get("/programs")
async def programs(request: Request) -> Response:
    """Render the source-freshness program ledger."""
    runtime = active_runtime()
    async with runtime.session_factory() as session:
        entries = await list_programs(session, runtime.clock.now())
    return runtime.templates.TemplateResponse(
        request=request,
        name="programs.html",
        context={"programs": entries},
    )


@router.get("/programs/failure-scenario")
async def failure_scenario(request: Request) -> Response:
    """Render every supported failure detected from persisted domain state."""
    runtime = active_runtime()
    async with runtime.session_factory() as session:
        snapshot = await load_failure_snapshot(session)
    return runtime.templates.TemplateResponse(
        request=request,
        name="failure_scenario.html",
        context={"snapshot": snapshot},
    )


@router.get("/health/failures", response_class=JSONResponse)
async def failure_health() -> FailureHealth:
    """Return stable visible failure IDs and the hidden-failure audit list."""
    runtime = active_runtime()
    async with runtime.session_factory() as session:
        snapshot = await load_failure_snapshot(session)
    return FailureHealth(
        visible_failure_ids=snapshot.visible_failure_ids,
        hidden_failures=snapshot.hidden_failures,
    )


@router.get("/programs/{program_id}")
async def program_detail(request: Request, program_id: int) -> Response:
    """Render official sources, conditions, locations, and reverse matches."""
    runtime = active_runtime()
    async with runtime.session_factory() as session:
        detail = await get_program_detail(session, program_id, runtime.settings.timezone)
    if detail is None:
        return PlainTextResponse("program_not_found", status_code=404)
    return runtime.templates.TemplateResponse(
        request=request,
        name="program_detail.html",
        context={"program": detail},
    )


@router.post("/programs/{program_id}/reverse-match")
async def reverse_match(
    program_id: int,
    form: Annotated[AttributionForm, Form()],
) -> Response:
    """Run one attributed reverse-match invocation through the domain service."""
    runtime = active_runtime()
    assessed_at = runtime.clock.now().astimezone(UTC)
    try:
        _ = validate_attribution(form.actor, form.reason, assessed_at)
        async with runtime.session_factory() as session:
            _ = await ReverseMatchingService(session).reverse_match(
                ProgramId(program_id),
                assessed_at,
            )
    except AuditValidationError as error:
        return PlainTextResponse(error.code.value, status_code=422)
    return RedirectResponse(f"/programs/{program_id}", status_code=303)


@router.post("/assessments/{assessment_id}/review")
async def review_assessment(
    request: Request,
    assessment_id: int,
) -> Response:
    """Apply one attributed assessment review through its repository."""
    runtime = active_runtime()
    try:
        form = await parse_review_request(request)
        async with runtime.session_factory() as read_session:
            assessment = await read_session.get(AssessmentRow, assessment_id)
            if assessment is None:
                return PlainTextResponse("assessment_not_found", status_code=404)
            overrides = await review_overrides(read_session, assessment, form.conditions)
            program_id = assessment.program_id
            profile_id = assessment.profile_id
        async with runtime.session_factory() as mutation_session:
            _ = await AssessmentRepository(mutation_session).review(
                AssessmentReviewCommand(
                    AssessmentId(assessment_id),
                    overrides,
                    form.actor,
                    form.reason,
                    runtime.clock.now().astimezone(UTC),
                    form.expected_review_revision,
                )
            )
        async with runtime.session_factory() as read_session:
            case_id = await case_for_assessment(read_session, program_id, profile_id)
    except (TypeError, ValidationError, ValueError):
        return PlainTextResponse("invalid_review_status", status_code=422)
    except AuditValidationError as error:
        status_code = 409 if error.code.value == "concurrent_change" else 422
        return PlainTextResponse(error.code.value, status_code=status_code)
    location = f"/cases/{case_id}" if case_id is not None else f"/programs/{program_id}"
    return RedirectResponse(location, status_code=303)


@router.get("/companies")
async def companies(request: Request) -> Response:
    """Render the complete managed-company ledger."""
    runtime = active_runtime()
    async with runtime.session_factory() as session:
        entries = await list_companies(session)
    return runtime.templates.TemplateResponse(
        request=request,
        name="companies.html",
        context={"companies": entries},
    )


@router.get("/cases/{case_id}")
async def case_detail(request: Request, case_id: int) -> Response:
    """Render one consultation dossier with immutable audit history."""
    runtime = active_runtime()
    try:
        async with runtime.session_factory() as session:
            report = await ConsultationReportService(
                session,
                runtime.clock,
                runtime.settings.timezone,
            ).load(case_id)
    except NoResultFound:
        return PlainTextResponse("case_not_found", status_code=404)
    return runtime.templates.TemplateResponse(
        request=request,
        name="case_detail.html",
        context={"report": report, "stages": tuple(CaseStage)},
    )


@router.post("/cases/{case_id}/transition")
async def transition_case(
    case_id: int,
    form: Annotated[TransitionForm, Form()],
) -> Response:
    """Move a support case through the authoritative transition graph."""
    runtime = active_runtime()
    try:
        stage = CaseStage(form.stage)
    except ValueError:
        return PlainTextResponse("malformed_case_stage", status_code=422)
    try:
        async with runtime.session_factory() as session:
            _ = await CaseRepository(session).transition(
                CaseTransition(
                    CaseId(case_id),
                    stage,
                    form.actor,
                    form.reason,
                    runtime.clock.now().astimezone(UTC),
                )
            )
    except AuditValidationError as error:
        is_conflict = error.code.value in {"concurrent_change", "invalid_transition"}
        status_code = 409 if is_conflict else 422
        return PlainTextResponse(error.code.value, status_code=status_code)
    return RedirectResponse(f"/cases/{case_id}", status_code=303)


@router.get("/cases/{case_id}/report.pdf")
async def consultation_pdf(case_id: int) -> Response:
    """Render the case dossier as a searchable inline PDF."""
    runtime = active_runtime()
    async with runtime.session_factory() as session:
        payload = await ConsultationReportService(
            session,
            runtime.clock,
            runtime.settings.timezone,
        ).render_consultation_pdf(case_id)
    return Response(
        payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="consultation-{case_id}.pdf"'},
    )
