"""Complete the release-blocker schema without unsafe recurrence reversal."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_release_blockers"
down_revision: str | None = "0005_review_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _IrreversibleRecurrenceDowngradeError(RuntimeError):
    _MESSAGE = (
        "0006_release_blockers is irreversible after recurrence support; "
        "restore a pre-upgrade backup instead"
    )

    def __init__(self) -> None:
        super().__init__(self._MESSAGE)


def upgrade() -> None:
    """Apply release integrity, provenance, and retry-state columns."""
    with op.batch_alter_table("change_sets") as batch_op:
        batch_op.drop_constraint("uq_change_set_current_version", type_="unique")
    op.drop_index("uq_documents_attachment", table_name="documents")
    with op.batch_alter_table("documents") as batch_op:
        batch_op.create_unique_constraint("uq_documents_attachment", ["attachment_id"])
    with op.batch_alter_table("programs") as batch_op:
        batch_op.add_column(sa.Column("reference_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("reference_date_source", sa.String(40), nullable=True))
    op.execute(sa.text("UPDATE programs SET reference_date = date(created_at)"))
    op.execute(sa.text("UPDATE programs SET reference_date_source = 'collected_at_fallback'"))
    with op.batch_alter_table("programs") as batch_op:
        batch_op.alter_column("reference_date", existing_type=sa.Date(), nullable=False)
        batch_op.alter_column(
            "reference_date_source",
            existing_type=sa.String(40),
            nullable=False,
        )
    with op.batch_alter_table("notice_versions") as batch_op:
        batch_op.add_column(sa.Column("announcement_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("reference_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("reference_date_source", sa.String(40), nullable=True))
    op.execute(sa.text("UPDATE notice_versions SET reference_date = date(collected_at)"))
    op.execute(
        sa.text("UPDATE notice_versions SET reference_date_source = 'collected_at_fallback'")
    )
    with op.batch_alter_table("notice_versions") as batch_op:
        batch_op.alter_column("reference_date", existing_type=sa.Date(), nullable=False)
        batch_op.alter_column(
            "reference_date_source",
            existing_type=sa.String(40),
            nullable=False,
        )
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False)
        )
    with op.batch_alter_table("eligibility_rules") as batch_op:
        batch_op.add_column(sa.Column("source_document_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_eligibility_rules_source_document_id_documents",
            "documents",
            ["source_document_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_eligibility_rules_source_document_id",
            ["source_document_id"],
        )


def downgrade() -> None:
    """Fail before mutation because recurrence cannot fit the prior uniqueness contract."""
    raise _IrreversibleRecurrenceDowngradeError
