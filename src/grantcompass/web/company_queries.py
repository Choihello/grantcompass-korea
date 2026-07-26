"""Managed-company ledger read queries."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.storage.table_cases import CaseRow, ManagedCompanyRow
from grantcompass.storage.table_eligibility import ApplicantProfileRow


@dataclass(frozen=True, slots=True)
class CompanyEntry:
    """One managed company and its current support case."""

    id: int
    profile_name: str
    owner_name: str
    active: bool
    case_id: int | None
    case_stage: str | None


async def list_companies(session: AsyncSession) -> tuple[CompanyEntry, ...]:
    """Return every institution-managed company, including inactive records."""
    managed_rows = tuple(
        (await session.scalars(select(ManagedCompanyRow).order_by(ManagedCompanyRow.id))).all()
    )
    if not managed_rows:
        return ()
    profile_ids = tuple(managed.profile_id for managed in managed_rows)
    profiles = tuple(
        (
            await session.scalars(
                select(ApplicantProfileRow).where(ApplicantProfileRow.id.in_(profile_ids))
            )
        ).all()
    )
    profiles_by_id = {profile.id: profile for profile in profiles}
    company_ids = tuple(managed.id for managed in managed_rows)
    latest_case_ids = (
        select(func.max(CaseRow.id))
        .where(CaseRow.managed_company_id.in_(company_ids))
        .group_by(CaseRow.managed_company_id)
    )
    cases = tuple(
        (await session.scalars(select(CaseRow).where(CaseRow.id.in_(latest_case_ids)))).all()
    )
    cases_by_company = {case.managed_company_id: case for case in cases}
    return tuple(
        CompanyEntry(
            managed.id,
            profiles_by_id[managed.profile_id].display_name,
            managed.owner_name,
            managed.active,
            cases_by_company[managed.id].id if managed.id in cases_by_company else None,
            cases_by_company[managed.id].stage if managed.id in cases_by_company else None,
        )
        for managed in managed_rows
    )


__all__ = ["list_companies"]
