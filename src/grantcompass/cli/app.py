"""Typer presentation boundary for the personal GrantCompass workflow."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Annotated, Never

import anyio
import typer
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from grantcompass.cli.commands import (
    create_profile_command,
    initialize_command,
    report_command,
    search_command,
    sync_command,
)
from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.cli.reporting import ReportRequest
from grantcompass.cli.runtime import CliDependencies, default_dependencies
from grantcompass.cli.schemas import ProfileCreateInput, SearchOutput, SyncOutput
from grantcompass.cli.sync import SourceSelection


def create_app(dependencies: CliDependencies | None = None) -> typer.Typer:
    """Create a CLI app around production or injected dependencies."""
    runtime = dependencies or default_dependencies()
    root = typer.Typer(
        add_completion=False,
        no_args_is_help=True,
        pretty_exceptions_enable=False,
        rich_markup_mode=None,
    )
    database_app = typer.Typer(add_completion=False)
    sources_app = typer.Typer(add_completion=False)
    profile_app = typer.Typer(add_completion=False)

    @database_app.command("init")
    def initialize() -> None:
        _execute(partial(initialize_command, runtime))
        typer.echo("database_initialized")

    @sources_app.command("sync")
    def synchronize(
        *,
        source: Annotated[SourceSelection, typer.Option("--source")] = SourceSelection.ALL,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        output = _execute(partial(sync_command, runtime, source))
        _emit(output, _sync_human(output), json_output=json_output)

    @profile_app.command("create")
    def create_profile(
        *,
        name: Annotated[str, typer.Option("--name")],
        founded_on: Annotated[
            datetime | None,
            typer.Option("--founded-on", formats=["%Y-%m-%d"]),
        ] = None,
        region: Annotated[list[str] | None, typer.Option("--region")] = None,
        industry: Annotated[list[str] | None, typer.Option("--industry")] = None,
        representative_birth_year: Annotated[
            int | None,
            typer.Option("--representative-birth-year"),
        ] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        profile_input = _profile_input(
            name,
            founded_on,
            region,
            industry,
            representative_birth_year,
        )
        output = _execute(partial(create_profile_command, runtime, profile_input))
        _emit(
            output,
            (f"profile_id={output.profile_id} display_name={output.display_name}",),
            json_output=json_output,
        )

    @root.command("search")
    def search(
        *,
        profile: Annotated[str, typer.Option("--profile")],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        output = _execute(partial(search_command, runtime, profile))
        _emit(output, _search_human(output), json_output=json_output)

    @root.command("report")
    def report(
        *,
        profile: Annotated[str, typer.Option("--profile")],
        output_path: Annotated[Path, typer.Option("--out")],
        force: Annotated[bool, typer.Option("--force")] = False,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        request = ReportRequest(
            profile_selector=profile,
            output_path=output_path,
            force=force,
        )
        output = _execute(partial(report_command, runtime, request))
        _emit(output, (f"report={output.output_path}",), json_output=json_output)

    _ = (initialize, synchronize, create_profile, search, report)
    root.add_typer(database_app, name="db")
    root.add_typer(sources_app, name="sources")
    root.add_typer(profile_app, name="profile")
    return root


def _profile_input(
    name: str,
    founded_on: datetime | None,
    regions: list[str] | None,
    industries: list[str] | None,
    representative_birth_year: int | None,
) -> ProfileCreateInput:
    try:
        return ProfileCreateInput(
            display_name=name,
            founded_on=None if founded_on is None else founded_on.date(),
            regions=tuple(regions or ()),
            industries=tuple(industries or ()),
            representative_birth_year=representative_birth_year,
        )
    except ValidationError:
        _fail(CliError(CliErrorCode.INVALID_PROFILE_INPUT, 3))


def _execute[T](command: Callable[[], Awaitable[T]]) -> T:
    try:
        return anyio.run(command)
    except CliError as error:
        _fail(error)
    except SQLAlchemyError:
        _fail(CliError(CliErrorCode.STORAGE_ERROR, 4))
    except OSError:
        _fail(CliError(CliErrorCode.FILESYSTEM_ERROR, 4))


def _fail(error: CliError) -> Never:
    typer.echo(error.code.value, err=True)
    raise typer.Exit(error.exit_code) from None


def _emit(
    output: BaseModel,
    human_lines: tuple[str, ...],
    *,
    json_output: bool,
) -> None:
    if json_output:
        typer.echo(output.model_dump_json().encode("utf-8"))
        return
    for line in human_lines:
        typer.echo(line)


def _sync_human(output: SyncOutput) -> tuple[str, ...]:
    return tuple(
        " ".join(
            (
                f"source={item.source.value}",
                f"freshness={item.freshness.value}",
                f"stored={item.stored}",
                f"unchanged={item.unchanged}",
                f"failed={item.failed}",
                f"error_code={item.error_code or 'none'}",
            )
        )
        for item in output.results
    )


def _search_human(output: SearchOutput) -> tuple[str, ...]:
    freshness = tuple(
        " ".join(
            (
                f"source={item.source.value}",
                f"freshness={item.status.value}",
                f"error_code={item.error_code or 'none'}",
            )
        )
        for item in output.source_freshness
    )
    programs = tuple(
        " ".join(
            (
                f"program_id={item.program_id}",
                "final_status="
                + (item.final_status.value if item.final_status is not None else "unavailable"),
                f"review_status={item.review_status.value}",
                f"errors={','.join(item.input_errors) or 'none'}",
            )
        )
        for item in output.results
    )
    return (*freshness, *programs)


app = create_app()
