import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.reverse import CompanyInputErrorCode
from grantcompass.matching.reverse import ReverseMatchingService
from grantcompass.storage.table_documents import rule_evidence
from grantcompass.storage.table_eligibility import (
    ApplicantProfileRow,
    AssessmentRow,
    EligibilityRuleRow,
)
from grantcompass.storage.table_notice_analysis import CurrentNoticeVersionRow
from grantcompass.storage.table_programs import NoticeVersionRow
from tests.integration.task12_fixtures import (
    REFERENCE_TIME,
    program_id,
    seed_managed_company,
    seed_profile,
    seed_program,
    seed_rule,
)
from tests.integration.task12_reverse_fixtures import seed_reverse_matrix

pytestmark = pytest.mark.anyio


async def test_missing_rules_are_visible_for_every_company(db_session: AsyncSession) -> None:
    # Given: a canonical program with one managed company and no rules.
    program = await seed_program(db_session)
    profile = await seed_profile(db_session)
    _ = await seed_managed_company(db_session, profile)
    await db_session.commit()

    # When: reverse matching loads the incomplete program.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: the company remains visible without a fabricated assessment.
    assert results[0].assessment is None
    assert results[0].input_error is not None
    assert results[0].input_error.code is CompanyInputErrorCode.MISSING_RULES


async def test_missing_evidence_is_visible_for_every_company(db_session: AsyncSession) -> None:
    # Given: one normalized rule whose evidence association is missing.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile = await seed_profile(db_session)
    _ = await seed_managed_company(db_session, profile)
    _ = await db_session.execute(rule_evidence.delete())
    await db_session.commit()

    # When: reverse matching loads the incomplete rule.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: no automatic assessment is manufactured from incomplete evidence.
    assert results[0].assessment is None
    assert results[0].input_error is not None
    assert results[0].input_error.code is CompanyInputErrorCode.MISSING_EVIDENCE


async def test_malformed_rule_enum_is_visible(db_session: AsyncSession) -> None:
    # Given: one complete stored rule with a corrupted enum boundary.
    program = await seed_program(db_session)
    rule = await seed_rule(db_session, program)
    profile = await seed_profile(db_session)
    _ = await seed_managed_company(db_session, profile)
    rule.kind = "broken"
    await db_session.commit()

    # When: reverse matching parses the untrusted stored enum.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: enum corruption is finite and no assessment is persisted.
    count = await db_session.scalar(select(func.count(AssessmentRow.id)))
    assert results[0].input_error is not None
    assert results[0].input_error.code is CompanyInputErrorCode.MALFORMED_RULE
    assert count == 0


async def test_malformed_rule_json_is_visible(db_session: AsyncSession) -> None:
    # Given: one complete stored rule with a corrupted JSON boundary.
    program = await seed_program(db_session)
    rule = await seed_rule(db_session, program)
    profile = await seed_profile(db_session)
    _ = await seed_managed_company(db_session, profile)
    rule.expected_json = "{"
    await db_session.commit()

    # When: reverse matching parses the untrusted stored JSON.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: JSON corruption is finite and no assessment is persisted.
    count = await db_session.scalar(select(func.count(AssessmentRow.id)))
    assert results[0].input_error is not None
    assert results[0].input_error.code is CompanyInputErrorCode.MALFORMED_RULE
    assert count == 0


async def test_mixed_rule_versions_are_visible_without_assessment(
    db_session: AsyncSession,
) -> None:
    # Given: one program whose evidence-linked rules use two versions.
    program = await seed_reverse_matrix(db_session)
    rule_id = await db_session.scalar(select(func.max(EligibilityRuleRow.id)))
    _ = await db_session.execute(
        update(EligibilityRuleRow)
        .where(EligibilityRuleRow.id == rule_id)
        .values(rule_version="rules-v2")
    )
    await db_session.commit()

    # When: the mixed input is reverse-matched.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: all companies remain visible and no automatic run is persisted.
    count = await db_session.scalar(select(func.count(AssessmentRow.id)))
    errors = {
        item.input_error.code
        for item in results
        if item.input_error is not None and item.profile_name is not None
    }
    assert errors == {CompanyInputErrorCode.MIXED_RULE_VERSIONS}
    assert count == 0


async def test_missing_profile_row_is_visible_in_corrupt_legacy_state(
    db_session: AsyncSession,
) -> None:
    # Given: foreign keys are restored after constructing one legacy dangling company link.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile = await seed_profile(db_session)
    _ = await seed_managed_company(db_session, profile)
    await db_session.commit()
    _ = await db_session.execute(text("PRAGMA foreign_keys=OFF"))
    _ = await db_session.execute(
        delete(ApplicantProfileRow).where(ApplicantProfileRow.id == profile.id)
    )
    await db_session.commit()
    _ = await db_session.execute(text("PRAGMA foreign_keys=ON"))
    await db_session.commit()

    # When: reverse matching reads the legacy row with foreign keys enabled again.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: the dangling company is visible with a finite missing-profile code.
    assert results[0].input_error is not None
    assert results[0].input_error.code is CompanyInputErrorCode.PROFILE_NOT_FOUND


@pytest.mark.parametrize("notice_mode", ["missing", "malformed_source"])
async def test_invalid_current_notice_identity_is_visible_per_company(
    db_session: AsyncSession,
    notice_mode: str,
) -> None:
    # Given: a complete company and rules with missing or malformed current notice identity.
    program = await seed_program(db_session)
    _ = await seed_rule(db_session, program)
    profile = await seed_profile(db_session)
    _ = await seed_managed_company(db_session, profile)
    if notice_mode == "missing":
        _ = await db_session.execute(delete(CurrentNoticeVersionRow))
    else:
        _ = await db_session.execute(update(NoticeVersionRow).values(source="broken"))
    await db_session.commit()

    # When: reverse matching resolves official content identities.
    results = await ReverseMatchingService(db_session).reverse_match(
        program_id(program), REFERENCE_TIME
    )

    # Then: identity corruption is visible and no assessment is fabricated.
    expected = (
        CompanyInputErrorCode.MISSING_CURRENT_NOTICE
        if notice_mode == "missing"
        else CompanyInputErrorCode.MALFORMED_NOTICE_SOURCE
    )
    assert results[0].assessment is None
    assert results[0].input_error is not None
    assert results[0].input_error.code is expected


async def test_reverse_matching_rolls_back_all_assessments_on_insert_failure(
    db_session: AsyncSession,
) -> None:
    # Given: a real SQLite trigger rejects the second assessment insert.
    program = await seed_reverse_matrix(db_session)
    _ = await db_session.execute(
        text(
            """
            CREATE TRIGGER fail_second_assessment BEFORE INSERT ON assessments
            WHEN (SELECT COUNT(*) FROM assessments) >= 1
            BEGIN SELECT RAISE(ABORT, 'forced_assessment_failure'); END
            """
        )
    )
    await db_session.commit()

    # When: one invocation attempts to persist the full valid company set.
    with pytest.raises(IntegrityError):
        _ = await ReverseMatchingService(db_session).reverse_match(
            program_id(program), REFERENCE_TIME
        )

    # Then: the transaction leaves no partial automatic assessment rows.
    count = await db_session.scalar(select(func.count(AssessmentRow.id)))
    assert count == 0
