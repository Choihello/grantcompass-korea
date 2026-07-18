from datetime import UTC, date, datetime

from grantcompass.domain.documents import DocumentBlockId, DocumentId, Evidence, EvidenceId
from grantcompass.domain.eligibility import (
    ApplicantProfile,
    ApplicantProfileId,
    AssessmentResult,
    EligibilityRuleId,
    RuleAssessment,
)
from grantcompass.domain.enums import (
    ConditionStatus,
    FinalStatus,
    FreshnessStatus,
    ReviewStatus,
    SourceName,
)
from grantcompass.domain.ids import AssessmentId, ProgramId
from grantcompass.domain.programs import Program
from grantcompass.matching.forward import rank_programs
from grantcompass.matching.roadmap import build_roadmap
from grantcompass.reports.markdown import ReportInput, SourceFreshness, render_markdown_report


def make_program() -> Program:
    return Program(
        id=ProgramId(3),
        canonical_key="program-3",
        title="[공고] <지원>",
        organization="기관",
        application_start=None,
        application_end=date(2026, 7, 31),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def make_input(*, include_evidence: bool = True, invalid_url: bool = False) -> ReportInput:
    evidence = Evidence(
        id=EvidenceId(30),
        document_id=DocumentId("doc-3"),
        block_id=DocumentBlockId("p-12"),
        source_url=(
            "javascript:alert(1)" if invalid_url else "https://official.example/notice?a=1&b=2"
        ),
        page=12,
        section_path="자격 > 업력",
        quote="근거 [인용] " + ("가" * 300),
        content_hash="a" * 64,
    )
    assessment = AssessmentResult(
        id=AssessmentId(300),
        program_id=ProgramId(3),
        profile_id=ApplicantProfileId(7),
        final_status=FinalStatus.NEEDS_REVIEW,
        review_status=ReviewStatus.REVIEW_REQUIRED,
        rule_version="rules-v3",
        assessed_at=datetime(2026, 7, 1, 10, 30, tzinfo=UTC),
        items=(
            RuleAssessment(
                rule_id=EligibilityRuleId(8),
                status=ConditionStatus.UNKNOWN,
                explanation="unknown",
                evidence_ids=(EvidenceId(30), EvidenceId(31)),
                error_id="region_missing",
            ),
        ),
    )
    program = make_program()
    matches = rank_programs((assessment,), (program,), date(2026, 7, 15))
    roadmap = build_roadmap(matches[0])
    return ReportInput(
        profile=ApplicantProfile(id=ApplicantProfileId(7), display_name="기업 | <대표>"),
        matches=matches,
        roadmaps=(roadmap,),
        evidence=(evidence,) if include_evidence else (),
        freshness=(
            SourceFreshness(
                SourceName.KSTARTUP,
                FreshnessStatus.STALE,
                datetime(2026, 7, 2, tzinfo=UTC),
            ),
            SourceFreshness(
                SourceName.BIZINFO,
                FreshnessStatus.FRESH,
                datetime(2026, 7, 3, tzinfo=UTC),
            ),
        ),
        generated_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
    )


def test_report_is_deterministic_and_includes_provenance_freshness_and_review_state() -> None:
    report_input = make_input()
    first = render_markdown_report(report_input)
    second = render_markdown_report(report_input)

    assert first == second
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    assert "generated_at" in first
    assert "profile_id" in first
    assert "freshness" in first
    assert FreshnessStatus.STALE.value in first
    assert ReviewStatus.REVIEW_REQUIRED.value in first
    assert r"doc\-3" in first
    assert r"p\-12" in first
    assert r"rules\-v3" in first
    assert r"region\_missing" in first
    assert "https://official.example/notice?a=1&b=2" in first
    assert "missing_evidence" in first
    assert "verify_missing_evidence" in first
    assert "verify_unknown" in first
    assert "<대표>" not in first


def test_report_marks_missing_and_invalid_sources_without_raw_html_or_unbounded_quotes() -> None:
    report_input = make_input(invalid_url=True)
    report = render_markdown_report(report_input)

    assert "missing_evidence" in report
    assert "invalid_source_url" in report
    assert "<script>" not in report
    assert "가" * 161 not in report
