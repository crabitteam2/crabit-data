"""Deterministic production server settings for the private recap service."""

from __future__ import annotations

import os


def _bounded_integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


host = os.environ.get("CRABIT_RECAP_HOST", "0.0.0.0")
if not host or any(character.isspace() for character in host) or ":" in host:
    raise RuntimeError("CRABIT_RECAP_HOST must be a nonempty IPv4 host name")
port = _bounded_integer("CRABIT_RECAP_PORT", 8081, 1, 65535)

bind = f"{host}:{port}"
workers = _bounded_integer("CRABIT_RECAP_WORKERS", 2, 1, 8)
threads = _bounded_integer("CRABIT_RECAP_THREADS", 1, 1, 4)
timeout = _bounded_integer("CRABIT_RECAP_REQUEST_TIMEOUT_SECONDS", 30, 1, 120)
graceful_timeout = _bounded_integer("CRABIT_RECAP_GRACEFUL_TIMEOUT_SECONDS", 30, 1, 120)

worker_class = "sync"
worker_tmp_dir = "/tmp"
preload_app = True
backlog = 128
keepalive = 2
max_requests = 1000
max_requests_jitter = 0
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 8190

accesslog = None
errorlog = "-"
loglevel = os.environ.get("CRABIT_RECAP_LOG_LEVEL", "info")
capture_output = False
disable_redirect_access_to_syslog = True
forwarded_allow_ips = ""
secure_scheme_headers = {}
proc_name = "crabit-recap"
umask = 0o077
