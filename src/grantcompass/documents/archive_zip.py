"""Raw ZIP directory validation independent of platform filename normalization."""

from typing import Final

from grantcompass.documents.archive_paths import validate_archive_path
from grantcompass.documents.base import ParseErrorCode, parse_failure

INVALID_ARCHIVE: Final[ParseErrorCode] = "invalid_archive"


def validate_raw_archive_names(content: bytes) -> None:
    """Validate central names and exact matching local-header names."""
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
        cursor = _validate_central_entry(content, cursor, end_offset)
    if cursor != directory_offset + directory_size:
        raise parse_failure(INVALID_ARCHIVE, "HWPX central directory size is invalid")


def _validate_central_entry(content: bytes, cursor: int, end_offset: int) -> int:
    if cursor + 46 > end_offset or content[cursor : cursor + 4] != b"PK\x01\x02":
        raise parse_failure(INVALID_ARCHIVE, "HWPX central entry is malformed")
    flags = _u16(content, cursor + 8)
    name_size = _u16(content, cursor + 28)
    extra_size = _u16(content, cursor + 30)
    comment_size = _u16(content, cursor + 32)
    entry_end = cursor + 46 + name_size + extra_size + comment_size
    if entry_end > end_offset:
        raise parse_failure(INVALID_ARCHIVE, "HWPX central entry is truncated")
    name_bytes = content[cursor + 46 : cursor + 46 + name_size]
    name = _decode_name(name_bytes, flags)
    validate_archive_path(name)
    _validate_local_name(content, _u32(content, cursor + 42), name_bytes)
    return entry_end


def _validate_local_name(content: bytes, offset: int, central_name: bytes) -> None:
    if offset + 30 > len(content) or content[offset : offset + 4] != b"PK\x03\x04":
        raise parse_failure(INVALID_ARCHIVE, "HWPX local entry is malformed")
    name_size = _u16(content, offset + 26)
    local_name = content[offset + 30 : offset + 30 + name_size]
    if local_name != central_name:
        raise parse_failure(INVALID_ARCHIVE, "HWPX local and central names differ")


def _decode_name(value: bytes, flags: int) -> str:
    encoding = "utf-8" if flags & 0x800 else "cp437"
    try:
        return value.decode(encoding)
    except UnicodeDecodeError as error:
        raise parse_failure(INVALID_ARCHIVE, "HWPX member name is invalid") from error


def _u16(content: bytes, offset: int) -> int:
    return int.from_bytes(content[offset : offset + 2], "little")


def _u32(content: bytes, offset: int) -> int:
    return int.from_bytes(content[offset : offset + 4], "little")
