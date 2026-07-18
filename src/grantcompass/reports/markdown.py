"""Deterministic Markdown report with bounded evidence provenance."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from grantcompass.domain.documents import Evidence, EvidenceId
from grantcompass.domain.eligibility import ApplicantProfile, RuleAssessment
from grantcompass.domain.enums import ConditionStatus, FreshnessStatus, SourceName
from grantcompass.matching.forward import ChangeImpact, ProgramMatch
from grantcompass.matching.roadmap import ProgramRoadmap
from grantcompass.reports.impact_validation import (
    ReportProgramContext,
    validate_report_inputs,
)
from grantcompass.reports.markdown_helpers import (
    bounded_quote,
    escape_markdown,
    evidence_index,
    valid_source_url,
)

__all__ = ["ReportInput", "SourceFreshness", "render_markdown_report"]

_MISSING_EVIDENCE: Final = "missing_evidence"
_VERIFY_MISSING_EVIDENCE: Final = "verify_missing_evidence"
_INVALID_SOURCE_URL: Final = "invalid_source_url"
_DUPLICATE_EVIDENCE: Final = "duplicate_evidence_id"
_UNKNOWN_IMPACT_PROGRAM: Final = "unknown_impact_program_id"


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    """Caller-supplied source freshness state and timestamp."""

    source: SourceName
    status: FreshnessStatus
    collected_at: datetime


@dataclass(frozen=True, slots=True)
class ReportInput:
    """Immutable values required to render one Markdown report."""

    profile: ApplicantProfile
    matches: tuple[ProgramMatch, ...]
    roadmaps: tuple[ProgramRoadmap, ...]
    evidence: tuple[Evidence, ...]
    freshness: tuple[SourceFreshness, ...]
    generated_at: datetime
    change_impacts: tuple[ChangeImpact, ...] = ()


def render_markdown_report(report_input: ReportInput) -> str:
    """Render byte-stable UTF-8 Markdown without reading the system clock."""
    evidence_by_id, duplicate_ids = evidence_index(report_input.evidence)
    validated = validate_report_inputs(
        report_input.matches,
        report_input.roadmaps,
        report_input.change_impacts,
    )
    lines = _header(report_input)
    for program_input in sorted(validated, key=lambda value: int(value.match.program.id)):
        lines.extend(
            _program_section(
                program_input.match,
                ReportProgramContext(
                    roadmap=program_input.roadmap,
                    impact=program_input.impact,
                    evidence_by_id=evidence_by_id,
                    duplicate_ids=duplicate_ids,
                ),
            )
        )
    return "\n".join(lines).rstrip("\n") + "\n"


def _header(report_input: ReportInput) -> list[str]:
    profile_id = "none" if report_input.profile.id is None else str(report_input.profile.id)
    lines = [
        "# GrantCompass report",
        f"generated_at: {report_input.generated_at.isoformat()}",
        f"profile_name: {escape_markdown(report_input.profile.display_name)}",
        f"profile_id: {profile_id}",
        "",
        "## freshness",
    ]
    lines.extend(
        " | ".join(
            (
                f"source: {freshness.source.value}",
                f"status: {freshness.status.value}",
                f"collected_at: {freshness.collected_at.isoformat()}",
            )
        )
        for freshness in sorted(report_input.freshness, key=lambda value: value.source.value)
    )
    return lines


def _program_section(
    match: ProgramMatch,
    context: ReportProgramContext,
) -> list[str]:
    assessment = match.assessment
    reassessment_required = str(
        bool(context.impact)
        or (context.roadmap.reassessment_required if context.roadmap else False)
    ).lower()
    lines = [
        "",
        f"## program {int(match.program.id)} - {escape_markdown(match.program.title)}",
        f"organization: {escape_markdown(match.program.organization or 'none')}",
        f"deadline_state: {match.deadline.state.value}",
        f"application_end: {_date_value(match.deadline.date)}",
        f"final_status: {assessment.final_status.value}",
        f"review_status: {assessment.review_status.value}",
        f"rule_version: {escape_markdown(assessment.rule_version)}",
        f"assessed_at: {assessment.assessed_at.isoformat()}",
        f"reassessment_required: {reassessment_required}",
        "",
        "### conditions",
        "| rule_id | status | error_id | evidence_ids |",
        "| --- | --- | --- | --- |",
    ]
    for item in assessment.items:
        evidence_ids = ",".join(str(evidence_id) for evidence_id in item.evidence_ids) or "none"
        lines.append(
            "| {} | {} | {} | {} |".format(
                int(item.rule_id),
                item.status.value,
                escape_markdown(item.error_id or "none"),
                evidence_ids,
            )
        )
    lines.extend(
        _evidence_sections(
            assessment.items,
            context.evidence_by_id,
            context.duplicate_ids,
        )
    )
    lines.extend(_roadmap_sections(context.roadmap, context.impact))
    return lines


def _evidence_sections(
    items: tuple[RuleAssessment, ...],
    evidence_by_id: dict[EvidenceId, Evidence],
    duplicate_ids: frozenset[EvidenceId],
) -> list[str]:
    ids = sorted({evidence_id for item in items for evidence_id in item.evidence_ids}, key=int)
    lines = ["", "### evidence"]
    for evidence_id in ids:
        if evidence_id in duplicate_ids:
            lines.append(f"- evidence_id: {int(evidence_id)} | error: {_DUPLICATE_EVIDENCE}")
            continue
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None or evidence.id != evidence_id:
            lines.append(f"- evidence_id: {int(evidence_id)} | error: {_MISSING_EVIDENCE}")
            lines.append(
                f"- question: {_VERIFY_MISSING_EVIDENCE} | evidence_id: {int(evidence_id)}"
            )
            continue
        lines.extend(_one_evidence(evidence))
    return lines


def _one_evidence(evidence: Evidence) -> list[str]:
    source = escape_markdown(evidence.source_url)
    source_line = (
        f"[{source}]({evidence.source_url})"
        if valid_source_url(evidence.source_url)
        else f"{source} | error: {_INVALID_SOURCE_URL}"
    )
    return [
        f"- evidence_id: {int(evidence.id) if evidence.id is not None else 'none'}",
        f"  - official_url: {source_line}",
        f"  - document_id: {escape_markdown(evidence.document_id)}",
        f"  - document_hash: {escape_markdown(evidence.content_hash)}",
        f"  - block_id: {escape_markdown(evidence.block_id)}",
        f"  - page: {_optional_value(evidence.page)}",
        f"  - section: {escape_markdown(evidence.section_path or 'none')}",
        f"  - quote: {escape_markdown(bounded_quote(evidence.quote))}",
    ]


def _roadmap_sections(
    roadmap: ProgramRoadmap | None,
    impact: ChangeImpact | None,
) -> list[str]:
    if roadmap is None:
        return ["", "### roadmap", f"- error: {_UNKNOWN_IMPACT_PROGRAM}"]
    lines = ["", "### roadmap"]
    for item in roadmap.items:
        rule_id = "none" if item.rule_id is None else str(int(item.rule_id))
        lines.append(
            "- kind: {} | code: {} | rule_id: {} | status: {} | evidence_ids: {}".format(
                item.kind.value,
                item.code,
                rule_id,
                _optional_status(item.condition_status),
                ",".join(str(value) for value in item.evidence_ids) or "none",
            )
        )
    change_impact = roadmap.change_impact if roadmap.change_impact is not None else impact
    if change_impact is not None:
        changed_fields = ",".join(escape_markdown(value) for value in change_impact.changed_fields)
        impacted_assessments = ",".join(
            str(value) for value in change_impact.impacted_assessment_ids
        )
        lines.append(
            f"- change_impact: fields={changed_fields} | assessment_ids={impacted_assessments}"
        )
    return lines


def _date_value(value: date | None) -> str:
    return "none" if value is None else value.isoformat()


def _optional_value(value: int | None) -> str:
    return "none" if value is None else str(value)


def _optional_status(value: ConditionStatus | None) -> str:
    return "none" if value is None else str(value.value)
