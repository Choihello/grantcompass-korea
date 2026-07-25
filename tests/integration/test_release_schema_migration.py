from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_fresh_upgrade_matches_orm_and_release_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "release-schema.db"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", async_url)

    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        document_constraints = {
            item["name"] for item in inspector.get_unique_constraints("documents")
        }
        document_indexes = {item["name"] for item in inspector.get_indexes("documents")}
        change_constraints = {
            item["name"] for item in inspector.get_unique_constraints("change_sets")
        }
        program_columns = {item["name"]: item for item in inspector.get_columns("programs")}
        version_columns = {item["name"]: item for item in inspector.get_columns("notice_versions")}
        rule_columns = {item["name"]: item for item in inspector.get_columns("eligibility_rules")}
        assert "uq_documents_attachment" in document_constraints
        assert "uq_documents_attachment" not in document_indexes
        assert "uq_change_set_current_version" not in change_constraints
        assert program_columns["reference_date"]["nullable"] is False
        assert program_columns["reference_date_source"]["nullable"] is False
        assert version_columns["announcement_date"]["nullable"] is True
        assert version_columns["reference_date"]["nullable"] is False
        assert version_columns["reference_date_source"]["nullable"] is False
        assert rule_columns["source_document_id"]["nullable"] is True
    finally:
        engine.dispose()
