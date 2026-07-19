from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_review_integrity_migration_upgrades_and_downgrades(tmp_path: Path) -> None:
    # Given: an empty real SQLite database at the pre-review-integrity revision.
    database_path = tmp_path / "migration.db"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", async_url)
    command.upgrade(config, "0004_attachment_parse_evidence")

    # When: review integrity is upgraded to head.
    command.upgrade(config, "head")

    # Then: durable error context and a non-null zero revision exist.
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        assessment_columns = {
            column["name"]: column for column in inspector.get_columns("assessments")
        }
        condition_columns = {
            column["name"]: column for column in inspector.get_columns("rule_assessments")
        }
        assert assessment_columns["review_revision"]["nullable"] is False
        assert str(assessment_columns["review_revision"]["default"]).strip("()'") == "0"
        assert condition_columns["error_id"]["nullable"] is True
    finally:
        engine.dispose()

    # When: the new revision is downgraded exactly one step.
    command.downgrade(config, "0004_attachment_parse_evidence")

    # Then: both added columns are removed without changing prior schema ownership.
    downgraded_engine = create_engine(sync_url)
    try:
        downgraded = inspect(downgraded_engine)
        assert "review_revision" not in {
            column["name"] for column in downgraded.get_columns("assessments")
        }
        assert "error_id" not in {
            column["name"] for column in downgraded.get_columns("rule_assessments")
        }
    finally:
        downgraded_engine.dispose()
