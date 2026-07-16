from dataclasses import replace

import pytest

from grantcompass.domain.documents import (
    DocumentBlock,
    DocumentBlockId,
    DocumentId,
    ParsedDocument,
)
from grantcompass.domain.eligibility import ExpectedValue
from grantcompass.domain.enums import RuleKind
from grantcompass.rules.candidates import (
    EvidenceIntegrityError,
    RegexRuleCandidateProvider,
    validate_candidates,
)

type NormalizedRule = tuple[RuleKind, str, ExpectedValue]


def _document(text: str) -> ParsedDocument:
    return ParsedDocument(
        document_id=DocumentId("review-fix"),
        parser_name="test",
        parser_version="1.0.0",
        content_hash="c" * 64,
        blocks=(
            DocumentBlock(
                block_id=DocumentBlockId("section0:p0"),
                ordinal=0,
                kind="paragraph",
                text=text,
                page=None,
                section_path="Contents/section0.xml",
            ),
        ),
    )


ADVERSARIAL_GOLDENS: tuple[tuple[str, tuple[NormalizedRule, ...]], ...] = (
    (
        "서울특별시 소재 기업은 제외",
        ((RuleKind.REGION, "not_in", "서울특별시"),),
    ),
    (
        "서울특별시 소재 기업 은, 제외.",
        ((RuleKind.REGION, "not_in", "서울특별시"),),
    ),
    (
        "서울특별시 소재 기업을 제외합니다.",
        ((RuleKind.REGION, "not_in", "서울특별시"),),
    ),
    (
        "서울특별시 소재 기업 를 제외",
        ((RuleKind.REGION, "not_in", "서울특별시"),),
    ),
    ("기업은 제외", ()),
    ("창업 제외", ()),
    ("업력 3년 이내 지원 불가", ()),
    ("업력 3년 이내 제외", ()),
    ("대표자 만 39세 이하 지원 불가", ()),
    ("업력 3년 이상 7년 이내", ()),
    ("업력 3년 6개월 이내", ()),
    (
        "업력 3년 이내 지원 불가. 업력 5년 이상",
        ((RuleKind.BUSINESS_AGE_MONTHS, "gte", 60),),
    ),
    (
        "업력은: 3년 이내",
        ((RuleKind.BUSINESS_AGE_MONTHS, "lte", 36),),
    ),
)


@pytest.mark.parametrize(("text", "expected"), ADVERSARIAL_GOLDENS)
def test_candidate_matches_independently_reviewed_adversarial_golden(
    text: str,
    expected: tuple[NormalizedRule, ...],
) -> None:
    # Given: one independently reviewed source expression and normalized oracle.
    document = _document(text)

    # When: deterministic extraction runs.
    rules = RegexRuleCandidateProvider().extract(document)

    # Then: only the frozen machine fields match the reviewed oracle.
    assert tuple((rule.kind, rule.operator, rule.expected_value) for rule in rules) == expected


def test_candidate_rejects_duplicate_document_block_identity() -> None:
    # Given: parser output containing two blocks with the same address.
    document = _document("업력 3년 이내")
    duplicate = replace(document.blocks[0], ordinal=1, text="대표자 만 39세 이하")
    invalid = replace(document, blocks=(document.blocks[0], duplicate))

    # When: evidence integrity is checked.
    with pytest.raises(EvidenceIntegrityError) as caught:
        _ = validate_candidates((), invalid)

    # Then: the duplicate block identity is explicit.
    assert caught.value.code == "duplicate_block_id"


def test_candidate_rejects_duplicate_evidence_identity_within_rule() -> None:
    # Given: one rule repeats the same evidence coordinates.
    document = _document("업력 3년 이내")
    valid = RegexRuleCandidateProvider().extract(document)[0]
    invalid = replace(valid, evidence=(valid.evidence[0], valid.evidence[0]))

    # When: evidence integrity is checked.
    with pytest.raises(EvidenceIntegrityError) as caught:
        _ = validate_candidates((invalid,), document)

    # Then: the duplicate evidence identity is explicit.
    assert caught.value.code == "duplicate_evidence"
