from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import anyio
import httpx2
from pydantic import SecretStr
from typer.core import TyperGroup
from typer.main import get_command
from typer.testing import CliRunner

from grantcompass.cli.app import create_app
from grantcompass.cli.schemas import ProfileCreatedOutput, SearchOutput, SyncOutput
from grantcompass.config import Settings
from grantcompass.domain.enums import ConditionStatus, FreshnessStatus, SourceName
from grantcompass.http import create_async_client
from grantcompass.sources.base import SourceAdapter
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.table_eligibility import ApplicantProfileRow
from tests.cli_fixtures import (
    FailingAdapter,
    SuccessfulAdapter,
    make_dependencies,
)
from tests.cli_search_fixtures import seed_search_fixture


def test_cli_exposes_only_the_stable_personal_command_surface() -> None:
    # Given
    module_path = Path("src/grantcompass/cli/app.py")

    # When
    command = get_command(create_app())

    # Then
    assert module_path.is_file()
    assert isinstance(command, TyperGroup)
    assert set(command.commands) == {"db", "sources", "profile", "search", "report"}


def test_profile_errors_use_finite_codes_and_never_reveal_service_keys(tmp_path: Path) -> None:
    # Given
    database_path = tmp_path / "profiles.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    runner = CliRunner()
    app = create_app(make_dependencies(database_url))
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    created = runner.invoke(app, ["profile", "create", "--name", "기업 A", "--json"])
    assert ProfileCreatedOutput.model_validate_json(created.stdout).profile_id == 1

    # When
    duplicate = runner.invoke(app, ["profile", "create", "--name", "기업 A", "--json"])
    blank = runner.invoke(app, ["profile", "create", "--name", "   ", "--json"])
    long_region = runner.invoke(
        app,
        ["profile", "create", "--name", "기업 B", "--region", "가" * 101, "--json"],
    )
    credential_marker = "task11-secret-must-not-leak"
    invalid_app = create_app(
        make_dependencies(
            "invalid-database-url",
            kstartup_key=credential_marker,
            bizinfo_key=credential_marker,
        )
    )
    invalid_database = runner.invoke(invalid_app, ["db", "init"])

    # Then
    assert duplicate.exit_code == 3
    assert duplicate.stderr == "duplicate_profile_name\n"
    assert blank.exit_code == 3
    assert blank.stderr == "invalid_profile_input\n"
    assert long_region.exit_code == 3
    assert long_region.stderr == "invalid_profile_input\n"
    assert invalid_database.exit_code == 4
    assert invalid_database.stderr == "invalid_database_url\n"
    assert credential_marker not in invalid_database.stdout
    assert credential_marker not in invalid_database.stderr


def test_ambiguous_stored_profile_name_is_rejected(tmp_path: Path) -> None:
    # Given
    database_path = tmp_path / "ambiguous.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    runner = CliRunner()
    app = create_app(make_dependencies(database_url))
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    anyio.run(_seed_ambiguous_profiles, database_url)

    # When
    result = runner.invoke(app, ["search", "--profile", "중복기업", "--json"])

    # Then
    assert result.exit_code == 3
    assert result.stdout == ""
    assert result.stderr == "ambiguous_profile_name\n"


def test_source_sync_keeps_stale_results_visible_and_closes_owned_client(tmp_path: Path) -> None:
    # Given
    database_path = tmp_path / "sync.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    clients: list[httpx2.AsyncClient] = []

    def client_factory() -> httpx2.AsyncClient:
        client = create_async_client()
        clients.append(client)
        return client

    dependencies = make_dependencies(
        database_url,
        (
            SuccessfulAdapter(SourceName.KSTARTUP),
            FailingAdapter(SourceName.BIZINFO),
        ),
        kstartup_key="synthetic-key",
        bizinfo_key="synthetic-key",
        client_factory=client_factory,
    )
    runner = CliRunner()
    app = create_app(dependencies)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0

    # When
    result = runner.invoke(app, ["sources", "sync", "--source", "all", "--json"])

    # Then
    assert result.exit_code == 0
    assert result.stderr == ""
    output = SyncOutput.model_validate_json(result.stdout)
    assert result.stdout == output.model_dump_json() + "\n"
    assert tuple(item.source for item in output.results) == (
        SourceName.KSTARTUP,
        SourceName.BIZINFO,
    )
    assert output.results[0].freshness is FreshnessStatus.FRESH
    assert output.results[0].stored == 0
    assert output.results[1].freshness is FreshnessStatus.STALE
    assert output.results[1].error_code == "synthetic_upstream_stale"
    assert len(clients) == 1
    assert clients[0].is_closed


def test_source_sync_with_missing_keys_never_constructs_a_client(tmp_path: Path) -> None:
    # Given
    database_path = tmp_path / "missing-keys.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    def forbidden_client_factory() -> httpx2.AsyncClient:
        raise AssertionError

    runner = CliRunner()
    app = create_app(make_dependencies(database_url, client_factory=forbidden_client_factory))
    assert runner.invoke(app, ["db", "init"]).exit_code == 0

    # When
    result = runner.invoke(app, ["sources", "sync", "--source", "all", "--json"])

    # Then
    assert result.exit_code == 0
    assert result.stderr == ""
    output = SyncOutput.model_validate_json(result.stdout)
    assert len(output.results) == 2
    assert all(item.freshness is FreshnessStatus.STALE for item in output.results)
    assert all(item.error_code == "missing_service_key" for item in output.results)


def test_profile_create_persists_representative_birth_year_for_search(tmp_path: Path) -> None:
    # Given
    database_path = tmp_path / "representative.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    runner = CliRunner()
    app = create_app(make_dependencies(database_url))
    assert runner.invoke(app, ["db", "init"]).exit_code == 0

    # When
    created = runner.invoke(
        app,
        [
            "profile",
            "create",
            "--name",
            "대표자기업",
            "--representative-birth-year",
            "1990",
            "--json",
        ],
    )

    # Then
    assert created.exit_code == 0
    profile = ProfileCreatedOutput.model_validate_json(created.stdout)
    assert profile.profile_id == 1
    stored = anyio.run(_stored_representative_birth_year, database_url)
    assert stored == 1990
    anyio.run(partial(seed_search_fixture, database_url, representative_age=True))
    searched = runner.invoke(app, ["search", "--profile", "1", "--json"])
    search_output = SearchOutput.model_validate_json(searched.stdout)
    assert search_output.results[0].conditions[0].status is ConditionStatus.SATISFIED


def test_invalid_settings_are_finite_for_sync_and_report(tmp_path: Path) -> None:
    # Given
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'invalid.db').as_posix()}"
    dependencies = replace(
        make_dependencies(database_url),
        settings_provider=_invalid_settings,
    )
    runner = CliRunner()
    app = create_app(dependencies)

    # When
    sync_result = runner.invoke(app, ["sources", "sync", "--source", "all", "--json"])
    report_result = runner.invoke(
        app,
        ["report", "--profile", "1", "--out", str(tmp_path / "report.md"), "--json"],
    )

    # Then
    for result in (sync_result, report_result):
        assert result.exit_code == 4
        assert result.stdout == ""
        assert result.stderr == "invalid_configuration\n"
        assert "Traceback" not in result.stderr


def test_blank_service_keys_never_construct_client_or_adapter(tmp_path: Path) -> None:
    # Given
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'blank-keys.db').as_posix()}"
    dependencies = replace(
        make_dependencies(
            database_url,
            kstartup_key="   ",
            bizinfo_key="",
            client_factory=_forbidden_client_factory,
        ),
        adapter_factory=_ForbiddenAdapterFactory(),
    )
    runner = CliRunner()
    app = create_app(dependencies)
    assert runner.invoke(app, ["db", "init"]).exit_code == 0

    # When
    result = runner.invoke(app, ["sources", "sync", "--source", "all", "--json"])

    # Then
    assert result.exit_code == 0
    output = SyncOutput.model_validate_json(result.stdout)
    assert tuple(item.error_code for item in output.results) == (
        "missing_service_key",
        "missing_service_key",
    )


async def _seed_ambiguous_profiles(database_url: str) -> None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            session.add_all(
                (
                    _profile_row("중복기업"),
                    _profile_row("중복기업"),
                )
            )
    finally:
        await engine.dispose()


def _profile_row(display_name: str) -> ApplicantProfileRow:
    return ApplicantProfileRow(
        display_name=display_name,
        founded_on=None,
        regions_json="[]",
        representative_birth_year=None,
        industries_json="[]",
        performance_json="{}",
        benefit_history_json="[]",
        created_at=datetime(2026, 7, 15, 12, tzinfo=UTC),
    )


async def _stored_representative_birth_year(database_url: str) -> int | None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            row = await session.get(ApplicantProfileRow, 1)
            return None if row is None else row.representative_birth_year
    finally:
        await engine.dispose()


def _invalid_settings() -> Settings:
    return Settings(source_page_size=0)


def _forbidden_client_factory() -> httpx2.AsyncClient:
    raise AssertionError


class _ForbiddenAdapterFactory:
    def create(
        self,
        source: SourceName,
        client: httpx2.AsyncClient,
        service_key: SecretStr,
    ) -> SourceAdapter:
        del source, client, service_key
        raise AssertionError
