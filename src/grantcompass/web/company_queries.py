"""Managed-company ledger read queries."""

from dataclasses import dataclass

from sqlalchemy import select
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
    managed_rows = (
        await session.scalars(select(ManagedCompanyRow).order_by(ManagedCompanyRow.id))
    ).all()
    entries: list[CompanyEntry] = []
    for managed in managed_rows:
        profile = (
            await session.scalars(
                select(ApplicantProfileRow).where(ApplicantProfileRow.id == managed.profile_id)
            )
        ).one()
        case = await session.scalar(
            select(CaseRow)
            .where(CaseRow.managed_company_id == managed.id)
            .order_by(CaseRow.id.desc())
            .limit(1)
        )
        entries.append(
            CompanyEntry(
                managed.id,
                profile.display_name,
                managed.owner_name,
                managed.active,
                case.id if case else None,
                case.stage if case else None,
            )
        )
    return tuple(entries)


__all__ = ["list_companies"]
