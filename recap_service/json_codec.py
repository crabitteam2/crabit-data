"""Strict JSON parsing and deterministic JSON encoding."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from typing import Any

from .errors import MalformedRequest


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MalformedRequest("Request JSON contains a duplicate key.", [key])
        result[key] = value
    return result


def parse_json(body: bytes) -> dict[str, Any]:
    try:
        text = body.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except MalformedRequest:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MalformedRequest("Request body must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise MalformedRequest("Request JSON must be an object.")
    return value


def canonical_bytes(value: Any, *, sort_keys: bool = True) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=sort_keys,
        separators=(",", ":"),
    ).encode("utf-8")


def digest(value: Any, *, sort_keys: bool = True) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value, sort_keys=sort_keys)).hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite JSON number")
    return value


def response_bytes(value: Any) -> bytes:
    return canonical_bytes(jsonable(value), sort_keys=True)
