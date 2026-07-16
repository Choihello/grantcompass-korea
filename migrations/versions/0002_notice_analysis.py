"""Add conservative merge review and notice change tracking.

Revision ID: 0002_notice_analysis
Revises: 0001_initial
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_notice_analysis"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable normalized snapshots and analysis records."""
    with op.batch_alter_table("notice_versions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "normalized_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
    op.create_table(
        "field_conflicts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "program_id",
            "field_name",
            name="uq_field_conflict_program_field",
        ),
    )
    op.create_index("ix_field_conflicts_program_id", "field_conflicts", ["program_id"])
    op.create_table(
        "merge_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("left_program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("right_program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("title_similarity", sa.Float(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "left_program_id",
            "right_program_id",
            name="uq_merge_candidate_pair",
        ),
    )
    op.create_index("ix_merge_candidates_left_program_id", "merge_candidates", ["left_program_id"])
    op.create_index(
        "ix_merge_candidates_right_program_id", "merge_candidates", ["right_program_id"]
    )
    op.create_table(
        "change_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_notice_id", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("changed_fields_json", sa.Text(), nullable=False),
        sa.Column(
            "previous_version_id",
            sa.Integer(),
            sa.ForeignKey("notice_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "current_version_id",
            sa.Integer(),
            sa.ForeignKey("notice_versions.id"),
            nullable=False,
        ),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("current_version_id", name="uq_change_set_current_version"),
    )
    op.create_index("ix_change_sets_source", "change_sets", ["source"])
    op.create_index("ix_change_sets_source_notice_id", "change_sets", ["source_notice_id"])
    op.create_table(
        "change_impacts",
        sa.Column(
            "change_set_id",
            sa.Integer(),
            sa.ForeignKey("change_sets.id"),
            primary_key=True,
        ),
        sa.Column(
            "assessment_id",
            sa.Integer(),
            sa.ForeignKey("assessments.id"),
            primary_key=True,
        ),
    )
    op.create_index("ix_change_impacts_assessment_id", "change_impacts", ["assessment_id"])


def downgrade() -> None:
    """Remove analysis records and normalized snapshots."""
    op.drop_table("change_impacts")
    op.drop_table("change_sets")
    op.drop_table("merge_candidates")
    op.drop_table("field_conflicts")
    with op.batch_alter_table("notice_versions") as batch_op:
        batch_op.drop_column("normalized_json")
