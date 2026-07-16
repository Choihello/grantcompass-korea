"""Bounded in-memory access to HWPX ZIP content."""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from grantcompass.documents.base import DocumentParseError, parse_failure

MAX_ARCHIVE_ENTRIES = 256
MAX_ENTRY_SIZE = 10 * 1024 * 1024
MAX_TOTAL_SIZE = 50 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
HWPX_MIMETYPE = b"application/hwp+zip"
SECTION_PATTERN = re.compile(r"Contents/section([0-9]+)\.xml")
DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
INVALID_ARCHIVE = "invalid_archive"
ARCHIVE_TOO_LARGE = "archive_too_large"
UNSAFE_ARCHIVE_PATH = "unsafe_archive_path"
MISSING_CONTENT = "missing_content"


@dataclass(frozen=True, slots=True)
class SectionXml:
    """One validated HWPX section and its numeric identity."""

    number: int
    path: str
    content: bytes


def read_sections(content: bytes) -> tuple[SectionXml, ...]:
    """Validate an HWPX archive before returning bounded section bytes."""
    try:
        _validate_raw_names(content)
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            _validate_infos(infos)
            _validate_mimetype(archive, infos)
            sections = _section_infos(infos)
            _require_sections(sections)
            _require_valid_crc(archive)
            return _read_section_content(archive, sections)
    except DocumentParseError:
        raise
    except (BadZipFile, OSError, RuntimeError, ValueError) as error:
        raise parse_failure(INVALID_ARCHIVE, "HWPX is not a valid ZIP archive") from error


def _require_sections(sections: tuple[tuple[int, ZipInfo], ...]) -> None:
    if not sections:
        raise parse_failure(MISSING_CONTENT, "HWPX contains no section XML")


def _require_valid_crc(archive: ZipFile) -> None:
    if archive.testzip() is not None:
        raise parse_failure(INVALID_ARCHIVE, "HWPX member CRC check failed")


def _read_section_content(
    archive: ZipFile,
    sections: tuple[tuple[int, ZipInfo], ...],
) -> tuple[SectionXml, ...]:
    return tuple(SectionXml(number, info.filename, archive.read(info)) for number, info in sections)


def _validate_raw_names(content: bytes) -> None:
    end_offset = content.rfind(b"PK\x05\x06")
    if end_offset < 0 or end_offset + 22 > len(content):
        raise parse_failure(INVALID_ARCHIVE, "HWPX central directory is missing")
    disk, directory_disk = _u16(content, end_offset + 4), _u16(content, end_offset + 6)
    disk_entries, total_entries = _u16(content, end_offset + 8), _u16(content, end_offset + 10)
    directory_size = _u32(content, end_offset + 12)
    directory_offset = _u32(content, end_offset + 16)
    if disk != 0 or directory_disk != 0 or disk_entries != total_entries:
        raise parse_failure(INVALID_ARCHIVE, "Multi-disk HWPX archives are unsupported")
    if directory_offset + directory_size > end_offset:
        raise parse_failure(INVALID_ARCHIVE, "HWPX central directory is malformed")
    cursor = directory_offset
    for _index in range(total_entries):
        if cursor + 46 > end_offset or content[cursor : cursor + 4] != b"PK\x01\x02":
            raise parse_failure(INVALID_ARCHIVE, "HWPX central entry is malformed")
        flags = _u16(content, cursor + 8)
        name_size = _u16(content, cursor + 28)
        extra_size = _u16(content, cursor + 30)
        comment_size = _u16(content, cursor + 32)
        entry_end = cursor + 46 + name_size + extra_size + comment_size
        if entry_end > end_offset:
            raise parse_failure(INVALID_ARCHIVE, "HWPX central entry is truncated")
        encoding = "utf-8" if flags & 0x800 else "cp437"
        try:
            name = content[cursor + 46 : cursor + 46 + name_size].decode(encoding)
        except UnicodeDecodeError as error:
            raise parse_failure(INVALID_ARCHIVE, "HWPX member name is invalid") from error
        _validate_path(name)
        cursor = entry_end
    if cursor != directory_offset + directory_size:
        raise parse_failure(INVALID_ARCHIVE, "HWPX central directory size is invalid")


def _u16(content: bytes, offset: int) -> int:
    return int.from_bytes(content[offset : offset + 2], "little")


def _u32(content: bytes, offset: int) -> int:
    return int.from_bytes(content[offset : offset + 4], "little")


def _validate_infos(infos: list[ZipInfo]) -> None:
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise parse_failure(ARCHIVE_TOO_LARGE, "HWPX has too many entries")
    seen: set[str] = set()
    total_size = 0
    for info in infos:
        _validate_path(info.filename)
        normalized = str(PurePosixPath(info.filename)).casefold()
        if normalized in seen:
            raise parse_failure(INVALID_ARCHIVE, "HWPX contains duplicate entries")
        seen.add(normalized)
        _validate_member_type(info)
        _validate_member_size(info)
        total_size += info.file_size
        if total_size > MAX_TOTAL_SIZE:
            raise parse_failure(ARCHIVE_TOO_LARGE, "HWPX expands beyond the total limit")


def _validate_path(name: str) -> None:
    raw_parts = name.split("/")
    unsafe = (
        not name
        or "\\" in name
        or name.startswith("/")
        or DRIVE_PATTERN.match(name) is not None
        or any(part in {"", ".", ".."} for part in raw_parts)
        or PurePosixPath(name).is_absolute()
    )
    if unsafe:
        raise parse_failure(UNSAFE_ARCHIVE_PATH, "HWPX contains an unsafe member path")


def _validate_member_type(info: ZipInfo) -> None:
    if info.flag_bits & 1:
        raise parse_failure(INVALID_ARCHIVE, "Encrypted HWPX entries are unsupported")
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    permitted = {0, stat.S_IFREG, stat.S_IFDIR}
    if file_type not in permitted or (info.is_dir() and file_type == stat.S_IFREG):
        raise parse_failure(INVALID_ARCHIVE, "HWPX contains a special archive entry")


def _validate_member_size(info: ZipInfo) -> None:
    if info.file_size > MAX_ENTRY_SIZE:
        raise parse_failure(ARCHIVE_TOO_LARGE, "HWPX entry exceeds the size limit")
    if info.file_size == 0:
        return
    ratio = info.file_size / max(info.compress_size, 1)
    if ratio > MAX_COMPRESSION_RATIO:
        raise parse_failure(ARCHIVE_TOO_LARGE, "HWPX entry exceeds the expansion ratio")


def _validate_mimetype(archive: ZipFile, infos: list[ZipInfo]) -> None:
    if not infos or infos[0].filename != "mimetype" or infos[0].compress_type != ZIP_STORED:
        raise parse_failure(INVALID_ARCHIVE, "HWPX mimetype marker is missing")
    if archive.read(infos[0]) != HWPX_MIMETYPE:
        raise parse_failure(INVALID_ARCHIVE, "HWPX mimetype marker is invalid")


def _section_infos(infos: list[ZipInfo]) -> tuple[tuple[int, ZipInfo], ...]:
    sections: list[tuple[int, ZipInfo]] = []
    numbers: set[int] = set()
    for info in infos:
        match = SECTION_PATTERN.fullmatch(info.filename)
        if match is None:
            continue
        number = int(match.group(1))
        if number in numbers:
            raise parse_failure(INVALID_ARCHIVE, "HWPX section identity is duplicated")
        numbers.add(number)
        sections.append((number, info))
    return tuple(sorted(sections, key=lambda item: item[0]))
