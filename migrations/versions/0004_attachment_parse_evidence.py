"""Persist attachment parse failures and block-level PDF provenance.

Revision ID: 0004_attachment_parse_evidence
Revises: 0003_current_notice_state
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_attachment_parse_evidence"
down_revision: str | None = "0003_current_notice_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable evidence fields while preserving every existing row."""
    op.add_column("attachments", sa.Column("parse_error_code", sa.String(100)))
    op.add_column(
        "attachments",
        sa.Column(
            "requires_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("attachments", sa.Column("parser_name", sa.String(100)))
    op.add_column("attachments", sa.Column("parser_version", sa.String(100)))
    op.add_column("document_blocks", sa.Column("source_block_id", sa.String(200)))
    op.add_column("document_blocks", sa.Column("bbox_json", sa.Text()))
    op.add_column("document_blocks", sa.Column("confidence", sa.Float()))
    op.add_column("document_blocks", sa.Column("provenance", sa.String(40)))
    op.create_index(
        "uq_documents_attachment",
        "documents",
        ["attachment_id"],
        unique=True,
    )


def downgrade() -> None:
    """Remove parse evidence columns without altering base attachment rows."""
    op.drop_index("uq_documents_attachment", table_name="documents")
    op.drop_column("document_blocks", "provenance")
    op.drop_column("document_blocks", "confidence")
    op.drop_column("document_blocks", "bbox_json")
    op.drop_column("document_blocks", "source_block_id")
    op.drop_column("attachments", "parser_version")
    op.drop_column("attachments", "parser_name")
    op.drop_column("attachments", "requires_review")
    op.drop_column("attachments", "parse_error_code")
