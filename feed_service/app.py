"""Dependency-free authenticated WSGI feed endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Callable, Iterable

from feed.ranking import MODEL_VERSION, rank
from .validation import InvalidInput, validate

REQUEST_LIMIT = 262_144
RESPONSE_LIMIT = 65_536


class DuplicateField(ValueError): pass


def _json(body: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise DuplicateField(key)
            result[key] = value
        return result
    return json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


class FeedApplication:
    def __init__(self, credential: str):
        if not credential: raise ValueError("A nonempty feed ranking credential is required")
        self.credential = credential

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        if environ.get("REQUEST_METHOD") == "GET" and environ.get("PATH_INFO") == "/health" and not environ.get("QUERY_STRING"):
            return self._respond(start_response, 200, {"status": "ok"})
        if environ.get("REQUEST_METHOD") != "POST" or environ.get("PATH_INFO") != "/internal/v1/feed-rankings" or environ.get("QUERY_STRING"):
            return self._error(start_response, 400, "MALFORMED_REQUEST", False, ["$"])
        supplied = environ.get("HTTP_AUTHORIZATION", "")
        if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], self.credential):
            return self._error(start_response, 401, "AUTH_REQUIRED", False, [], auth=True)
        media = (environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
        if media != "application/json": return self._error(start_response, 415, "UNSUPPORTED_MEDIA_TYPE", False, [])
        try: length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError: return self._error(start_response, 400, "MALFORMED_REQUEST", False, ["$"])
        if length < 0: return self._error(start_response, 400, "MALFORMED_REQUEST", False, ["$"])
        if length > REQUEST_LIMIT: return self._error(start_response, 413, "PAYLOAD_TOO_LARGE", False, [])
        body = environ["wsgi.input"].read(length if length else REQUEST_LIMIT + 1)
        if len(body) > REQUEST_LIMIT: return self._error(start_response, 413, "PAYLOAD_TOO_LARGE", False, [])
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        try:
            request = validate(_json(body))
        except (UnicodeError, json.JSONDecodeError, DuplicateField, ValueError):
            return self._error(start_response, 400, "MALFORMED_REQUEST", False, ["$"])
        except InvalidInput as error:
            return self._error(start_response, 422, "INVALID_FEED_INPUT", False, error.paths)
        try:
            ordered = rank(request)
        except Exception:
            return self._error(start_response, 500, "RANKING_FAILED", False, [])
        response = {"schema_version": 1, "request_id": request["request_id"], "context_id": request["context_id"], "input_digest": digest, "model_version": MODEL_VERSION, "ordered_card_ids": ordered}
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        if len(encoded) > RESPONSE_LIMIT: return self._error(start_response, 500, "RANKING_FAILED", False, [])
        return self._respond(start_response, 200, encoded)

    def _error(self, start_response, status, code, retryable, fields, auth=False):
        trace = hashlib.sha256((code + ":" + ",".join(fields)).encode()).hexdigest()[:24]
        result = self._respond(start_response, status, {"code": code, "message": "Feed ranking request could not be processed.", "retryable": retryable, "trace_id": trace, "field_errors": fields}, auth)
        return result

    @staticmethod
    def _respond(start_response, status, value, auth=False):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        names = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 413: "Payload Too Large", 415: "Unsupported Media Type", 422: "Unprocessable Content", 500: "Internal Server Error", 503: "Service Unavailable"}
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")]
        if auth: headers.append(("WWW-Authenticate", "Bearer"))
        start_response(f"{status} {names[status]}", headers)
        return [body]


def create_app(credential: str) -> FeedApplication:
    return FeedApplication(credential)
