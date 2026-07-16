"""Canonical archive-member path safety rules."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Final
from unicodedata import normalize
from urllib.parse import unquote

from grantcompass.documents.base import ParseErrorCode, parse_failure

DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
ENCODED_OCTET = re.compile(r"%[0-9A-Fa-f]{2}")
UNSAFE_ARCHIVE_PATH: Final[ParseErrorCode] = "unsafe_archive_path"
MAX_DECODE_ROUNDS = 2


def validate_archive_path(name: str) -> None:
    """Reject unsafe literal, compatibility-normalized, or decoded path forms."""
    for interpretation in _interpretations(name):
        _validate_interpretation(interpretation)


def canonical_path_key(name: str) -> str:
    """Return the terminal bounded canonical form used for alias detection."""
    return _interpretations(name)[-1].casefold()


def _interpretations(name: str) -> tuple[str, ...]:
    forms: list[str] = []
    current = name
    for _round in range(MAX_DECODE_ROUNDS + 1):
        normalized = normalize("NFKC", current)
        if normalized not in forms:
            forms.append(normalized)
        if ENCODED_OCTET.search(normalized) is None:
            break
        try:
            decoded = unquote(normalized, encoding="utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise parse_failure(UNSAFE_ARCHIVE_PATH, "Archive path encoding is invalid") from error
        if decoded == current:
            break
        current = decoded
    return tuple(forms)


def _validate_interpretation(name: str) -> None:
    parts = name.split("/")
    unsafe = (
        not name
        or "\\" in name
        or name.startswith("/")
        or DRIVE_PATTERN.match(name) is not None
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(name).is_absolute()
    )
    if unsafe:
        raise parse_failure(UNSAFE_ARCHIVE_PATH, "HWPX contains an unsafe member path")
