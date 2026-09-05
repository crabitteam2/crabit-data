from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from recap_service.app import RESPONSE_LIMIT, create_app
from recap_service.errors import AuthenticationRequired
from recap_service.json_codec import response_bytes
from recap_service.validation import authenticate
from tests.test_recap_service import GENERATION, request_for


ROOT = Path(__file__).resolve().parents[1]
GENERATION_CONTRACT_SHA256 = "ec93e480994203a6c8a62d5b9e9992627fba9b71ef346640ea7b80c38f62d233"
TRANSPORT_SHA256 = "7772daae35b7b480328fc68e1df826575882c0d2f86cf49a3c05e24a26927457"
DEVELOPMENT_ENTRYPOINT_SHA256 = "8ac3e4b10ce176fe342b49c6883850e380a2f60fdd828f3458eb41da6db93a6c"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call_wsgi(**overrides):
    request = request_for()
    body = response_bytes(request)
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/internal/v1/recap-generations",
        "QUERY_STRING": "",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "HTTP_AUTHORIZATION": "Bearer deployment-test-secret",
        "HTTP_IDEMPOTENCY_KEY": GENERATION,
        "wsgi.input": BytesIO(body),
    }
    environ.update(overrides)
    captured = {}
    result = b"".join(create_app("deployment-test-secret")(
        environ,
        lambda status, headers: captured.update(status=status, headers=dict(headers)),
    ))
    return captured["status"], captured["headers"], result


class InterfacePreservationTest(unittest.TestCase):
    def test_approved_contract_and_transport_bytes_are_unchanged(self):
        self.assertEqual(sha256(ROOT / "api/recap-generation-v1.yaml"), GENERATION_CONTRACT_SHA256)
        self.assertEqual(sha256(ROOT / "recap_service/app.py"), TRANSPORT_SHA256)
        self.assertEqual(sha256(ROOT / "recap_service/__main__.py"), DEVELOPMENT_ENTRYPOINT_SHA256)

    def test_success_headers_remain_exact(self):
        status, headers, result = call_wsgi()
        self.assertEqual(status, "200 OK")
        self.assertEqual(headers, {
            "Content-Type": "application/json",
            "Content-Length": str(len(result)),
            "Cache-Control": "no-store",
        })

    def test_no_http_health_or_readiness_route_is_added(self):
        for method, path in (("GET", "/health"), ("HEAD", "/ready"), ("GET", "/internal/health")):
            with self.subTest(method=method, path=path):
                status, headers, result = call_wsgi(REQUEST_METHOD=method, PATH_INFO=path)
                self.assertEqual(status, "400 Bad Request")
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(json.loads(result)["code"], "MALFORMED_REQUEST")

    def test_response_limit_still_fails_closed(self):
        with patch("recap_service.app.generate_recap", return_value={"oversize": "x" * RESPONSE_LIMIT}):
            status, _, result = call_wsgi()
        self.assertEqual(status, "500 Internal Server Error")
        self.assertEqual(json.loads(result)["code"], "RECAP_CALCULATION_FAILED")

    def test_bearer_comparison_uses_constant_time_bytes(self):
        with patch("recap_service.validation.hmac.compare_digest", return_value=False) as compare:
            with self.assertRaises(AuthenticationRequired):
                authenticate("Bearer supplied", "expected")
        compare.assert_called_once_with(b"supplied", b"expected")


class ProductionServerConfigurationTest(unittest.TestCase):
    def load_config(self, **environment):
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(ROOT / "gunicorn.conf.py"))

    def test_defaults_are_bounded_and_preload_the_application(self):
        config = self.load_config()
        self.assertEqual(config["bind"], "0.0.0.0:8081")
        self.assertEqual(config["workers"], 2)
        self.assertEqual(config["threads"], 1)
        self.assertEqual(config["worker_class"], "sync")
        self.assertTrue(config["preload_app"])
        self.assertEqual(config["timeout"], 30)
        self.assertEqual(config["graceful_timeout"], 30)
        self.assertEqual(config["max_requests"], 1000)
        self.assertEqual(config["max_requests_jitter"], 0)
        self.assertIsNone(config["accesslog"])
        self.assertEqual(config["worker_tmp_dir"], "/tmp")

    def test_runtime_tuning_is_range_checked(self):
        for name, value in (
            ("CRABIT_RECAP_WORKERS", "0"),
            ("CRABIT_RECAP_THREADS", "5"),
            ("CRABIT_RECAP_PORT", "65536"),
            ("CRABIT_RECAP_REQUEST_TIMEOUT_SECONDS", "not-an-integer"),
        ):
            with self.subTest(name=name, value=value):
                with self.assertRaises(RuntimeError):
                    self.load_config(**{name: value})

    def test_application_preload_requires_a_nonempty_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "nonempty recap service token"):
                runpy.run_module("recap_service.wsgi", run_name="__deployment_test__")

    def test_application_preload_accepts_runtime_token(self):
        with patch.dict(os.environ, {"CRABIT_RECAP_TOKEN": "runtime-secret"}, clear=True):
            module = runpy.run_module("recap_service.wsgi", run_name="__deployment_test__")
        self.assertEqual(module["application"]._token, "runtime-secret")


if __name__ == "__main__":
    unittest.main()
