from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Integer,
    String,
    column,
    create_engine,
    inspect,
    literal_column,
    select,
    table,
    text,
)

CHANGE_ID = column("id", Integer)
PREVIOUS_VERSION_ID = column("previous_version_id", Integer)
CURRENT_VERSION_ID = column("current_version_id", Integer)
CHANGE_SETS = table(
    "change_sets",
    CHANGE_ID,
    PREVIOUS_VERSION_ID,
    CURRENT_VERSION_ID,
)
CHANGE_ROWS = (
    select(CHANGE_ID, PREVIOUS_VERSION_ID, CURRENT_VERSION_ID)
    .select_from(CHANGE_SETS)
    .order_by(CHANGE_ID)
)


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
        attachment_columns = {item["name"]: item for item in inspector.get_columns("attachments")}
        assert "uq_documents_attachment" in document_constraints
        assert "uq_documents_attachment" not in document_indexes
        assert "uq_change_set_current_version" not in change_constraints
        assert program_columns["reference_date"]["nullable"] is False
        assert program_columns["reference_date_source"]["nullable"] is False
        assert version_columns["announcement_date"]["nullable"] is True
        assert version_columns["reference_date"]["nullable"] is False
        assert version_columns["reference_date_source"]["nullable"] is False
        assert rule_columns["source_document_id"]["nullable"] is True
        assert attachment_columns["attempt_count"]["nullable"] is False
    finally:
        engine.dispose()


def test_recurrence_downgrade_is_explicitly_irreversible_before_mutation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "release-downgrade.db"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", async_url)
    command.upgrade(config, "head")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as connection:
            _ = connection.execute(
                text(
                    """
                    INSERT INTO programs
                    (id, canonical_key, title, reference_date, reference_date_source,
                     created_at, updated_at)
                    VALUES
                    (1, 'recurrence', 'Recurrence', '2026-01-01',
                     'collected_at_fallback', '2026-01-01', '2026-01-01')
                    """
                )
            )
            for version_id, content_hash in ((1, "a" * 64), (2, "b" * 64)):
                _ = connection.execute(
                    text(
                        """
                        INSERT INTO notice_versions
                        (id, program_id, source, source_notice_id, content_hash, detail_url,
                         raw_payload_json, normalized_json, collected_at, reference_date,
                         reference_date_source)
                        VALUES
                        (:id, 1, 'bizinfo', 'recurrence', :hash,
                         'https://official.example/notice', '{}', '{}', '2026-01-01',
                         '2026-01-01', 'collected_at_fallback')
                        """
                    ),
                    {"id": version_id, "hash": content_hash},
                )
            for change_id, previous_id in ((1, 1), (2, 2)):
                _ = connection.execute(
                    text(
                        """
                        INSERT INTO change_sets
                        (id, source, source_notice_id, kind, changed_fields_json,
                         previous_version_id, current_version_id, detected_at)
                        VALUES
                        (:id, 'bizinfo', 'recurrence', 'updated', '[]',
                         :previous, 2, '2026-01-01')
                        """
                    ),
                    {"id": change_id, "previous": previous_id},
                )
        before_tables = set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            before_rows = connection.execute(CHANGE_ROWS).all()
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match=r"irreversible.*recurrence"):
        command.downgrade(config, "0005_review_integrity")

    engine = create_engine(sync_url)
    try:
        assert set(inspect(engine).get_table_names()) == before_tables
        with engine.connect() as connection:
            after_rows = connection.execute(CHANGE_ROWS).all()
            revision = connection.scalar(
                select(literal_column("version_num", String)).select_from(text("alembic_version"))
            )
        assert after_rows == before_rows
        assert revision == "0006_release_blockers"
        assert "source_document_id" in {
            item["name"] for item in inspect(engine).get_columns("eligibility_rules")
        }
    finally:
        engine.dispose()
