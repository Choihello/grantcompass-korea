"""Mutable SQLAlchemy rows for collected programs and notices."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from grantcompass.storage.table_base import Base


class ProgramRow(Base):
    """Mutable canonical-program row managed by SQLAlchemy."""

    __tablename__: str = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    organization: Mapped[str | None] = mapped_column(String(300))
    application_start: Mapped[date | None] = mapped_column(Date)
    application_end: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NoticeVersionRow(Base):
    """Mutable ORM row representing an immutable notice snapshot."""

    __tablename__: str = "notice_versions"
    __table_args__: tuple[UniqueConstraint] = (
        UniqueConstraint(
            "source",
            "source_notice_id",
            "content_hash",
            name="uq_notice_source_identity_hash",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    source_notice_id: Mapped[str] = mapped_column(String(300), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    detail_url: Mapped[str] = mapped_column(Text)
    raw_payload_json: Mapped[str] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AttachmentRow(Base):
    """Mutable attachment download and parsing state."""

    __tablename__: str = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    notice_version_id: Mapped[int] = mapped_column(ForeignKey("notice_versions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    download_url: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    local_path: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(40), default="pending")


class SourceRunRow(Base):
    """Mutable collection-run state and visible failure record."""

    __tablename__: str = "source_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40))
    item_count: Mapped[int] = mapped_column(default=0)
    response_hash: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
