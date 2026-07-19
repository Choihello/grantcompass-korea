from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.cli.assessment_store import persist_assessments
from grantcompass.cli.profiles import ProfileRepository
from grantcompass.cli.program_queries import ProgramQueryRepository
from grantcompass.rules.deterministic import DeterministicAssessmentEngine
from grantcompass.storage.table_eligibility import RuleAssessmentRow
from tests.integration.task12_fixtures import (
    REFERENCE_TIME,
    seed_profile,
    seed_program,
    seed_rule,
)

pytestmark = pytest.mark.anyio


async def test_personal_persistence_retains_condition_error_id(
    db_session: AsyncSession,
) -> None:
    # Given: Task 11 assesses a persisted profile with one missing required fact.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile_row = await seed_profile(db_session)
    profile_row.regions_json = "[]"
    await db_session.commit()
    profile = await ProfileRepository(db_session).resolve(str(profile_row.id))
    record = (await ProgramQueryRepository(db_session).list_program_rules())[0]
    assessment = DeterministicAssessmentEngine().assess(profile, record.rules, REFERENCE_TIME)

    # When: the personal caller uses the assessment persistence boundary.
    persisted = await persist_assessments(db_session, (assessment,))
    row = (
        await db_session.scalars(
            select(RuleAssessmentRow).where(
                RuleAssessmentRow.assessment_id == int(persisted[0].id or 0)
            )
        )
    ).one()

    # Then: the stable machine error identity reaches durable storage unchanged.
    assert row.error_id == assessment.items[0].error_id


def test_cli_persistence_module_contains_no_row_storage_implementation() -> None:
    # Given: the CLI adapter and shared storage implementation source files.
    cli_source = Path("src/grantcompass/cli/assessment_store.py").read_text(encoding="utf-8")

    # When: the CLI adapter is inspected for duplicated ORM behavior.
    duplicated_rows = tuple(
        token for token in ("AssessmentRow(", "RuleAssessmentRow(") if token in cli_source
    )

    # Then: the CLI delegates instead of owning a second persistence implementation.
    assert duplicated_rows == ()
