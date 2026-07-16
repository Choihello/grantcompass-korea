from __future__ import annotations

from dataclasses import fields
from io import BytesIO
from typing import TYPE_CHECKING, get_args, get_type_hints
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from grantcompass.documents import archive as archive_limits
from grantcompass.documents.base import DocumentParseError, ParseErrorCode
from grantcompass.documents.hwpx import HwpxParser
from grantcompass.domain.documents import DocumentBlock

if TYPE_CHECKING:
    from collections.abc import Callable


def build_archive(entries: tuple[tuple[str, bytes], ...]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        _ = archive.writestr("mimetype", b"application/hwp+zip", compress_type=ZIP_STORED)
        for name, content in entries:
            info = ZipInfo(name)
            info.filename = name
            info.compress_type = ZIP_DEFLATED
            _ = archive.writestr(info, content)
    return output.getvalue()


def section(body: str, encoding: str = "utf-8") -> bytes:
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        '<s:sec xmlns:s="urn:fictional:s" xmlns:p="urn:fictional:p">'
        f"{body}</s:sec>"
    )
    return xml.encode(encoding)


def mutate_flags(content: bytes) -> bytes:
    changed = bytearray(content)
    local = changed.find(b"PK\x03\x04", changed.find(b"PK\x03\x04") + 4)
    central = changed.find(b"PK\x01\x02", changed.find(b"PK\x01\x02") + 4)
    changed[local + 6] |= 1
    changed[central + 8] |= 1
    return bytes(changed)


def mutate_local_name(content: bytes) -> bytes:
    changed = bytearray(content)
    first = changed.find(b"Contents/section0.xml")
    changed[first] = ord("c")
    return bytes(changed)


def corrupt_section_data(content: bytes) -> bytes:
    changed = bytearray(content)
    local = changed.find(b"PK\x03\x04", changed.find(b"PK\x03\x04") + 4)
    name_size = int.from_bytes(changed[local + 26 : local + 28], "little")
    extra_size = int.from_bytes(changed[local + 28 : local + 30], "little")
    data = local + 30 + name_size + extra_size
    changed[data + 2] ^= 0xFF
    return bytes(changed)


def truncate_central_directory(content: bytes) -> bytes:
    end = content.rfind(b"PK\x05\x06")
    return content[: end - 3] + content[end:]


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_hwpx_rejects_encoded_dtd_and_entity_expansion(encoding: str) -> None:
    # Given: an encoded XML document containing an internal entity declaration.
    xml = f'<?xml version="1.0" encoding="{encoding}"?><!DoCtYpE x [<!EnTiTy e "boom">]><x>&e;</x>'
    content = build_archive((("Contents/section0.xml", xml.encode(encoding)),))

    # When: the hardened XML boundary parses it.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("encoded-dtd", content, "encoded.hwpx")

    # Then: declaration encoding cannot bypass the stable rejection.
    assert caught.value.code == "invalid_xml"


def test_hwpx_preserves_split_runs_inline_text_and_authored_whitespace() -> None:
    # Given: styled runs and an inline child split one authored Korean phrase.
    body = "<p:p><p:run><p:t>업</p:t></p:run><p:run><p:t>력<q/> 3년</p:t></p:run></p:p>"
    content = build_archive((("Contents/section0.xml", section(body)),))

    # When: the paragraph is reconstructed.
    parsed = HwpxParser().parse("split-run", content, "split.hwpx")

    # Then: no synthetic separator is inserted and authored spaces remain exact.
    assert parsed.blocks[0].text == "업력 3년"


@pytest.mark.parametrize(
    "name",
    [
        "%2e%2e%2foutside.xml",
        "%252e%252e%252foutside.xml",
        "Contents%2f..%2foutside.xml",
        "Contents%5c..%5coutside.xml",
        "\uff0e\uff0e\uff0foutside.xml",
    ],
)
def test_hwpx_rejects_encoded_and_compatibility_traversal(name: str) -> None:
    # Given: a member whose normalized or decoded interpretation escapes the archive root.
    content = build_archive(((name, b"unsafe"), ("Contents/section0.xml", section("<p:p/>"))))

    # When: canonical path validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("encoded-path", content, "path.hwpx")

    # Then: every traversal representation uses the path-specific stable code.
    assert caught.value.code == "unsafe_archive_path"


@pytest.mark.parametrize("alias", ["contents/SECTION0.XML", "Contents%2Fsection0.xml"])
def test_hwpx_rejects_case_and_percent_aliases_of_critical_sections(alias: str) -> None:
    # Given: one exact section and one canonically equivalent archive member.
    content = build_archive((("Contents/section0.xml", section("<p:p/>")), (alias, b"alias")))

    # When: canonical duplicate validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("aliased", content, "aliased.hwpx")

    # Then: critical aliases cannot shadow exact section content.
    assert caught.value.code == "invalid_archive"


def test_document_parse_error_and_block_kind_are_finite_immutable_contracts() -> None:
    # Given: one public parse error and the published type annotations.
    error = DocumentParseError("invalid_xml", "fictional failure")

    # When: a caller attempts to mutate public error state.
    mutate_attribute = setattr
    with pytest.raises(AttributeError):
        mutate_attribute(error, "code", "invalid_archive")

    # Then: codes and block kinds are finite machine-readable sets.
    assert set(get_args(ParseErrorCode)) == {
        "archive_too_large",
        "invalid_archive",
        "invalid_document_id",
        "invalid_xml",
        "missing_content",
        "unsafe_archive_path",
        "unsupported_document",
    }
    assert set(get_args(get_type_hints(DocumentBlock)["kind"])) == {
        "ocr_text",
        "paragraph",
        "table_cell",
    }
    assert {item.name for item in fields(DocumentBlock)} >= {"kind", "text"}


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (mutate_flags, "invalid_archive"),
        (mutate_local_name, "invalid_archive"),
        (corrupt_section_data, "invalid_archive"),
        (truncate_central_directory, "invalid_archive"),
    ],
)
def test_hwpx_rejects_encryption_name_mismatch_and_crc_corruption(
    mutation: Callable[[bytes], bytes],
    expected_code: str,
) -> None:
    # Given: a valid archive modified at one low-level ZIP boundary.
    content = mutation(build_archive((("Contents/section0.xml", section("<p:p/>")),)))

    # When: archive validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("mutated", content, "mutated.hwpx")

    # Then: the malformed archive is rejected deterministically.
    assert caught.value.code == expected_code


@pytest.mark.parametrize(
    ("limit", "value"),
    [
        ("MAX_ARCHIVE_ENTRIES", 1),
        ("MAX_TOTAL_SIZE", 20),
        ("MAX_COMPRESSION_RATIO", 1),
    ],
)
def test_hwpx_enforces_each_archive_expansion_limit(
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
    value: int,
) -> None:
    # Given: a valid compressible document and one deliberately low safety limit.
    content = build_archive((("Contents/section0.xml", section("<p:p>" + "가" * 200 + "</p:p>")),))
    monkeypatch.setattr(archive_limits, limit, value)

    # When: archive validation runs.
    with pytest.raises(DocumentParseError) as caught:
        _ = HwpxParser().parse("bounded", content, "bounded.hwpx")

    # Then: all configured expansion dimensions share the bounded failure code.
    assert caught.value.code == "archive_too_large"
