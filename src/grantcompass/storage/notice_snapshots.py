"""Normalized immutable notice values used by persistence analysis."""

from datetime import date
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError

from grantcompass.domain.programs import RawNotice

_CONFLICT_FIELDS = (
    "title",
    "organization",
    "summary",
    "application_start",
    "application_end",
)


class NoticeSnapshot(BaseModel):
    """Source-independent fields retained beside an immutable notice version."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    title: str
    organization: str | None
    summary: str | None
    application_start: date | None
    application_end: date | None
    detail_url: str
    attachments: tuple[str, ...]
    announcement_date: date | None = None

    @classmethod
    def from_raw(cls, raw: RawNotice) -> "NoticeSnapshot":
        """Create a stable source-independent snapshot from a boundary notice."""
        return cls(
            title=" ".join(raw.title.split()),
            organization=raw.organization,
            summary=raw.summary,
            application_start=raw.application_start,
            application_end=raw.application_end,
            announcement_date=raw.announcement_date,
            detail_url=str(raw.detail_url),
            attachments=tuple(
                "|".join(
                    (
                        item.filename,
                        str(item.download_url),
                        item.media_type or "",
                        item.content_hash or "",
                    )
                )
                for item in raw.attachments
            ),
        )

    def conflict_values(self) -> dict[str, str | None]:
        """Return fields whose source disagreements require explicit review."""
        return {
            "title": self.title,
            "organization": self.organization,
            "summary": self.summary,
            "application_start": _date_text(self.application_start),
            "application_end": _date_text(self.application_end),
        }


def parse_snapshot(value: str) -> NoticeSnapshot | None:
    """Parse a stored snapshot while tolerating upgraded legacy placeholders."""
    try:
        return NoticeSnapshot.model_validate_json(value)
    except ValidationError:
        return None


def changed_fields(previous: NoticeSnapshot, current: NoticeSnapshot) -> tuple[str, ...]:
    """Return deterministic normalized field names changed between versions."""
    return tuple(
        field_name
        for field_name in NoticeSnapshot.model_fields
        if getattr(previous, field_name) != getattr(current, field_name)
    )


def conflict_field_names() -> tuple[str, ...]:
    """Return the fixed fields compared across official sources."""
    return _CONFLICT_FIELDS


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
