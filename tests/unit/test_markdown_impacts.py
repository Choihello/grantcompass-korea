from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from grantcompass.domain.documents import EvidenceId
from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.domain.programs import Program
from grantcompass.matching.forward import ChangeImpact, MatchingInputError, rank_programs
from grantcompass.matching.roadmap import build_roadmap
from grantcompass.reports.markdown import render_markdown_report
from tests.unit.test_markdown_report import make_input


def _impact() -> ChangeImpact:
    return ChangeImpact(
        program_id=ProgramId(3),
        changed_fields=("application_end",),
        impacted_assessment_ids=(AssessmentId(300),),
    )


def test_report_rejects_cross_program_impact_assessment_reference() -> None:
    base = make_input()
    second_program = Program(
        id=ProgramId(4),
        canonical_key="program-4",
        title="사업 4",
        organization="기관",
        application_start=None,
        application_end=date(2026, 8, 1),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second_assessment = replace(
        base.matches[0].assessment,
        id=AssessmentId(400),
        program_id=ProgramId(4),
        items=(replace(base.matches[0].assessment.items[0], evidence_ids=(EvidenceId(40),)),),
    )
    matches = rank_programs(
        (base.matches[0].assessment, second_assessment),
        (base.matches[0].program, second_program),
        date(2026, 7, 15),
    )
    report_input = replace(
        base,
        matches=matches,
        roadmaps=tuple(build_roadmap(match) for match in matches),
        change_impacts=(
            ChangeImpact(
                program_id=ProgramId(3),
                changed_fields=("application_end",),
                impacted_assessment_ids=(AssessmentId(400),),
            ),
        ),
    )

    with pytest.raises(MatchingInputError) as error:
        _ = render_markdown_report(report_input)
    assert error.value.code == "unknown_impact_assessment_id"


def test_report_rejects_duplicate_impact_assessment_reference() -> None:
    report_input = replace(
        make_input(),
        change_impacts=(
            ChangeImpact(
                program_id=ProgramId(3),
                changed_fields=("title",),
                impacted_assessment_ids=(AssessmentId(300), AssessmentId(300)),
            ),
        ),
    )

    with pytest.raises(MatchingInputError) as error:
        _ = render_markdown_report(report_input)
    assert error.value.code == "unknown_impact_assessment_id"


def test_report_rejects_unknown_impact_program() -> None:
    report_input = replace(
        make_input(),
        change_impacts=(
            ChangeImpact(
                program_id=ProgramId(999),
                changed_fields=("title",),
                impacted_assessment_ids=(AssessmentId(300),),
            ),
        ),
    )

    with pytest.raises(MatchingInputError) as error:
        _ = render_markdown_report(report_input)
    assert error.value.code == "unknown_impact_program_id"


def test_report_rejects_inconsistent_impact_copies() -> None:
    base = make_input()
    canonical = ChangeImpact(
        program_id=ProgramId(3),
        changed_fields=("application_end",),
        impacted_assessment_ids=(AssessmentId(300),),
    )
    conflicting = replace(canonical, changed_fields=("title",))
    roadmap = build_roadmap(base.matches[0], (canonical,))
    report_input = replace(
        base,
        roadmaps=(roadmap,),
        change_impacts=(conflicting,),
    )

    with pytest.raises(MatchingInputError) as error:
        _ = render_markdown_report(report_input)
    assert error.value.code == "inconsistent_change_impact"


def test_report_rejects_report_only_impact_without_canonical_match_impact() -> None:
    report_input = replace(make_input(), change_impacts=(_impact(),))

    with pytest.raises(MatchingInputError) as error:
        _ = render_markdown_report(report_input)
    assert error.value.code == "inconsistent_change_impact"


def test_report_rejects_roadmap_only_impact_without_canonical_match_impact() -> None:
    base = make_input()
    roadmap = build_roadmap(base.matches[0], (_impact(),))
    report_input = replace(base, roadmaps=(roadmap,))

    with pytest.raises(MatchingInputError) as error:
        _ = render_markdown_report(report_input)
    assert error.value.code == "inconsistent_change_impact"


def test_report_rejects_bare_roadmap_reassessment_flag_without_canonical_impact() -> None:
    base = make_input()
    roadmap = replace(base.roadmaps[0], reassessment_required=True)
    report_input = replace(base, roadmaps=(roadmap,))

    with pytest.raises(MatchingInputError) as error:
        _ = render_markdown_report(report_input)
    assert error.value.code == "inconsistent_change_impact"
