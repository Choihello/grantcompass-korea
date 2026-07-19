"""Persistence for immutable automatic assessment runs."""

import json
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from grantcompass.domain.eligibility import AssessmentResult
from grantcompass.domain.ids import AssessmentId
from grantcompass.storage.table_eligibility import AssessmentRow, RuleAssessmentRow


async def persist_assessment(
    session: AsyncSession,
    assessment: AssessmentResult,
) -> AssessmentResult:
    """Append one assessment and all evidence-preserving condition results."""
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
                evidence_ids_json=json.dumps(
                    tuple(int(value) for value in item.evidence_ids),
                    separators=(",", ":"),
                ),
            )
        )
    return replace(assessment, id=AssessmentId(row.id))
