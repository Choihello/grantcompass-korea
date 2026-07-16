from collections.abc import Callable
from dataclasses import replace

import pytest

from grantcompass.domain.documents import (
    DocumentBlock,
    DocumentBlockId,
    DocumentId,
    Evidence,
    ParsedDocument,
)
from grantcompass.domain.enums import ReviewStatus, RuleKind
from grantcompass.rules.candidates import (
    EvidenceIntegrityError,
    EvidenceIntegrityErrorCode,
    RegexRuleCandidateProvider,
    validate_candidates,
)


@pytest.fixture
def parsed_document() -> ParsedDocument:
    return ParsedDocument(
        document_id=DocumentId("notice/가상 1"),
        parser_name="test",
        parser_version="1.0.0",
        content_hash="a" * 64,
        blocks=(
            DocumentBlock(
                block_id=DocumentBlockId("section0:p12"),
                ordinal=0,
                kind="paragraph",
                text="업력 3년 이내인 서울특별시 소재 기업이며 도박업 제외",
                page=12,
                section_path="신청자격 > 기본요건",
            ),
            DocumentBlock(
                block_id=DocumentBlockId("section0:p13"),
                ordinal=1,
                kind="paragraph",
                text="대표자 만 39세 이하",
                page=13,
                section_path="신청자격 > 대표자",
            ),
        ),
    )


def test_candidate_keeps_exact_source_block(parsed_document: ParsedDocument) -> None:
    # Given: a parsed block containing a deterministic business-age condition.

    # When: rule candidates are extracted.
    rules = RegexRuleCandidateProvider().extract(parsed_document)

    # Then: the normalized rule keeps the exact parser coordinates.
    age_rule = next(rule for rule in rules if rule.kind is RuleKind.BUSINESS_AGE_MONTHS)
    assert age_rule.operator == "lte"
    assert age_rule.expected_value == 36
    assert age_rule.review_status is ReviewStatus.AUTOMATIC
    assert age_rule.evidence[0].block_id == DocumentBlockId("section0:p12")
    assert age_rule.evidence[0].quote == "업력 3년 이내"


def test_candidate_extracts_only_supported_rule_families(
    parsed_document: ParsedDocument,
) -> None:
    # Given: source blocks containing every deterministic rule family.

    # When: candidates are extracted in parser and source order.
    rules = RegexRuleCandidateProvider().extract(parsed_document)

    # Then: only the four supported normalized families are emitted.
    assert tuple((rule.kind, rule.operator, rule.expected_value) for rule in rules) == (
        (RuleKind.BUSINESS_AGE_MONTHS, "lte", 36),
        (RuleKind.REGION, "in", "서울특별시"),
        (RuleKind.INDUSTRY, "not_in", "도박업"),
        (RuleKind.REPRESENTATIVE_AGE, "lte", 39),
    )


def test_candidate_ignores_non_condition_business_age_text(
    parsed_document: ParsedDocument,
) -> None:
    # Given: a block mentioning business age without a supported comparison.
    near_miss = replace(
        parsed_document,
        blocks=(
            replace(
                parsed_document.blocks[0],
                text="업력 제한은 별도 공고 예정",
            ),
        ),
    )

    # When: deterministic extraction runs.
    rules = RegexRuleCandidateProvider().extract(near_miss)

    # Then: no speculative natural-language rule is created.
    assert rules == ()


def test_candidate_percent_encodes_document_id_in_evidence_uri(
    parsed_document: ParsedDocument,
) -> None:
    # Given: a document identifier containing a slash, space, and non-ASCII text.

    # When: one evidence-linked candidate is extracted.
    evidence = RegexRuleCandidateProvider().extract(parsed_document)[0].evidence[0]

    # Then: the stable internal URI cannot be structurally corrupted by the identifier.
    assert evidence.source_url == "grantcompass://documents/notice%2F%EA%B0%80%EC%83%81%201"


def test_candidate_without_resolvable_block_is_rejected(
    parsed_document: ParsedDocument,
) -> None:
    # Given: a candidate whose evidence block was replaced with an unknown identifier.
    valid = RegexRuleCandidateProvider().extract(parsed_document)[0]
    invalid = replace(
        valid,
        evidence=(replace(valid.evidence[0], block_id=DocumentBlockId("missing")),),
    )

    # When: evidence integrity is checked.
    with pytest.raises(EvidenceIntegrityError) as caught:
        _ = validate_candidates((invalid,), parsed_document)

    # Then: callers receive the finite unknown-block code.
    assert caught.value.code == "unknown_block_id"


def _wrong_document_id(evidence: Evidence) -> Evidence:
    return replace(evidence, document_id=DocumentId("other"))


def _wrong_content_hash(evidence: Evidence) -> Evidence:
    return replace(evidence, content_hash="b" * 64)


def _wrong_source_url(evidence: Evidence) -> Evidence:
    return replace(evidence, source_url="grantcompass://documents/other")


def _wrong_page(evidence: Evidence) -> Evidence:
    return replace(evidence, page=99)


def _wrong_section_path(evidence: Evidence) -> Evidence:
    return replace(evidence, section_path="other")


def _wrong_quote(evidence: Evidence) -> Evidence:
    return replace(evidence, quote="근거 블록에 없는 문구")


INTEGRITY_CASES: tuple[
    tuple[Callable[[Evidence], Evidence], EvidenceIntegrityErrorCode],
    ...,
] = (
    (_wrong_document_id, "document_id_mismatch"),
    (_wrong_content_hash, "content_hash_mismatch"),
    (_wrong_source_url, "source_url_mismatch"),
    (_wrong_page, "page_mismatch"),
    (_wrong_section_path, "section_path_mismatch"),
    (_wrong_quote, "quote_not_in_block"),
)


@pytest.mark.parametrize(("mutation", "expected_code"), INTEGRITY_CASES)
def test_candidate_with_mismatched_evidence_is_rejected(
    parsed_document: ParsedDocument,
    mutation: Callable[[Evidence], Evidence],
    expected_code: EvidenceIntegrityErrorCode,
) -> None:
    # Given: a candidate with one corrupted evidence coordinate.
    valid = RegexRuleCandidateProvider().extract(parsed_document)[0]
    invalid = replace(valid, evidence=(mutation(valid.evidence[0]),))

    # When: evidence integrity is checked.
    with pytest.raises(EvidenceIntegrityError) as caught:
        _ = validate_candidates((invalid,), parsed_document)

    # Then: the exact finite mismatch code is reported.
    assert caught.value.code == expected_code


def test_candidate_without_evidence_is_rejected(
    parsed_document: ParsedDocument,
) -> None:
    # Given: a deterministic candidate stripped of all evidence.
    valid = RegexRuleCandidateProvider().extract(parsed_document)[0]
    invalid = replace(valid, evidence=())

    # When: evidence integrity is checked.
    with pytest.raises(EvidenceIntegrityError) as caught:
        _ = validate_candidates((invalid,), parsed_document)

    # Then: callers receive the finite missing-evidence code.
    assert caught.value.code == "missing_evidence"
