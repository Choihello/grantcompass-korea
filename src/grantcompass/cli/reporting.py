"""Task 10 report reuse and atomic artifact persistence."""

import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.cli.runtime import CliDependencies, load_settings
from grantcompass.cli.schemas import ReportWrittenOutput, SearchOutput
from grantcompass.cli.search import search_programs
from grantcompass.reports.markdown import ReportInput, SourceFreshness, render_markdown_report
from grantcompass.reports.markdown_helpers import escape_markdown


@dataclass(frozen=True, slots=True)
class ReportRequest:
    """Validated presentation values for one requested report artifact."""

    profile_selector: str
    output_path: Path
    force: bool


async def generate_report(
    dependencies: CliDependencies,
    request: ReportRequest,
) -> ReportWrittenOutput:
    """Reuse one search and Task 10 renderer, then write atomically."""
    settings = load_settings(dependencies)
    generated_at = dependencies.clock.now()
    bundle = await search_programs(
        settings.database_url,
        request.profile_selector,
        generated_at,
    )
    report_input = ReportInput(
        profile=bundle.profile,
        matches=bundle.matches,
        roadmaps=bundle.roadmaps,
        evidence=bundle.evidence,
        freshness=tuple(
            SourceFreshness(
                source=item.source,
                status=item.status,
                collected_at=item.observed_at or generated_at,
            )
            for item in bundle.freshness
        ),
        generated_at=generated_at,
    )
    destination = request.output_path.resolve()
    content = render_markdown_report(report_input)
    content = _append_unassessed_results(content, bundle.output)
    _atomic_write(destination, content, force=request.force)
    profile_id = bundle.profile.id
    if profile_id is None:
        raise CliError(CliErrorCode.MISSING_PROFILE_ID, 4)
    return ReportWrittenOutput(
        output_path=str(destination),
        profile_id=int(profile_id),
        result_count=len(bundle.output.results),
    )


def _atomic_write(destination: Path, content: str, *, force: bool) -> None:
    if not destination.parent.is_dir():
        raise CliError(CliErrorCode.OUTPUT_PARENT_MISSING, 3)
    if destination.exists() and not force:
        raise CliError(CliErrorCode.OUTPUT_EXISTS, 3)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            _ = handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _ = temporary.replace(destination)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                raise CliError(CliErrorCode.REPORT_CLEANUP_FAILED, 4) from None
        raise CliError(CliErrorCode.REPORT_WRITE_FAILED, 4) from None


def _append_unassessed_results(content: str, output: SearchOutput) -> str:
    gaps = tuple(result for result in output.results if result.final_status is None)
    if not gaps:
        return content
    lines = [content.rstrip("\n"), "", "## review gaps"]
    for result in gaps:
        errors = ", ".join(escape_markdown(error) for error in result.input_errors) or "none"
        lines.extend(
            (
                "",
                f"## unassessed program {result.program_id} - {escape_markdown(result.title)}",
                f"organization: {escape_markdown(result.organization or 'none')}",
                f"review_status: {result.review_status.value}",
                f"input_errors: {errors}",
            )
        )
    return "\n".join(lines) + "\n"
