"""Strict JSON parsing and RFC 8785 JSON canonicalization."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

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


def _checked_string(value: str) -> str:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("RFC 8785 JSON cannot contain an unpaired Unicode surrogate")
    return value


def _utf16_sort_key(value: str) -> bytes:
    return _checked_string(value).encode("utf-16-be")


def _quote(value: str) -> str:
    return json.dumps(
        _checked_string(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _float_text(value: float) -> str:
    """Render one finite IEEE-754 value using ECMAScript Number.toString rules."""
    if not math.isfinite(value):
        raise ValueError("RFC 8785 JSON numbers must be finite")
    if value == 0:
        return "0"

    sign = "-" if value < 0 else ""
    shortest = repr(abs(value)).lower()
    mantissa, marker, exponent_text = shortest.partition("e")
    exponent = int(exponent_text) if marker else 0
    integer, dot, fraction = mantissa.partition(".")
    digits = integer + (fraction if dot else "")
    decimal_position = len(integer) + exponent

    leading_zeroes = len(digits) - len(digits.lstrip("0"))
    digits = digits[leading_zeroes:]
    decimal_position -= leading_zeroes
    digits = digits.rstrip("0")
    if not digits:
        return "0"

    decimal_exponent = decimal_position - 1
    if 0 <= decimal_exponent < 21:
        if len(digits) <= decimal_position:
            rendered = digits + ("0" * (decimal_position - len(digits)))
        else:
            rendered = digits[:decimal_position] + "." + digits[decimal_position:]
    elif -6 <= decimal_exponent < 0:
        rendered = "0." + ("0" * (-decimal_position)) + digits
    else:
        rendered = digits[0]
        if len(digits) > 1:
            rendered += "." + digits[1:]
        rendered += "e" + ("+" if decimal_exponent >= 0 else "") + str(decimal_exponent)
    return sign + rendered


def _canonical_text(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float_text(value)
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("RFC 8785 JSON object keys must be strings")
        return "{" + ",".join(
            _quote(key) + ":" + _canonical_text(value[key])
            for key in sorted(value, key=_utf16_sort_key)
        ) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ",".join(_canonical_text(item) for item in value) + "]"
    raise TypeError(f"Unsupported RFC 8785 JSON value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Return the RFC 8785 JSON Canonicalization Scheme encoding of *value*."""
    return _canonical_text(value).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


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
    return canonical_bytes(jsonable(value))
