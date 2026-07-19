"""Persistence for immutable automatic assessment runs."""

import json
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.eligibility import AssessmentResult
from grantcompass.domain.ids import AssessmentId
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow


async def append_assessment(
    session: AsyncSession,
    assessment: AssessmentResult,
) -> AssessmentResult:
    """Flush one evidence-preserving assessment without owning the transaction."""
    row = AssessmentRow(
        program_id=int(assessment.program_id),
        profile_id=int(assessment.profile_id),
        final_status=assessment.final_status.value,
        review_status=assessment.review_status.value,
        rule_version=assessment.rule_version,
        assessed_at=assessment.assessed_at,
    )
    session.add(row)
    await session.flush()
    for item in assessment.items:
        session.add(
            RuleAssessmentRow(
                assessment_id=row.id,
                rule_id=int(item.rule_id),
                status=item.status.value,
                explanation=item.explanation,
                error_id=item.error_id,
                evidence_ids_json=json.dumps(
                    tuple(int(value) for value in item.evidence_ids),
                    separators=(",", ":"),
                ),
            )
        )
    return replace(assessment, id=AssessmentId(row.id))


async def append_assessments(
    session: AsyncSession,
    assessments: tuple[AssessmentResult, ...],
) -> tuple[AssessmentResult, ...]:
    """Flush a batch through the single row-mapping implementation."""
    return tuple([await append_assessment(session, item) for item in assessments])


async def persist_assessments(
    session: AsyncSession,
    assessments: tuple[AssessmentResult, ...],
) -> tuple[AssessmentResult, ...]:
    """Commit a caller-requested assessment batch and return durable identities."""
    persisted = await append_assessments(session, assessments)
    await session.commit()
    return persisted
