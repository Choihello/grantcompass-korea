"""Mutable SQLAlchemy rows for profiles, rules, and assessments."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from grantcompass.storage.table_base import Base


class EligibilityRuleRow(Base):
    """Mutable normalized eligibility-rule row."""

    __tablename__: str = "eligibility_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    operator: Mapped[str] = mapped_column(String(40))
    expected_json: Mapped[str] = mapped_column(Text)
    required: Mapped[bool] = mapped_column()
    review_status: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[str] = mapped_column(String(100))


class ApplicantProfileRow(Base):
    """Mutable applicant-profile row managed by SQLAlchemy."""

    __tablename__: str = "applicant_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(300))
    founded_on: Mapped[date | None] = mapped_column(Date)
    regions_json: Mapped[str] = mapped_column(Text)
    representative_birth_year: Mapped[int | None] = mapped_column()
    industries_json: Mapped[str] = mapped_column(Text)
    performance_json: Mapped[str] = mapped_column(Text)
    benefit_history_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentRow(Base):
    """Mutable persisted assessment summary row."""

    __tablename__: str = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("applicant_profiles.id"), index=True)
    final_status: Mapped[str] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(40))
    rule_version: Mapped[str] = mapped_column(String(100))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_revision: Mapped[int] = mapped_column(default=0, server_default="0")


class RuleAssessmentRow(Base):
    """Mutable persisted result for one assessed rule."""

    __tablename__: str = "rule_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("eligibility_rules.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    explanation: Mapped[str] = mapped_column(Text)
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    error_id: Mapped[str | None] = mapped_column(String(100))
