"""Validated institution form boundaries."""

from datetime import date
from typing import ClassVar

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from starlette.datastructures import FormData, UploadFile

from grantcompass.domain.enums import ConditionStatus

_INVALID_DOCUMENT_FIELD = "invalid_document_field"
_REQUIRED_FORM_TEXT = "required_form_text"
_CONDITION_PREFIX = "condition_status_"


class AttributionForm(BaseModel):
    """Attribution required for every institutional mutation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    actor: str
    reason: str
    csrf_token: str = Field(default="", exclude=True)


class ReviewConditionForm(BaseModel):
    """One explicit browser-submitted condition identity and override."""

    rule_assessment_id: int = Field(gt=0)
    status: ConditionStatus | None


class ReviewForm(AttributionForm):
    """Revision-bound human assessment review form."""

    expected_review_revision: int = Field(ge=0)
    conditions: tuple[ReviewConditionForm, ...] = Field(min_length=1)


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


async def parse_review_request(request: Request) -> ReviewForm:
    """Parse revision and per-condition identities from one review form."""
    data = await request.form()
    conditions = tuple(
        ReviewConditionForm(
            rule_assessment_id=int(name.removeprefix(_CONDITION_PREFIX)),
            status=None if value == "" else ConditionStatus(value),
        )
        for name, value in data.multi_items()
        if name.startswith(_CONDITION_PREFIX) and isinstance(value, str)
    )
    return ReviewForm.model_validate(
        {
            "actor": _required_text(data, "actor"),
            "reason": _required_text(data, "reason"),
            "expected_review_revision": _required_text(data, "expected_review_revision"),
            "conditions": conditions,
        }
    )


def _required_text(data: FormData, name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str):
        raise TypeError(_REQUIRED_FORM_TEXT)
    return value


__all__ = [
    "AttributionForm",
    "ManualProgramForm",
    "ReviewConditionForm",
    "ReviewForm",
    "TransitionForm",
    "parse_manual_request",
    "parse_review_request",
]
