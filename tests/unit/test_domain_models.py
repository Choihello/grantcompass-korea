from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from pydantic import HttpUrl, ValidationError

from grantcompass.domain.documents import DocumentBlockId, DocumentId, Evidence
from grantcompass.domain.eligibility import ApplicantProfile
from grantcompass.domain.enums import SourceName
from grantcompass.domain.json_types import JsonObject, freeze_json_object
from grantcompass.domain.programs import Program, ProgramId, RawNotice


def test_raw_payload_is_excluded_from_content_hash() -> None:
    # Given: notices with the same published content but different collection metadata.
    first = RawNotice(
        source=SourceName.BIZINFO,
        source_notice_id="PBLN-1",
        title="수출 지원",
        detail_url=HttpUrl("https://example.invalid/PBLN-1"),
        raw_payload=freeze_json_object({"request_page": 1}),
    )
    second = first.model_copy(update={"raw_payload": {"request_page": 2}})

    # When: both notices are content-addressed.
    hashes = (first.content_hash(), second.content_hash())

    # Then: source transport metadata does not create a notice version.
    assert hashes[0] == hashes[1]


def test_published_change_changes_content_hash() -> None:
    # Given: a notice and a changed published summary.
    first = RawNotice(
        source=SourceName.BIZINFO,
        source_notice_id="PBLN-1",
        title="수출 지원",
        summary="원본",
        detail_url=HttpUrl("https://example.invalid/PBLN-1"),
        raw_payload=freeze_json_object({}),
    )
    second = first.model_copy(update={"summary": "변경"})

    # When: both notice snapshots are content-addressed.
    hashes = (first.content_hash(), second.content_hash())

    # Then: the published change produces a distinct version identity.
    assert hashes[0] != hashes[1]


def test_raw_notice_rejects_mutation() -> None:
    # Given: one parsed boundary model.
    notice = RawNotice(
        source=SourceName.MANUAL,
        source_notice_id="manual-1",
        title="기관 사업",
        detail_url=HttpUrl("https://example.invalid/manual-1"),
        raw_payload=freeze_json_object({}),
    )

    # When: a caller tries to mutate published content.
    with pytest.raises(ValidationError):
        notice.__setattr__("title", "변조")

    # Then: Pydantic rejects the mutation at the boundary.


def test_boundary_json_is_deeply_immutable_and_serializable() -> None:
    # Given: nested JSON supplied to both boundary models.
    raw_payload: JsonObject = {"nested": {"page": 1}, "tags": ["startup"]}
    notice = RawNotice(
        source=SourceName.MANUAL,
        source_notice_id="manual-json-1",
        title="기관 사업",
        detail_url=HttpUrl("https://example.invalid/manual-json-1"),
        raw_payload=freeze_json_object(raw_payload),
    )
    profile = ApplicantProfile(
        display_name="테스트 기업",
        performance=freeze_json_object({"revenue": {"2025": 100}}),
        benefit_history=(freeze_json_object({"programs": ["seed"]}),),
    )

    # When: the parsed JSON containers are hashed and serialized.
    hashes = (
        hash(notice.raw_payload),
        hash(profile.performance),
        hash(profile.benefit_history),
    )
    serialized = notice.model_dump_json()

    # Then: every nested value is immutable while the boundary stays JSON-compatible.
    assert all(isinstance(value, int) for value in hashes)
    assert '"nested":{"page":1}' in serialized


def test_program_is_frozen_internal_outcome() -> None:
    # Given: one canonical program outcome.
    recorded_at = datetime(2026, 7, 15, tzinfo=UTC)
    program = Program(
        id=ProgramId(1),
        canonical_key="지원|기관|2026-07-31",
        title="지원",
        organization="기관",
        application_start=None,
        application_end=None,
        created_at=recorded_at,
        updated_at=recorded_at,
        reference_date=recorded_at.date(),
        reference_date_source="announcement_date",
    )

    # When: a caller tries to replace its title.
    with pytest.raises(FrozenInstanceError):
        program.__setattr__("title", "변조")

    # Then: the internal result remains immutable.


def test_evidence_requires_resolvable_provenance() -> None:
    # Given: all required document provenance values.

    # When: an evidence value is constructed.
    evidence = Evidence(
        document_id=DocumentId("document-1"),
        block_id=DocumentBlockId("section0:p12"),
        page=12,
        section_path="신청자격 > 업력",
        quote="창업 후 3년 이내",
        content_hash="a" * 64,
        source_url="https://example.invalid/PBLN-1",
    )

    # Then: every provenance coordinate remains available.
    assert evidence.document_id == DocumentId("document-1")
    assert evidence.block_id == DocumentBlockId("section0:p12")
    assert evidence.page == 12
    assert evidence.section_path == "신청자격 > 업력"
    assert evidence.quote == "창업 후 3년 이내"
    assert evidence.content_hash == "a" * 64
