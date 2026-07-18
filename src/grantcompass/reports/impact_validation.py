"""Canonical change-impact validation for report inputs."""

from dataclasses import dataclass, replace
from typing import Final

from grantcompass.domain.documents import Evidence, EvidenceId
from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.matching.forward import (
    ChangeImpact,
    MatchingInputError,
    ProgramMatch,
    validate_change_impacts,
)
from grantcompass.matching.roadmap import ProgramRoadmap

_DUPLICATE_IMPACT = "duplicate_change_impact"
_DUPLICATE_PROGRAM: Final = "duplicate_program_id"
_DUPLICATE_ROADMAP = "duplicate_roadmap_program_id"
_UNKNOWN_ROADMAP = "unknown_roadmap_program_id"
_UNKNOWN_PROGRAM = "unknown_impact_program_id"
_UNKNOWN_ASSESSMENT = "unknown_impact_assessment_id"
_INCONSISTENT_IMPACT = "inconsistent_change_impact"


@dataclass(frozen=True, slots=True)
class ValidatedProgramInput:
    """One report program with its validated canonical impact."""

    match: ProgramMatch
    roadmap: ProgramRoadmap | None
    impact: ChangeImpact | None


@dataclass(frozen=True, slots=True)
class ReportProgramContext:
    """Validated context used to render one report program."""

    roadmap: ProgramRoadmap | None
    impact: ChangeImpact | None
    evidence_by_id: dict[EvidenceId, Evidence]
    duplicate_ids: frozenset[EvidenceId]


def validate_report_inputs(
    matches: tuple[ProgramMatch, ...],
    roadmaps: tuple[ProgramRoadmap, ...],
    impacts: tuple[ChangeImpact, ...],
) -> tuple[ValidatedProgramInput, ...]:
    """Validate every report impact against its exact program assessment."""
    match_by_program: dict[ProgramId, ProgramMatch] = {}
    for match in matches:
        if match.program.id in match_by_program:
            raise MatchingInputError(_DUPLICATE_PROGRAM)
        match_by_program[match.program.id] = match
    roadmap_by_program = _index_roadmaps(roadmaps, match_by_program)
    impact_by_program = _index_impacts(impacts, match_by_program)
    _validate_global_assessment_references(impacts)

    validated: list[ValidatedProgramInput] = []
    for match in matches:
        roadmap = roadmap_by_program.get(match.program.id)
        impact = _canonical_impact(
            match,
            roadmap,
            impact_by_program.get(match.program.id),
        )
        validated.append(ValidatedProgramInput(match, roadmap, impact))
    return tuple(validated)


def _index_roadmaps(
    roadmaps: tuple[ProgramRoadmap, ...],
    match_by_program: dict[ProgramId, ProgramMatch],
) -> dict[ProgramId, ProgramRoadmap]:
    indexed: dict[ProgramId, ProgramRoadmap] = {}
    for roadmap in roadmaps:
        if roadmap.program_id in indexed:
            raise MatchingInputError(_DUPLICATE_ROADMAP)
        if roadmap.program_id not in match_by_program:
            raise MatchingInputError(_UNKNOWN_ROADMAP)
        indexed[roadmap.program_id] = roadmap
    return indexed


def _index_impacts(
    impacts: tuple[ChangeImpact, ...],
    match_by_program: dict[ProgramId, ProgramMatch],
) -> dict[ProgramId, ChangeImpact]:
    indexed: dict[ProgramId, ChangeImpact] = {}
    for impact in impacts:
        if impact.program_id in indexed:
            raise MatchingInputError(_DUPLICATE_IMPACT)
        if impact.program_id not in match_by_program:
            raise MatchingInputError(_UNKNOWN_PROGRAM)
        indexed[impact.program_id] = impact
    return indexed


def _validate_global_assessment_references(impacts: tuple[ChangeImpact, ...]) -> None:
    seen: set[AssessmentId] = set()
    for impact in impacts:
        for assessment_id in impact.impacted_assessment_ids:
            if assessment_id in seen:
                raise MatchingInputError(_UNKNOWN_ASSESSMENT)
            seen.add(assessment_id)


def _canonical_impact(
    match: ProgramMatch,
    roadmap: ProgramRoadmap | None,
    report_impact: ChangeImpact | None,
) -> ChangeImpact | None:
    roadmap_impact = None if roadmap is None else roadmap.change_impact
    canonical = validate_change_impacts(match, ())
    compatibility_match = replace(match, change_impact=None)
    if roadmap_impact is not None:
        _ = validate_change_impacts(compatibility_match, (roadmap_impact,))
    if report_impact is not None:
        _ = validate_change_impacts(compatibility_match, (report_impact,))
    if roadmap_impact is not None and roadmap_impact != canonical:
        raise MatchingInputError(_INCONSISTENT_IMPACT)
    if report_impact is not None and report_impact != canonical:
        raise MatchingInputError(_INCONSISTENT_IMPACT)
    if roadmap is not None and roadmap.reassessment_required != (canonical is not None):
        raise MatchingInputError(_INCONSISTENT_IMPACT)
    return canonical
