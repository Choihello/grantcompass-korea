"""Applicant profile persistence and finite lookup semantics."""

import json
from datetime import datetime
from typing import final

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.cli.schemas import ProfileCreateInput
from grantcompass.domain.eligibility import ApplicantProfile, ApplicantProfileId
from grantcompass.domain.json_types import JsonObject, freeze_json_object
from grantcompass.storage.table_eligibility import ApplicantProfileRow

_STRING_TUPLE: TypeAdapter[tuple[str, ...]] = TypeAdapter(tuple[str, ...])
_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_JSON_OBJECT_TUPLE: TypeAdapter[tuple[JsonObject, ...]] = TypeAdapter(tuple[JsonObject, ...])


@final
class ProfileRepository:
    """Create and resolve applicant profiles in one caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind profile operations to one async unit of work."""
        self._session: AsyncSession = session

    async def create(
        self, profile_input: ProfileCreateInput, created_at: datetime
    ) -> ApplicantProfile:
        """Persist one validated unique display name with one commit."""
        async with self._session.begin():
            duplicate_count = (
                await self._session.execute(
                    select(func.count(ApplicantProfileRow.id)).where(
                        ApplicantProfileRow.display_name == profile_input.display_name
                    )
                )
            ).scalar_one()
            if duplicate_count:
                raise CliError(CliErrorCode.DUPLICATE_PROFILE_NAME, 3)
            row = ApplicantProfileRow(
                display_name=profile_input.display_name,
                founded_on=profile_input.founded_on,
                regions_json=_compact_json(profile_input.regions),
                representative_birth_year=profile_input.representative_birth_year,
                industries_json=_compact_json(profile_input.industries),
                performance_json="{}",
                benefit_history_json="[]",
                created_at=created_at,
            )
            self._session.add(row)
            await self._session.flush()
            return profile_from_row(row)

    async def resolve(self, selector: str) -> ApplicantProfile:
        """Resolve one numeric ID or one unambiguous exact display name."""
        normalized = selector.strip()
        if normalized.isdecimal():
            row = await self._session.scalar(
                select(ApplicantProfileRow).where(ApplicantProfileRow.id == int(normalized))
            )
            if row is None:
                raise CliError(CliErrorCode.PROFILE_NOT_FOUND, 3)
            return profile_from_row(row)
        rows = (
            await self._session.scalars(
                select(ApplicantProfileRow)
                .where(ApplicantProfileRow.display_name == normalized)
                .order_by(ApplicantProfileRow.id)
            )
        ).all()
        if not rows:
            raise CliError(CliErrorCode.PROFILE_NOT_FOUND, 3)
        if len(rows) > 1:
            raise CliError(CliErrorCode.AMBIGUOUS_PROFILE_NAME, 3)
        return profile_from_row(rows[0])


def profile_from_row(row: ApplicantProfileRow) -> ApplicantProfile:
    """Convert one batch-loaded persistence row through the profile boundary."""
    try:
        return ApplicantProfile(
            id=ApplicantProfileId(row.id),
            display_name=row.display_name,
            founded_on=row.founded_on,
            regions=_STRING_TUPLE.validate_json(row.regions_json),
            representative_birth_year=row.representative_birth_year,
            industries=_STRING_TUPLE.validate_json(row.industries_json),
            performance=freeze_json_object(_JSON_OBJECT.validate_json(row.performance_json)),
            benefit_history=tuple(
                freeze_json_object(item)
                for item in _JSON_OBJECT_TUPLE.validate_json(row.benefit_history_json)
            ),
        )
    except ValidationError:
        raise CliError(CliErrorCode.MALFORMED_PROFILE_RECORD, 4) from None


def _compact_json(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


__all__ = ["ProfileRepository", "profile_from_row"]
