"""Conservative promotion of contradictory official rule outcomes."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from ipaddress import AddressValueError, IPv4Address, IPv6Address
from typing import Final, Literal
from urllib.parse import urlsplit, urlunsplit

from grantcompass.domain.eligibility import EligibilityRule, RuleAssessment
from grantcompass.domain.enums import ConditionStatus, RuleKind
from grantcompass.rules.evaluation_values import expected_codes, performance_expected

type NumericDirection = Literal["lower", "upper"]

HTTP_DEFAULT_PORT: Final = 80
HTTPS_DEFAULT_PORT: Final = 443
_ASCII_SPACE: Final = 32
_ASCII_DELETE: Final = 127
_MAX_DNS_HOST_LENGTH: Final = 253
_MAX_DNS_LABEL_LENGTH: Final = 63
_HEX_DIGITS: Final = frozenset("0123456789abcdefABCDEF")
_UNRESERVED: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_AGE_RULE_KINDS: Final = frozenset({RuleKind.BUSINESS_AGE_MONTHS, RuleKind.REPRESENTATIVE_AGE})
_NUMERIC_RULE_KINDS: Final = _AGE_RULE_KINDS | {RuleKind.PERFORMANCE}
_SET_RULE_KINDS: Final = frozenset({RuleKind.REGION, RuleKind.INDUSTRY, RuleKind.DUPLICATE_BENEFIT})


@dataclass(frozen=True, slots=True)
class ConflictGroupKey:
    """Typed semantic group whose rules may represent competing constraints."""

    kind: RuleKind
    direction: NumericDirection | None = None
    metric_key: str | None = None


def promote_conflicts(
    rules: Sequence[EligibilityRule],
    items: Sequence[RuleAssessment],
) -> tuple[RuleAssessment, ...]:
    """Promote only comparable required cross-source contradictions."""
    indexes: set[int] = set()
    for left_index, left_rule in enumerate(rules):
        for right_index in range(left_index + 1, len(rules)):
            right_rule = rules[right_index]
            if _contradicts(
                left_rule,
                items[left_index],
                right_rule,
                items[right_index],
            ):
                indexes.update((left_index, right_index))
    return tuple(
        replace(item, status=ConditionStatus.CONFLICT, explanation="source_conflict")
        if index in indexes
        else item
        for index, item in enumerate(items)
    )


def _contradicts(
    left_rule: EligibilityRule,
    left_item: RuleAssessment,
    right_rule: EligibilityRule,
    right_item: RuleAssessment,
) -> bool:
    statuses = {left_item.status, right_item.status}
    return (
        left_rule.required
        and right_rule.required
        and statuses == {ConditionStatus.SATISFIED, ConditionStatus.UNSATISFIED}
        and _distinct_sources(left_rule, right_rule)
        and _comparable(left_rule, right_rule)
    )


def _distinct_sources(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_documents = {item.document_id for item in left.evidence}
    right_documents = {item.document_id for item in right.evidence}
    left_urls = _canonical_urls(left)
    right_urls = _canonical_urls(right)
    return (
        left_documents.isdisjoint(right_documents)
        and left_urls is not None
        and right_urls is not None
        and left_urls.isdisjoint(right_urls)
    )


def _comparable(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_group = _conflict_group(left)
    right_group = _conflict_group(right)
    if left_group is None or left_group != right_group:
        return False
    if left_group.kind in _NUMERIC_RULE_KINDS:
        return True
    if left_group.kind in _SET_RULE_KINDS:
        return _overlapping_codes(left, right)
    return False


def _conflict_group(rule: EligibilityRule) -> ConflictGroupKey | None:
    if rule.kind in _AGE_RULE_KINDS:
        direction = _numeric_direction(rule.operator)
        return None if direction is None else ConflictGroupKey(kind=rule.kind, direction=direction)
    if rule.kind is RuleKind.PERFORMANCE:
        expected = performance_expected(rule.expected_value)
        direction = _numeric_direction(rule.operator)
        return (
            None
            if expected is None or direction is None
            else ConflictGroupKey(
                kind=rule.kind,
                direction=direction,
                metric_key=expected[0],
            )
        )
    if rule.kind in _SET_RULE_KINDS:
        return ConflictGroupKey(kind=rule.kind)
    return None


def _numeric_direction(operator: str) -> NumericDirection | None:
    if operator in {"gte", "gt"}:
        return "lower"
    if operator in {"lte", "lt"}:
        return "upper"
    return None


def _overlapping_codes(left: EligibilityRule, right: EligibilityRule) -> bool:
    left_codes = expected_codes(left.expected_value)
    right_codes = expected_codes(right.expected_value)
    return (
        left_codes is not None
        and right_codes is not None
        and not left_codes.isdisjoint(right_codes)
    )


def _canonical_urls(rule: EligibilityRule) -> frozenset[str] | None:
    urls: set[str] = set()
    for evidence in rule.evidence:
        canonical = _canonical_url(evidence.source_url)
        if canonical is None:
            return None
        urls.add(canonical)
    return frozenset(urls)


def _canonical_url(value: str) -> str | None:
    normalized_value = None if _has_forbidden_ascii(value) else _normalize_percent_encoding(value)
    if normalized_value is None:
        return None
    try:
        parsed = urlsplit(normalized_value)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname
    if scheme not in {"http", "https"} or hostname is None:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    canonical_host = _canonical_host(hostname)
    if canonical_host is None:
        return None
    host, is_ipv6 = canonical_host
    rendered_host = f"[{host}]" if is_ipv6 else host
    default_port = (scheme == "http" and port == HTTP_DEFAULT_PORT) or (
        scheme == "https" and port == HTTPS_DEFAULT_PORT
    )
    netloc = rendered_host if port is None or default_port else f"{rendered_host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def _has_forbidden_ascii(value: str) -> bool:
    return any(
        ord(character) <= _ASCII_SPACE or ord(character) == _ASCII_DELETE for character in value
    )


def _normalize_percent_encoding(value: str) -> str | None:
    normalized: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "%":
            normalized.append(character)
            index += 1
            continue
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            return None
        escape = value[index + 1 : index + 3]
        decoded = chr(int(escape, 16))
        normalized.append(decoded if decoded in _UNRESERVED else f"%{escape.upper()}")
        index += 3
    return "".join(normalized)


def _canonical_host(hostname: str) -> tuple[str, bool] | None:
    if ":" in hostname:
        return _canonical_ipv6_host(hostname)
    if "." in hostname and all(character in "0123456789." for character in hostname):
        return _canonical_ipv4_host(hostname)
    return _canonical_dns_host(hostname)


def _canonical_ipv6_host(hostname: str) -> tuple[str, bool] | None:
    try:
        return IPv6Address(hostname).compressed.casefold(), True
    except AddressValueError:
        return None


def _canonical_ipv4_host(hostname: str) -> tuple[str, bool] | None:
    try:
        return str(IPv4Address(hostname)), False
    except AddressValueError:
        return None


def _canonical_dns_host(hostname: str) -> tuple[str, bool] | None:
    try:
        ascii_host = hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return None
    host = ascii_host.removesuffix(".")
    if not host or len(host) > _MAX_DNS_HOST_LENGTH:
        return None
    if not all(_is_valid_dns_label(label) for label in host.split(".")):
        return None
    return host, False


def _is_valid_dns_label(label: str) -> bool:
    if not label or len(label) > _MAX_DNS_LABEL_LENGTH:
        return False
    if not label[0].isalnum() or not label[-1].isalnum():
        return False
    if not all(character.isalnum() or character == "-" for character in label):
        return False
    if label.startswith("xn--"):
        try:
            _ = label.encode("ascii").decode("idna")
        except UnicodeError:
            return False
    return True
