"""Mutable SQLAlchemy rows for parsed documents and evidence."""

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from grantcompass.storage.table_base import Base


class DocumentRow(Base):
    """Mutable parsed-document row managed by SQLAlchemy."""

    __tablename__: str = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachments.id"), index=True)
    parser_name: Mapped[str] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    parsed_at: Mapped[datetime] = mapped_column()
    warning_json: Mapped[str] = mapped_column(Text, default="[]")


class DocumentBlockRow(Base):
    """Mutable addressable document-block row."""

    __tablename__: str = "document_blocks"
    __table_args__: tuple[UniqueConstraint] = (
        UniqueConstraint("document_id", "ordinal", name="uq_block_ordinal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    ordinal: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column()
    section_path: Mapped[str | None] = mapped_column(Text)
    table_ref: Mapped[str | None] = mapped_column(String(200))


class EvidenceRow(Base):
    """Mutable evidence row with exact document coordinates."""

    __tablename__: str = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("document_blocks.id"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column()
    section_path: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))


rule_evidence = Table(
    "rule_evidence",
    Base.metadata,
    Column("rule_id", Integer, ForeignKey("eligibility_rules.id"), primary_key=True),
    Column("evidence_id", Integer, ForeignKey("evidence.id"), primary_key=True),
)
