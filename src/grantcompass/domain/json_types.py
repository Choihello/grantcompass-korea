"""Mutable input and deeply immutable JSON value types."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import override

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]
type FrozenJsonValue = JsonScalar | tuple["FrozenJsonValue", ...] | FrozenJsonObject


@dataclass(frozen=True, slots=True)
class FrozenJsonObject(Mapping[str, FrozenJsonValue]):
    """Hashable JSON object with recursively immutable values."""

    entries: tuple[tuple[str, FrozenJsonValue], ...] = ()

    @override
    def __getitem__(self, key: str) -> FrozenJsonValue:
        """Return the immutable value for a JSON object key."""
        for item_key, value in self.entries:
            if item_key == key:
                return value
        raise KeyError(key)

    @override
    def __iter__(self) -> Iterator[str]:
        """Iterate over JSON object keys."""
        return (key for key, _value in self.entries)

    @override
    def __len__(self) -> int:
        """Return the number of JSON object keys."""
        return len(self.entries)


def freeze_json_object(value: JsonObject | FrozenJsonObject) -> FrozenJsonObject:
    """Copy a JSON object into recursively immutable containers."""
    match value:
        case FrozenJsonObject():
            return value
        case dict() as raw:
            return FrozenJsonObject(
                entries=tuple((key, _freeze_json_value(item)) for key, item in sorted(raw.items()))
            )


def thaw_json_object(value: FrozenJsonObject) -> JsonObject:
    """Copy immutable JSON into mutable containers for persistence or transport."""
    return {key: _thaw_json_value(item) for key, item in value.entries}


def _freeze_json_value(value: JsonValue) -> FrozenJsonValue:
    match value:
        case None | str() | int() | float():
            return value
        case list() as items:
            return tuple(_freeze_json_value(item) for item in items)
        case dict() as mapping:
            return freeze_json_object(mapping)


def _thaw_json_value(value: FrozenJsonValue) -> JsonValue:
    match value:
        case None | str() | int() | float():
            return value
        case tuple() as items:
            return [_thaw_json_value(item) for item in items]
        case FrozenJsonObject():
            return thaw_json_object(value)
