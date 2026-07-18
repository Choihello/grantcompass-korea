"""Deterministic search presentation mapping."""

from dataclasses import dataclass
from datetime import date, datetime

from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.cli.freshness import FreshnessRecord
from grantcompass.cli.program_queries import ProgramRules
from grantcompass.cli.schemas import (
    ConditionOutput,
    DeadlineOutput,
    EvidenceOutput,
    ProfileIdentityOutput,
    RoadmapOutput,
    SearchOutput,
    SearchProgramOutput,
    SourceFreshnessOutput,
)
from grantcompass.domain.documents import Evidence
from grantcompass.domain.eligibility import ApplicantProfile
from grantcompass.domain.enums import ReviewStatus
from grantcompass.domain.ids import ProgramId
from grantcompass.matching.forward import DeadlineState, ProgramMatch
from grantcompass.matching.roadmap import ProgramRoadmap


@dataclass(frozen=True, slots=True)
class SearchViewData:
    """Hold typed domain values needed for deterministic search serialization."""

    profile: ApplicantProfile
    matches: tuple[ProgramMatch, ...]
    roadmaps: tuple[ProgramRoadmap, ...]
    records: tuple[ProgramRules, ...]
    freshness: tuple[FreshnessRecord, ...]
    errors: tuple[tuple[ProgramId, tuple[str, ...]], ...]
    assessed_at: datetime


def build_search_output(data: SearchViewData) -> SearchOutput:
    """Map complete and invalid programs into one stable public response."""
    profile = data.profile
    if profile.id is None:
        raise CliError(CliErrorCode.MISSING_PROFILE_ID, 4)
    records_by_id = {record.program.id: record for record in data.records}
    roadmaps_by_id = {roadmap.program_id: roadmap for roadmap in data.roadmaps}
    errors_by_program = dict(data.errors)
    complete = tuple(
        _complete_result(match, roadmaps_by_id[match.program.id], records_by_id[match.program.id])
        for match in data.matches
    )
    invalid = tuple(
        _invalid_result(
            records_by_id[program_id],
            errors_by_program[program_id],
            data.assessed_at.date(),
        )
        for program_id in sorted(errors_by_program, key=int)
    )
    return SearchOutput(
        profile=ProfileIdentityOutput(id=int(profile.id), display_name=profile.display_name),
        assessed_at=data.assessed_at,
        source_freshness=tuple(
            SourceFreshnessOutput(
                source=item.source,
                status=item.status,
                observed_at=item.observed_at,
                last_successful_at=item.last_successful_at,
                error_code=item.error_code,
            )
            for item in data.freshness
        ),
        results=(*complete, *invalid),
    )


def _complete_result(
    match: ProgramMatch,
    roadmap: ProgramRoadmap,
    record: ProgramRules,
) -> SearchProgramOutput:
    return SearchProgramOutput(
        program_id=int(match.program.id),
        title=match.program.title,
        organization=match.program.organization,
        final_status=match.assessment.final_status,
        review_status=match.assessment.review_status,
        deadline=DeadlineOutput(
            state=match.deadline.state,
            date=match.deadline.date,
            days_remaining=match.deadline.days_remaining,
        ),
        conditions=tuple(
            ConditionOutput(
                rule_id=int(item.rule_id),
                status=item.status,
                error_id=item.error_id,
                evidence_ids=tuple(int(value) for value in item.evidence_ids),
            )
            for item in match.assessment.items
        ),
        evidence=tuple(_evidence_output(item) for item in record.evidence),
        roadmap=tuple(
            RoadmapOutput(
                kind=item.kind,
                code=item.code,
                condition_status=item.condition_status,
                rule_id=None if item.rule_id is None else int(item.rule_id),
                evidence_ids=tuple(int(value) for value in item.evidence_ids),
            )
            for item in roadmap.items
        ),
        input_errors=(),
    )


def _invalid_result(
    record: ProgramRules,
    errors: tuple[str, ...],
    today: date,
) -> SearchProgramOutput:
    deadline = record.program.application_end
    if deadline is None:
        deadline_output = DeadlineOutput(
            state=DeadlineState.MISSING, date=None, days_remaining=None
        )
    else:
        remaining = (deadline - today).days
        state = DeadlineState.EXPIRED if remaining < 0 else DeadlineState.OPEN
        deadline_output = DeadlineOutput(state=state, date=deadline, days_remaining=remaining)
    return SearchProgramOutput(
        program_id=int(record.program.id),
        title=record.program.title,
        organization=record.program.organization,
        final_status=None,
        review_status=ReviewStatus.REVIEW_REQUIRED,
        deadline=deadline_output,
        conditions=(),
        evidence=tuple(_evidence_output(item) for item in record.evidence),
        roadmap=(),
        input_errors=errors,
    )


def _evidence_output(evidence: Evidence) -> EvidenceOutput:
    if evidence.id is None:
        raise CliError(CliErrorCode.MISSING_EVIDENCE_ID, 4)
    return EvidenceOutput(
        id=int(evidence.id),
        source_url=evidence.source_url,
        document_id=str(evidence.document_id),
        block_id=str(evidence.block_id),
        page=evidence.page,
        section_path=evidence.section_path,
        content_hash=evidence.content_hash,
    )
