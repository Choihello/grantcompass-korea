"""Validated institution form boundaries."""

from datetime import date
from typing import ClassVar

from fastapi import Request
from pydantic import BaseModel, ConfigDict, HttpUrl
from starlette.datastructures import FormData, UploadFile

_INVALID_DOCUMENT_FIELD = "invalid_document_field"
_REQUIRED_FORM_TEXT = "required_form_text"


class AttributionForm(BaseModel):
    """Attribution required for every institutional mutation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    actor: str
    reason: str


class ReviewForm(AttributionForm):
    """Human assessment review form."""

    status: str


class TransitionForm(AttributionForm):
    """Support-case stage transition form."""

    stage: str


class ManualProgramForm(AttributionForm):
    """Institution-owned notice registration form."""

    title: str
    organization: str
    application_end: date
    source_url: HttpUrl


async def parse_manual_request(
    request: Request,
) -> tuple[ManualProgramForm, UploadFile | None]:
    """Parse a mixed multipart manual-notice form at one typed boundary."""
    data = await request.form()
    document_value = data.get("document")
    if document_value is not None and not isinstance(document_value, UploadFile):
        raise TypeError(_INVALID_DOCUMENT_FIELD)
    form = ManualProgramForm.model_validate(
        {
            "title": _required_text(data, "title"),
            "organization": _required_text(data, "organization"),
            "application_end": _required_text(data, "application_end"),
            "source_url": _required_text(data, "source_url"),
            "actor": _required_text(data, "actor"),
            "reason": _required_text(data, "reason"),
        }
    )
    return form, document_value


def _required_text(data: FormData, name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str):
        raise TypeError(_REQUIRED_FORM_TEXT)
    return value


__all__ = [
    "AttributionForm",
    "ManualProgramForm",
    "ReviewForm",
    "TransitionForm",
    "parse_manual_request",
]
