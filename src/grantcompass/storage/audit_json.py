"""Canonical immutable JSON conversion for append-only audit records."""

import json
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import TypeAdapter, ValidationError

from grantcompass.domain.cases import (
    AuditErrorCode,
    AuditEvent,
    AuditEventId,
    AuditValidationError,
)
from grantcompass.domain.json_types import (
    FrozenJsonObject,
    JsonObject,
    freeze_json_object,
    thaw_json_object,
)
from grantcompass.storage.audit_schemas import (
    AuditStateKind,
    parse_audit_identity,
    validate_audit_state,
)
from grantcompass.storage.table_cases import AuditEventRow

_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_MAX_ACTOR_LENGTH: Final = 300
_MAX_REASON_LENGTH: Final = 2_000


def dump_audit_json(value: FrozenJsonObject) -> str:
    """Serialize one audit state with deterministic compact key order."""
    return json.dumps(
        thaw_json_object(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def load_audit_json(value: str | None, kind: AuditStateKind) -> FrozenJsonObject:
    """Parse one stored audit state or surface a finite corruption code."""
    if value is None:
        raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT)
    try:
        validate_audit_state(value, kind)
        raw = _JSON_OBJECT.validate_json(value, strict=True)
        return freeze_json_object(raw)
    except ValidationError:
        raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT) from None


def validate_attribution(actor: str, reason: str, occurred_at: datetime) -> tuple[str, str]:
    """Normalize and validate bounded attribution at a UTC write boundary."""
    normalized_actor = actor.strip()
    normalized_reason = reason.strip()
    if not normalized_actor:
        raise AuditValidationError(AuditErrorCode.ACTOR_REQUIRED)
    if len(normalized_actor) > _MAX_ACTOR_LENGTH:
        raise AuditValidationError(AuditErrorCode.ACTOR_TOO_LONG)
    if not normalized_reason:
        raise AuditValidationError(AuditErrorCode.REASON_REQUIRED)
    if len(normalized_reason) > _MAX_REASON_LENGTH:
        raise AuditValidationError(AuditErrorCode.REASON_TOO_LONG)
    if occurred_at.utcoffset() is None:
        raise AuditValidationError(AuditErrorCode.NAIVE_TIME)
    if occurred_at.utcoffset() != timedelta(0):
        raise AuditValidationError(AuditErrorCode.NON_UTC_TIME)
    return normalized_actor, normalized_reason


def audit_event_from_row(row: AuditEventRow) -> AuditEvent:
    """Parse one mutable audit row into an immutable domain event."""
    try:
        kind = parse_audit_identity(row.entity_type, row.action)
        return AuditEvent(
            id=AuditEventId(row.id),
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            action=row.action,
            actor_name=row.actor_name,
            reason=row.reason,
            before_json=load_audit_json(row.before_json, kind),
            after_json=load_audit_json(row.after_json, kind),
            created_at=aware_utc(row.created_at),
        )
    except ValidationError:
        raise AuditValidationError(AuditErrorCode.MALFORMED_AUDIT) from None


def aware_utc(value: datetime) -> datetime:
    """Restore SQLite UTC timezone information lost by its datetime adapter."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
