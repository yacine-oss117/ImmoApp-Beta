from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


def normalize_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_json_value(item) for item in value]
    return str(value)


def normalize_json_object(value: object) -> JsonObject:
    if isinstance(value, Mapping):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    return {"raw": normalize_json_value(value)}
