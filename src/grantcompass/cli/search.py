"""Reproducible profile search orchestration."""

from dataclasses import dataclass
from datetime import UTC, datetime

from grantcompass.cli.database import create_cli_engine
from grantcompass.cli.errors import CliError, CliErrorCode
from grantcompass.cli.freshness import FreshnessRecord, load_source_freshness
from grantcompass.cli.profiles import ProfileRepository
from grantcompass.cli.program_queries import ProgramQueryRepository, ProgramRules
from grantcompass.cli.schemas import SearchOutput
from grantcompass.cli.search_views import SearchViewData, build_search_output
from grantcompass.domain.documents import Evidence
from grantcompass.domain.eligibility import ApplicantProfile, AssessmentResult
from grantcompass.domain.ids import ProgramId
from grantcompass.matching.forward import ProgramMatch, rank_programs
from grantcompass.matching.roadmap import ProgramRoadmap, build_roadmap
from grantcompass.rules.deterministic import AssessmentInputError, DeterministicAssessmentEngine
from grantcompass.storage.assessment_runs import persist_assessments
from grantcompass.storage.db import create_session_factory

type AssessmentErrors = tuple[tuple[ProgramId, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class SearchBundle:
    """Retain serialized results and Task 10 report inputs from one search."""

    profile: ApplicantProfile
    matches: tuple[ProgramMatch, ...]
    roadmaps: tuple[ProgramRoadmap, ...]
    evidence: tuple[Evidence, ...]
    freshness: tuple[FreshnessRecord, ...]
    output: SearchOutput


async def search_programs(
    database_url: str,
    profile_selector: str,
    assessed_at: datetime,
) -> SearchBundle:
    """Assess, rank, and map every canonical program at one UTC instant."""
    if assessed_at.utcoffset() is None:
        raise CliError(CliErrorCode.INVALID_CLOCK, 4)
    reference_time = assessed_at.astimezone(UTC)
    engine = create_cli_engine(database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            profile = await ProfileRepository(session).resolve(profile_selector)
            records = await ProgramQueryRepository(session).list_program_rules()
            freshness = await load_source_freshness(session)
            assessments, errors = _assess_records(profile, records, reference_time)
            persisted = await persist_assessments(session, assessments)
            complete_program_ids = {assessment.program_id for assessment in persisted}
            programs = tuple(
                record.program for record in records if record.program.id in complete_program_ids
            )
            matches = rank_programs(persisted, programs, reference_time.date())
            roadmaps = tuple(build_roadmap(match) for match in matches)
            output = build_search_output(
                SearchViewData(
                    profile=profile,
                    matches=matches,
                    roadmaps=roadmaps,
                    records=records,
                    freshness=freshness,
                    errors=errors,
                    assessed_at=reference_time,
                )
            )
            evidence = tuple(
                item
                for record in records
                if record.program.id in complete_program_ids
                for item in record.evidence
            )
            return SearchBundle(profile, matches, roadmaps, evidence, freshness, output)
    finally:
        await engine.dispose()


def _assess_records(
    profile: ApplicantProfile,
    records: tuple[ProgramRules, ...],
    assessed_at: datetime,
) -> tuple[tuple[AssessmentResult, ...], AssessmentErrors]:
    engine = DeterministicAssessmentEngine()
    assessments: list[AssessmentResult] = []
    errors: list[tuple[ProgramId, tuple[str, ...]]] = []
    for record in records:
        if record.errors:
            errors.append((record.program.id, record.errors))
            continue
        try:
            assessments.append(engine.assess(profile, record.rules, assessed_at))
        except AssessmentInputError as error:
            errors.append((record.program.id, (f"assessment_input_{error.code}",)))
    return tuple(assessments), tuple(errors)
