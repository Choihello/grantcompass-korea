"""Mutable SQLAlchemy rows for institutional workflows and audits."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grantcompass.storage.table_base import Base


class ManagedCompanyRow(Base):
    """Mutable managed-company ownership row."""

    __tablename__: str = "managed_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("applicant_profiles.id"), index=True)
    owner_name: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(default=True)


class CaseRow(Base):
    """Mutable institutional support-case row."""

    __tablename__: str = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    managed_company_id: Mapped[int] = mapped_column(ForeignKey("managed_companies.id"), index=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    assignee_name: Mapped[str | None] = mapped_column(String(300))
    stage: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEventRow(Base):
    """Mutable append-only attribution row for state changes."""

    __tablename__: str = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(100))
    actor_name: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
