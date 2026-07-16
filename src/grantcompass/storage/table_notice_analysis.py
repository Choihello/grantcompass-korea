"""Mutable rows for merge review, conflicts, and notice change impact."""

from datetime import datetime

from sqlalchemy import Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from grantcompass.storage.table_base import Base


class FieldConflictRow(Base):
    """Current source disagreement for a normalized program field."""

    __tablename__: str = "field_conflicts"
    __table_args__: tuple[UniqueConstraint] = (
        UniqueConstraint("program_id", "field_name", name="uq_field_conflict_program_field"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(80))
    values_json: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column()


class MergeCandidateRow(Base):
    """Potential duplicate deliberately withheld for human review."""

    __tablename__: str = "merge_candidates"
    __table_args__: tuple[UniqueConstraint] = (
        UniqueConstraint(
            "left_program_id",
            "right_program_id",
            name="uq_merge_candidate_pair",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    left_program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    right_program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    title_similarity: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(40))
    detected_at: Mapped[datetime] = mapped_column()


class ChangeSetRow(Base):
    """Persisted notice-version transition and its changed normalized fields."""

    __tablename__: str = "change_sets"
    __table_args__: tuple[UniqueConstraint] = (
        UniqueConstraint("current_version_id", name="uq_change_set_current_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    source_notice_id: Mapped[str] = mapped_column(String(300), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    changed_fields_json: Mapped[str] = mapped_column(Text)
    previous_version_id: Mapped[int] = mapped_column(ForeignKey("notice_versions.id"))
    current_version_id: Mapped[int] = mapped_column(ForeignKey("notice_versions.id"))
    detected_at: Mapped[datetime] = mapped_column()


class ChangeImpactRow(Base):
    """Assessment explicitly affected by one persisted notice change."""

    __tablename__: str = "change_impacts"

    change_set_id: Mapped[int] = mapped_column(ForeignKey("change_sets.id"), primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id"), primary_key=True, index=True
    )
