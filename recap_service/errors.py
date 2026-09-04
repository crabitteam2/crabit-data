"""Closed, transport-safe errors for the recap service."""


class RecapServiceError(Exception):
    status = 500
    code = "RECAP_CALCULATION_FAILED"
    retryable = True

    def __init__(self, message: str, field_errors: list[str] | None = None):
        super().__init__(message)
        self.public_message = message
        self.field_errors = field_errors or []


class MalformedRequest(RecapServiceError):
    status = 400
    code = "MALFORMED_REQUEST"
    retryable = False


class AuthenticationRequired(RecapServiceError):
    status = 401
    code = "AUTH_REQUIRED"
    retryable = False


class PayloadTooLarge(RecapServiceError):
    status = 413
    code = "PAYLOAD_TOO_LARGE"
    retryable = False


class UnsupportedMediaType(RecapServiceError):
    status = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    retryable = False


class InvalidRecapInput(RecapServiceError):
    status = 422
    code = "RECAP_INPUT_INVALID"
    retryable = False


class CalculationFailed(RecapServiceError):
    status = 500
    code = "RECAP_CALCULATION_FAILED"
    retryable = True


class ServiceUnavailable(RecapServiceError):
    status = 503
    code = "RECAP_SERVICE_UNAVAILABLE"
    retryable = True
