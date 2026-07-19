"""Preserve automatic errors and serialize assessment reviews.

Revision ID: 0005_review_integrity
Revises: 0004_attachment_parse_evidence
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_review_integrity"
down_revision: str | None = "0004_attachment_parse_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add durable error context and an optimistic review revision."""
    op.add_column("rule_assessments", sa.Column("error_id", sa.String(100)))
    op.add_column(
        "assessments",
        sa.Column(
            "review_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Remove fields owned by the review-integrity revision."""
    op.drop_column("assessments", "review_revision")
    op.drop_column("rule_assessments", "error_id")
