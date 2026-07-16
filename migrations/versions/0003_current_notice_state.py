"""Add explicit current notice state and human assessment notes.

Revision ID: 0003_current_notice_state
Revises: 0002_notice_analysis
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_current_notice_state"
down_revision: str | None = "0002_notice_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create current pointers, backfill legacy state, and add review notes."""
    op.create_table(
        "current_notice_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_notice_id", sa.String(300), nullable=False),
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("notice_versions.id"),
            nullable=False,
            unique=True,
        ),
        sa.UniqueConstraint("source", "source_notice_id", name="uq_current_notice_identity"),
    )
    op.create_index("ix_current_notice_versions_source", "current_notice_versions", ["source"])
    op.create_index(
        "ix_current_notice_versions_source_notice_id",
        "current_notice_versions",
        ["source_notice_id"],
    )
    op.create_index(
        "ix_current_notice_versions_version_id",
        "current_notice_versions",
        ["version_id"],
        unique=True,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO current_notice_versions (source, source_notice_id, version_id)
            SELECT notice.source, notice.source_notice_id, notice.id
            FROM notice_versions AS notice
            JOIN (
                SELECT source, source_notice_id, MAX(id) AS version_id
                FROM notice_versions
                GROUP BY source, source_notice_id
            ) AS latest ON latest.version_id = notice.id
            """
        )
    )
    op.create_table(
        "assessment_review_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("assessments.id"),
            nullable=False,
        ),
        sa.Column("reviewer_name", sa.String(300), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_assessment_review_notes_assessment_id",
        "assessment_review_notes",
        ["assessment_id"],
    )


def downgrade() -> None:
    """Remove review notes and explicit current pointers."""
    op.drop_table("assessment_review_notes")
    op.drop_table("current_notice_versions")
