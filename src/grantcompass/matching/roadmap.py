"""Condition actions and verification questions for one ranked program."""

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, assert_never

from grantcompass.domain.documents import EvidenceId
from grantcompass.domain.eligibility import AssessmentResult, EligibilityRuleId
from grantcompass.domain.enums import ConditionStatus, FinalStatus
from grantcompass.domain.ids import ProgramId
from grantcompass.matching.forward import (
    ChangeImpact,
    Deadline,
    ProgramMatch,
    validate_change_impacts,
)

__all__ = ["ProgramRoadmap", "RoadmapItem", "RoadmapItemKind", "build_roadmap"]

_VERIFY_UNKNOWN: Final = "verify_unknown"
_VERIFY_CONFLICT: Final = "verify_conflict"
_ASSESSMENT_NEEDS_REVIEW: Final = "assessment_needs_review"
_SATISFY_CONDITION: Final = "satisfy_condition"


@unique
class RoadmapItemKind(StrEnum):
    """Machine-visible type of one preparation roadmap item."""

    ACTION = "action"
    QUESTION = "question"


@dataclass(frozen=True, slots=True)
class RoadmapItem:
    """Immutable condition action or verification question."""

    program_id: ProgramId
    kind: RoadmapItemKind
    condition_status: ConditionStatus | None
    rule_id: EligibilityRuleId | None
    evidence_ids: tuple[EvidenceId, ...]
    code: str


@dataclass(frozen=True, slots=True)
class ProgramRoadmap:
    """Immutable preparation view retaining the original assessment."""

    program_id: ProgramId
    assessment: AssessmentResult
    deadline: Deadline
    items: tuple[RoadmapItem, ...]
    reassessment_required: bool
    change_impact: ChangeImpact | None = None


def build_roadmap(
    match: ProgramMatch,
    impacts: tuple[ChangeImpact, ...] | list[ChangeImpact] = (),
) -> ProgramRoadmap:
    """Build actions and questions without changing assessment eligibility."""
    impact = validate_change_impacts(match, impacts)
    items = _roadmap_items(match)
    return ProgramRoadmap(
        program_id=match.program.id,
        assessment=match.assessment,
        deadline=match.deadline,
        items=items,
        reassessment_required=impact is not None,
        change_impact=impact,
    )


def _roadmap_items(match: ProgramMatch) -> tuple[RoadmapItem, ...]:
    status = match.assessment.final_status
    match status:
        case FinalStatus.CONDITIONAL:
            return _condition_items(match)
        case FinalStatus.NEEDS_REVIEW:
            items = _condition_items(match)
            if items and any(item.kind is RoadmapItemKind.QUESTION for item in items):
                return items
            return (*items, _assessment_question(match.program.id))
        case FinalStatus.ELIGIBLE | FinalStatus.INELIGIBLE:
            return tuple(
                item for item in _condition_items(match) if item.kind is RoadmapItemKind.QUESTION
            )
        case _:
            assert_never(status)


def _condition_items(match: ProgramMatch) -> tuple[RoadmapItem, ...]:
    items: list[RoadmapItem] = []
    for assessment_item in match.assessment.items:
        item = _condition_item(
            match.program.id,
            assessment_item.status,
            assessment_item.rule_id,
            assessment_item.evidence_ids,
        )
        if item is not None:
            items.append(item)
    return tuple(items)


def _condition_item(
    program_id: ProgramId,
    status: ConditionStatus,
    rule_id: EligibilityRuleId,
    evidence_ids: tuple[EvidenceId, ...],
) -> RoadmapItem | None:
    match status:
        case ConditionStatus.CONDITIONAL:
            return RoadmapItem(
                program_id,
                RoadmapItemKind.ACTION,
                status,
                rule_id,
                evidence_ids,
                _SATISFY_CONDITION,
            )
        case ConditionStatus.UNKNOWN:
            return RoadmapItem(
                program_id,
                RoadmapItemKind.QUESTION,
                status,
                rule_id,
                evidence_ids,
                _VERIFY_UNKNOWN,
            )
        case ConditionStatus.CONFLICT:
            return RoadmapItem(
                program_id,
                RoadmapItemKind.QUESTION,
                status,
                rule_id,
                evidence_ids,
                _VERIFY_CONFLICT,
            )
        case ConditionStatus.SATISFIED | ConditionStatus.UNSATISFIED:
            return None
        case _:
            assert_never(status)


def _assessment_question(program_id: ProgramId) -> RoadmapItem:
    return RoadmapItem(
        program_id,
        RoadmapItemKind.QUESTION,
        None,
        None,
        (),
        _ASSESSMENT_NEEDS_REVIEW,
    )
