"""Pure Markdown, URL, quote, and evidence formatting helpers."""

from collections.abc import Iterable
from string import hexdigits
from urllib.parse import urlsplit

from grantcompass.domain.documents import Evidence, EvidenceId

MAX_QUOTE_CHARS = 160
_MAX_PORT = 65535
_MARKDOWN_SPECIALS = (
    "\\",
    "`",
    "*",
    "_",
    "{",
    "}",
    "[",
    "]",
    "(",
    ")",
    "#",
    "+",
    "-",
    ".",
    "!",
    "|",
    ">",
    "<",
)


def escape_markdown(value: str) -> str:
    """Escape untrusted text for Markdown labels and table cells."""
    escaped = value.replace("&", "&amp;")
    for character in _MARKDOWN_SPECIALS:
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def bounded_quote(value: str) -> str:
    """Bound a quote by Unicode code points without external state."""
    if len(value) <= MAX_QUOTE_CHARS:
        return value
    return value[: MAX_QUOTE_CHARS - 1] + "…"


def valid_source_url(value: str) -> bool:
    """Accept only conservative HTTP or HTTPS source URLs."""
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(hostname)
        and (port is None or 1 <= port <= _MAX_PORT)
        and parsed.username is None
        and parsed.password is None
        and _valid_percent_encoding(value)
        and not any(character.isspace() for character in value)
        and not any(character in value for character in "\r\n<>\"'()[]\\")
    )


def _valid_percent_encoding(value: str) -> bool:
    for index, character in enumerate(value):
        if character == "%":
            if index + 2 >= len(value) or value[index + 1] not in hexdigits:
                return False
            if value[index + 2] not in hexdigits:
                return False
    return True


def evidence_index(
    evidence_items: Iterable[Evidence],
) -> tuple[dict[EvidenceId, Evidence], frozenset[EvidenceId]]:
    """Index evidence IDs and retain duplicate IDs as visible errors."""
    indexed: dict[EvidenceId, Evidence] = {}
    duplicates: set[EvidenceId] = set()
    for evidence in evidence_items:
        if evidence.id is None:
            continue
        if evidence.id in indexed:
            duplicates.add(evidence.id)
            continue
        indexed[evidence.id] = evidence
    return indexed, frozenset(duplicates)
