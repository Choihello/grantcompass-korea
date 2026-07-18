import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from sqlalchemy import func, select
from typer import Typer
from typer.testing import CliRunner, Result

from grantcompass.cli.app import create_app
from grantcompass.cli.schemas import ProfileCreatedOutput, ReportWrittenOutput, SearchOutput
from grantcompass.domain.enums import FinalStatus, FreshnessStatus, ReviewStatus, SourceName
from grantcompass.storage.db import create_engine, create_session_factory
from grantcompass.storage.table_eligibility import ApplicantProfileRow
from tests.cli_fixtures import make_dependencies
from tests.cli_search_fixtures import seed_search_fixture


def test_db_init_is_idempotent_against_real_isolated_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    database_path = tmp_path / "grantcompass.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    monkeypatch.setenv(
        "GRANTCOMPASS_DATABASE_URL",
        database_url,
    )
    runner = CliRunner()
    app = create_app()

    # When
    first = runner.invoke(app, ["db", "init"])
    second = runner.invoke(app, ["db", "init"])

    # Then
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert anyio.run(_profile_count, database_url) == 0


def test_search_flow_is_reproducible_against_real_sqlite(tmp_path: Path) -> None:
    # Given
    runner, app, _ = _prepared_flow(tmp_path)

    # When
    first_search = runner.invoke(app, ["search", "--profile", "1", "--json"])
    second_search = runner.invoke(app, ["search", "--profile", "1", "--json"])

    # Then
    _assert_search_results(first_search, second_search)


def test_installed_search_json_is_utf8_and_single_document(tmp_path: Path) -> None:
    # Given
    database_path = tmp_path / "installed.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    runner = CliRunner()
    app = create_app(make_dependencies(database_url))
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    created = runner.invoke(
        app,
        [
            "profile",
            "create",
            "--name",
            "한국 테스트기업",
            "--region",
            "서울",
            "--industry",
            "소프트웨어",
            "--json",
        ],
    )
    assert created.exit_code == 0
    anyio.run(seed_search_fixture, database_url)
    stdout_path = tmp_path / "search.json"
    executable_name = "grantcompass.exe" if sys.platform == "win32" else "grantcompass"
    executable = Path(sys.executable).with_name(executable_name)
    environment = os.environ.copy()
    environment["GRANTCOMPASS_DATABASE_URL"] = database_url
    environment["PYTHONIOENCODING"] = "cp949"
    environment["PYTHONUTF8"] = "0"

    # When
    with stdout_path.open("wb") as stdout_file:
        completed = subprocess.run(  # noqa: S603 - invokes the local installed CLI under test
            [str(executable), "search", "--profile", "1", "--json"],
            env=environment,
            stdout=stdout_file,
            stderr=subprocess.PIPE,
            check=False,
        )
    raw_output = stdout_path.read_bytes()

    # Then
    assert completed.returncode == 0
    assert completed.stderr == b""
    assert not raw_output.startswith(b"\xef\xbb\xbf")
    assert b"\x1b[" not in raw_output
    assert raw_output.endswith(b"\n")
    assert not raw_output[:-1].endswith(b"\n")
    decoded = raw_output[:-1].decode("utf-8")
    search_output = SearchOutput.model_validate_json(decoded)
    assert search_output.profile.display_name == "한국 테스트기업"
    assert "합성 지원사업 1" in decoded


def test_report_writes_all_search_programs_and_review_gaps(tmp_path: Path) -> None:
    # Given
    runner, app, report_path = _prepared_flow(tmp_path)

    # When
    reported = runner.invoke(
        app,
        ["report", "--profile", "1", "--out", str(report_path), "--json"],
    )

    # Then
    _assert_report_written(reported, report_path)


def test_report_refuses_existing_output_without_force(tmp_path: Path) -> None:
    # Given
    runner, app, report_path = _prepared_flow(tmp_path)
    first = runner.invoke(
        app,
        ["report", "--profile", "1", "--out", str(report_path), "--json"],
    )
    assert first.exit_code == 0

    # When
    refused = runner.invoke(
        app,
        ["report", "--profile", "1", "--out", str(report_path), "--json"],
    )

    # Then
    assert refused.exit_code == 3
    assert refused.stdout == ""
    assert refused.stderr == "output_exists\n"


def test_report_force_replaces_existing_output_atomically(tmp_path: Path) -> None:
    # Given
    runner, app, report_path = _prepared_flow(tmp_path)
    first = runner.invoke(
        app,
        ["report", "--profile", "1", "--out", str(report_path), "--json"],
    )
    assert first.exit_code == 0
    _ = report_path.write_text("sentinel", encoding="utf-8")

    # When
    forced = runner.invoke(
        app,
        [
            "report",
            "--profile",
            "1",
            "--out",
            str(report_path),
            "--force",
            "--json",
        ],
    )

    # Then
    assert forced.exit_code == 0
    forced_output = ReportWrittenOutput.model_validate_json(forced.stdout)
    assert forced_output.schema_version == "1.0"
    assert report_path.read_text(encoding="utf-8").startswith("# GrantCompass report\n")


def _prepared_flow(tmp_path: Path) -> tuple[CliRunner, Typer, Path]:
    database_path = tmp_path / "flow.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    app = create_app(make_dependencies(database_url))
    runner = CliRunner()
    assert runner.invoke(app, ["db", "init"]).exit_code == 0
    _prepare_search_fixture(runner, app, database_url)
    report_path = tmp_path / "reports" / "합성기업.md"
    _ = report_path.parent.mkdir()
    return runner, app, report_path


def _prepare_search_fixture(
    runner: CliRunner,
    app: Typer,
    database_url: str,
) -> None:
    created = runner.invoke(
        app,
        [
            "profile",
            "create",
            "--name",
            "  합성기업  ",
            "--founded-on",
            "2025-01-01",
            "--region",
            "서울",
            "--region",
            "서울",
            "--region",
            "인천",
            "--industry",
            "software",
            "--industry",
            "software",
            "--json",
        ],
    )
    assert created.exit_code == 0
    profile_output = ProfileCreatedOutput.model_validate_json(created.stdout)
    assert profile_output.profile_id == 1
    stored_profile = anyio.run(_stored_profile, database_url)
    assert stored_profile == ("합성기업", '["서울","인천"]', '["software"]')
    anyio.run(seed_search_fixture, database_url)


def _assert_search_results(first_search: Result, second_search: Result) -> None:
    assert first_search.exit_code == 0
    assert first_search.stderr == ""
    assert first_search.stdout == second_search.stdout
    search_output = SearchOutput.model_validate_json(first_search.stdout)
    assert first_search.stdout == search_output.model_dump_json() + "\n"
    assert search_output.schema_version == "1.0"
    assert search_output.profile.id == 1
    assert tuple(result.final_status for result in search_output.results[:4]) == (
        FinalStatus.ELIGIBLE,
        FinalStatus.CONDITIONAL,
        FinalStatus.NEEDS_REVIEW,
        FinalStatus.INELIGIBLE,
    )
    assert search_output.results[4].final_status is None
    assert search_output.results[4].review_status is ReviewStatus.REVIEW_REQUIRED
    assert search_output.results[4].input_errors == ("missing_rules",)
    assert search_output.results[0].conditions[0].evidence_ids == (10,)
    assert search_output.results[0].evidence[0].source_url.startswith("https://")
    assert search_output.results[1].roadmap[0].code == "satisfy_condition"
    assert search_output.results[2].roadmap[0].code == "verify_unknown"
    freshness = {item.source: item for item in search_output.source_freshness}
    assert freshness[SourceName.KSTARTUP].status is FreshnessStatus.FRESH
    assert freshness[SourceName.BIZINFO].status is FreshnessStatus.STALE
    assert freshness[SourceName.BIZINFO].error_code == "synthetic_stale"
    assert freshness[SourceName.BIZINFO].last_successful_at is not None


def _assert_report_written(reported: Result, report_path: Path) -> None:
    assert reported.exit_code == 0
    assert reported.stderr == ""
    report_output = ReportWrittenOutput.model_validate_json(reported.stdout)
    assert report_output.profile_id == 1
    assert report_output.result_count == 5
    assert report_output.output_path == str(report_path.resolve())
    report = report_path.read_text(encoding="utf-8")
    assert report.startswith("# GrantCompass report\n")
    assert "generated_at:" in report
    assert "profile_id:" in report
    assert "official_url:" in report
    assert "document_hash:" in report
    assert "block_id:" in report
    assert "review_status: review_required" in report
    assert "missing\\_rules" in report
    assert report.count("missing\\_rules") == 1
    represented_programs = tuple(
        line
        for line in report.splitlines()
        if line.startswith(("## program ", "## unassessed program "))
    )
    assert len(represented_programs) == report_output.result_count
    assert not tuple(report_path.parent.glob(".*.tmp"))


async def _profile_count(database_url: str) -> int:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            result = await session.execute(select(func.count(ApplicantProfileRow.id)))
            return result.scalar_one()
    finally:
        await engine.dispose()


async def _stored_profile(database_url: str) -> tuple[str, str, str] | None:
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            row = await session.get(ApplicantProfileRow, 1)
            if row is None:
                return None
            return row.display_name, row.regions_json, row.industries_json
    finally:
        await engine.dispose()
