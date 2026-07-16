from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from grantcompass.documents.base import DocumentParseError
from grantcompass.documents.hwpx import HwpxParser

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "documents"


def _archive(entries: tuple[tuple[str, bytes], ...]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip", compress_type=ZIP_STORED)
        for name, content in entries:
            info = ZipInfo(name)
            info.filename = name
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return output.getvalue()


def _section(text: str = "업력 3년 이내") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="urn:fictional:section" xmlns:hp="urn:fictional:paragraph">'
        f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"
        "</hs:sec>"
    ).encode()


def _archive_with_member_name(name: str) -> bytes:
    content = _archive(((name, _section()),))
    if "\\" not in name:
        return content
    return content.replace(b"Contents/section0.xml", b"Contents\\section0.xml")


def test_hwpx_restores_paragraphs_and_table_cells() -> None:
    # Given: a fictional golden HWPX containing Korean eligibility text and a table.
    content = (FIXTURE_DIRECTORY / "eligibility-table.hwpx").read_bytes()

    # When: the document is parsed from bytes.
    document = HwpxParser().parse("doc-1", content, "공고.hwpx")

    # Then: ordered blocks retain paragraph and exact cell coordinates.
    assert document.blocks[0].block_id == "section0:p0"
    assert document.blocks[0].kind == "paragraph"
    assert any(block.table_ref == "table0:r1:c2:rs1:cs1" for block in document.blocks)
    assert any("업력 3년 이내" in block.text for block in document.blocks)


def test_hwpx_preserves_merged_cell_origin_and_span() -> None:
    # Given: a golden HWPX with cells merged in both dimensions.
    content = (FIXTURE_DIRECTORY / "merged-cells.hwpx").read_bytes()

    # When: the document is parsed.
    document = HwpxParser().parse("doc-merged", content, "병합표.HWPX")

    # Then: the cell origin and spans are encoded without inventing duplicate cells.
    references = tuple(block.table_ref for block in document.blocks if block.table_ref)
    assert "table0:r0:c0:rs2:cs3" in references
    assert len(references) == len(set(references))


def test_hwpx_orders_numeric_sections_and_hashes_original_bytes() -> None:
    # Given: section 10 appears before section 2 in ZIP entry order.
    content = _archive(
        (
            ("Contents/section10.xml", _section("열 번째")),
            ("Contents/section2.xml", _section("두 번째")),
        )
    )

    # When: the archive is parsed.
    document = HwpxParser().parse("doc-order", content, "order.hwpx")

    # Then: numeric section order and the SHA-256 of exact bytes are stable.
    assert tuple(block.text for block in document.blocks) == ("두 번째", "열 번째")
    assert document.content_hash == sha256(content).hexdigest()
    assert tuple(block.ordinal for block in document.blocks) == (0, 1)


@pytest.mark.parametrize(
    ("entry_name", "code"),
    [
        ("../outside.xml", "unsafe_archive_path"),
        ("/absolute.xml", "unsafe_archive_path"),
        ("C:/drive.xml", "unsafe_archive_path"),
        (r"Contents\section0.xml", "unsafe_archive_path"),
    ],
)
def test_hwpx_rejects_unsafe_archive_paths(entry_name: str, code: str) -> None:
    # Given: an otherwise valid HWPX containing an unsafe member path.
    content = _archive_with_member_name(entry_name)

    # When: archive validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("doc-path", content, "bad.hwpx")

    # Then: a stable path-specific failure is returned.
    assert caught.value.code == code


def test_hwpx_rejects_duplicate_critical_entries() -> None:
    # Given: two names resolve to the same numeric section identity.
    content = _archive(
        (("Contents/section0.xml", _section()), ("Contents/section00.xml", _section()))
    )

    # When: archive validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("doc-duplicate", content, "bad.hwpx")

    # Then: ambiguous critical content is rejected.
    assert caught.value.code == "invalid_archive"


def test_hwpx_rejects_encrypted_and_special_entries() -> None:
    # Given: a ZIP member marked as a Unix symlink.
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", b"application/hwp+zip", compress_type=ZIP_STORED)
        link = ZipInfo("Contents/section0.xml")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, _section())

    # When: archive validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("doc-special", output.getvalue(), "bad.hwpx")

    # Then: special archive members are rejected.
    assert caught.value.code == "invalid_archive"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"not-a-zip", "invalid_archive"),
        (_archive(()), "missing_content"),
        (_archive((("Contents/section0.xml", b"<broken>"),)), "invalid_xml"),
        (
            _archive((("Contents/section0.xml", b'<!DOCTYPE x [<!ENTITY e "boom">]><x>&e;</x>'),)),
            "invalid_xml",
        ),
    ],
)
def test_hwpx_returns_stable_codes_for_invalid_content(
    payload: bytes,
    expected_code: str,
) -> None:
    # Given: invalid or incomplete HWPX bytes.

    # When: parsing is attempted.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("doc-invalid", payload, "invalid.hwpx")

    # Then: callers receive a machine-readable stable failure code.
    assert caught.value.code == expected_code
    assert expected_code in str(caught.value)


def test_hwpx_rejects_entry_and_expansion_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: limits lower than an otherwise valid archive requires.
    content = _archive((("Contents/section0.xml", _section("가" * 200)),))
    monkeypatch.setattr("grantcompass.documents.archive.MAX_ENTRY_SIZE", 32)

    # When: archive validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("doc-large", content, "large.hwpx")

    # Then: oversized expansion is rejected before XML parsing.
    assert caught.value.code == "archive_too_large"


def test_hwpx_models_are_frozen() -> None:
    # Given: a parsed immutable document.
    content = _archive((("Contents/section0.xml", _section()),))
    document = HwpxParser().parse("doc-frozen", content, "frozen.hwpx")

    # When: a caller tries to mutate one block.
    with pytest.raises(FrozenInstanceError):
        document.blocks[0].__setattr__("text", "변조")

    # Then: document evidence coordinates remain immutable.


def test_hwpx_rejects_wrong_filename_and_mimetype() -> None:
    # Given: valid archive bytes but unsupported boundary metadata.
    content = _archive((("Contents/section0.xml", _section()),))

    # When: filename validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("doc-name", content, "notice.zip")

    # Then: the boundary reports an invalid document type.
    assert caught.value.code == "unsupported_document"
