"""Async command services independent from Typer presentation."""

from pydantic import ValidationError

from grantcompass.cli.database import create_cli_engine, initialize_database
from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.cli.profiles import ProfileRepository
from grantcompass.cli.reporting import ReportRequest, generate_report
from grantcompass.cli.runtime import CliDependencies
from grantcompass.cli.schemas import (
    ProfileCreatedOutput,
    ProfileCreateInput,
    ReportWrittenOutput,
    SearchOutput,
    SyncOutput,
)
from grantcompass.cli.search import search_programs
from grantcompass.cli.sync import SourceSelection, synchronize_sources
from grantcompass.config import Settings
from grantcompass.storage.db import create_session_factory


async def initialize_command(dependencies: CliDependencies) -> None:
    """Initialize the complete configured database schema."""
    await initialize_database(_settings(dependencies).database_url)


async def create_profile_command(
    dependencies: CliDependencies,
    profile_input: ProfileCreateInput,
) -> ProfileCreatedOutput:
    """Create one unique profile and return its persisted identity."""
    settings = _settings(dependencies)
    engine = create_cli_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            profile = await ProfileRepository(session).create(
                profile_input,
                dependencies.clock.now(),
            )
            if profile.id is None:
                raise CliError(CliErrorCode.MISSING_PROFILE_ID, 4)
            return ProfileCreatedOutput(
                profile_id=int(profile.id),
                display_name=profile.display_name,
            )
    finally:
        await engine.dispose()


async def search_command(
    dependencies: CliDependencies,
    profile_selector: str,
) -> SearchOutput:
    """Run one reproducible search for a selected profile."""
    settings = _settings(dependencies)
    return (
        await search_programs(
            settings.database_url,
            profile_selector,
            dependencies.clock.now(),
        )
    ).output


async def sync_command(
    dependencies: CliDependencies,
    selection: SourceSelection,
) -> SyncOutput:
    """Synchronize selected official sources."""
    return await synchronize_sources(dependencies, selection)


async def report_command(
    dependencies: CliDependencies,
    request: ReportRequest,
) -> ReportWrittenOutput:
    """Generate and atomically persist a Task 10 Markdown report."""
    return await generate_report(dependencies, request)


def _settings(dependencies: CliDependencies) -> Settings:
    try:
        return dependencies.settings_provider()
    except ValidationError:
        raise CliError(CliErrorCode.INVALID_CONFIGURATION, 4) from None
