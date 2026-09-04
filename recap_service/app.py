"""Dependency-free WSGI transport for synchronous recap generation."""

from __future__ import annotations

import hashlib
import os
from typing import Callable, Iterable

from .errors import (
    CalculationFailed, MalformedRequest, PayloadTooLarge, RecapServiceError,
    UnsupportedMediaType,
)
from .generator import generate_recap
from .json_codec import parse_json, response_bytes
from .validation import authenticate, validate_request

REQUEST_LIMIT = 4_194_304
RESPONSE_LIMIT = 1_048_576
STATUS_TEXT = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 413: "Payload Too Large", 415: "Unsupported Media Type", 422: "Unprocessable Content", 500: "Internal Server Error", 503: "Service Unavailable"}


class RecapApplication:
    def __init__(self, token: str):
        if not token:
            raise ValueError("A nonempty recap service token is required")
        self._token = token

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        body = b""
        try:
            if environ.get("REQUEST_METHOD") != "POST" or environ.get("PATH_INFO") != "/internal/v1/recap-generations" or environ.get("QUERY_STRING"):
                raise MalformedRequest("Only POST /internal/v1/recap-generations without a query is supported.")
            authenticate(environ.get("HTTP_AUTHORIZATION"), self._token)
            media_type = (environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                raise UnsupportedMediaType("Content-Type must be application/json.")
            try:
                length = int(environ.get("CONTENT_LENGTH") or "0")
            except ValueError as exc:
                raise MalformedRequest("Content-Length is invalid.") from exc
            if length < 0:
                raise MalformedRequest("Content-Length is invalid.")
            if length > REQUEST_LIMIT:
                raise PayloadTooLarge("Request body exceeds 4194304 bytes.")
            body = environ["wsgi.input"].read(length if length else REQUEST_LIMIT + 1)
            if len(body) > REQUEST_LIMIT:
                raise PayloadTooLarge("Request body exceeds 4194304 bytes.")
            request = validate_request(parse_json(body), environ.get("HTTP_IDEMPOTENCY_KEY"))
            try:
                payload = generate_recap(request)
            except RecapServiceError:
                raise
            except Exception as exc:
                raise CalculationFailed("Recap calculation failed deterministically.") from exc
            encoded = response_bytes(payload)
            if len(encoded) > RESPONSE_LIMIT:
                raise CalculationFailed("Recap response exceeds the service limit.")
            return self._respond(start_response, 200, encoded)
        except RecapServiceError as error:
            trace = hashlib.sha256(body).hexdigest()[:24]
            encoded = response_bytes({
                "code": error.code,
                "message": error.public_message,
                "retryable": error.retryable,
                "trace_id": trace,
                "field_errors": error.field_errors,
            })
            return self._respond(start_response, error.status, encoded, auth=error.status == 401)

    @staticmethod
    def _respond(start_response: Callable, status: int, body: bytes, auth: bool = False) -> list[bytes]:
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")]
        if auth:
            headers.append(("WWW-Authenticate", "Bearer"))
        start_response(f"{status} {STATUS_TEXT[status]}", headers)
        return [body]


def create_app(token: str | None = None) -> RecapApplication:
    return RecapApplication(token if token is not None else os.environ.get("CRABIT_RECAP_TOKEN", ""))
