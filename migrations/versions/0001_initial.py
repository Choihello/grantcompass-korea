"""Create the canonical GrantCompass 0.1 schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all 0.1 domain tables, constraints, and lookup indexes."""
    op.create_table(
        "programs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_key", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("organization", sa.String(300)),
        sa.Column("application_start", sa.Date()),
        sa.Column("application_end", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_key"),
    )
    op.create_table(
        "notice_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_notice_id", sa.String(300), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("detail_url", sa.Text(), nullable=False),
        sa.Column("raw_payload_json", sa.Text(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source", "source_notice_id", "content_hash", name="uq_notice_source_identity_hash"
        ),
    )
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "notice_version_id", sa.Integer(), sa.ForeignKey("notice_versions.id"), nullable=False
        ),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("download_url", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(200)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("local_path", sa.Text()),
        sa.Column("parse_status", sa.String(40), nullable=False),
    )
    op.create_table(
        "source_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("response_hash", sa.String(64)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attachment_id", sa.Integer(), sa.ForeignKey("attachments.id"), nullable=False),
        sa.Column("parser_name", sa.String(100), nullable=False),
        sa.Column("parser_version", sa.String(100), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("parsed_at", sa.DateTime(), nullable=False),
        sa.Column("warning_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "document_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("section_path", sa.Text()),
        sa.Column("table_ref", sa.String(200)),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_block_ordinal"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("block_id", sa.Integer(), sa.ForeignKey("document_blocks.id"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("section_path", sa.Text()),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "eligibility_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("operator", sa.String(40), nullable=False),
        sa.Column("expected_json", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("review_status", sa.String(40), nullable=False),
        sa.Column("rule_version", sa.String(100), nullable=False),
    )
    op.create_table(
        "rule_evidence",
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("eligibility_rules.id"), primary_key=True),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidence.id"), primary_key=True),
    )
    op.create_table(
        "applicant_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(300), nullable=False),
        sa.Column("founded_on", sa.Date()),
        sa.Column("regions_json", sa.Text(), nullable=False),
        sa.Column("representative_birth_year", sa.Integer()),
        sa.Column("industries_json", sa.Text(), nullable=False),
        sa.Column("performance_json", sa.Text(), nullable=False),
        sa.Column("benefit_history_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("applicant_profiles.id"), nullable=False
        ),
        sa.Column("final_status", sa.String(40), nullable=False),
        sa.Column("review_status", sa.String(40), nullable=False),
        sa.Column("rule_version", sa.String(100), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "rule_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("eligibility_rules.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "managed_companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id", sa.Integer(), sa.ForeignKey("applicant_profiles.id"), nullable=False
        ),
        sa.Column("owner_name", sa.String(300), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "managed_company_id",
            sa.Integer(),
            sa.ForeignKey("managed_companies.id"),
            nullable=False,
        ),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("programs.id"), nullable=False),
        sa.Column("assignee_name", sa.String(300)),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("actor_name", sa.String(300), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_indexes()


def _create_indexes() -> None:
    for table, column in (
        ("notice_versions", "program_id"),
        ("notice_versions", "source"),
        ("notice_versions", "source_notice_id"),
        ("attachments", "notice_version_id"),
        ("source_runs", "source"),
        ("documents", "attachment_id"),
        ("document_blocks", "document_id"),
        ("evidence", "document_id"),
        ("evidence", "block_id"),
        ("eligibility_rules", "program_id"),
        ("assessments", "program_id"),
        ("assessments", "profile_id"),
        ("rule_assessments", "assessment_id"),
        ("rule_assessments", "rule_id"),
        ("managed_companies", "profile_id"),
        ("cases", "managed_company_id"),
        ("cases", "program_id"),
        ("audit_events", "entity_type"),
        ("audit_events", "entity_id"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    """Drop all 0.1 domain tables in dependency-safe order."""
    for table in (
        "audit_events",
        "cases",
        "managed_companies",
        "rule_assessments",
        "assessments",
        "applicant_profiles",
        "rule_evidence",
        "eligibility_rules",
        "evidence",
        "document_blocks",
        "documents",
        "source_runs",
        "attachments",
        "notice_versions",
        "programs",
    ):
        op.drop_table(table)
