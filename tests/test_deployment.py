from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from recap_service.app import RESPONSE_LIMIT, create_app
from recap_service.errors import AuthenticationRequired
from recap_service.json_codec import response_bytes
from recap_service.validation import authenticate
from tests.test_recap_service import GENERATION, request_for


ROOT = Path(__file__).resolve().parents[1]
GENERATION_CONTRACT_SHA256 = "5b5afa7662e84c6809f167827125dd38a82b47fa437a2a8c9ba73c039ae083a5"
TRANSPORT_SHA256 = "7772daae35b7b480328fc68e1df826575882c0d2f86cf49a3c05e24a26927457"
DEVELOPMENT_ENTRYPOINT_SHA256 = "8ac3e4b10ce176fe342b49c6883850e380a2f60fdd828f3458eb41da6db93a6c"
PUBLICATION_REVISION = "0123456789abcdef0123456789abcdef01234567"
PUBLICATION_DIGEST = "sha256:" + "a" * 64
PUBLICATION_CONFIG_DIGEST = "sha256:" + "1" * 64


FAKE_DOCKER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import io
    import json
    import os
    from pathlib import Path
    import sys
    import tarfile


    args = sys.argv[1:]
    scenario = os.environ["FAKE_DOCKER_SCENARIO"]
    state = Path(os.environ["FAKE_DOCKER_STATE"])
    repository = "crabitteam2/crabit-data"
    revision = os.environ["EXPECTED_TEST_REVISION"]
    tag = "sha-" + revision[:12]
    local_image = "crabit-recap:" + tag
    tagged_image = repository + ":" + tag
    config_digest = "sha256:" + "1" * 64
    different_config_digest = "sha256:" + "2" * 64
    first_digest = "sha256:" + "a" * 64
    different_digest = "sha256:" + "b" * 64


    def bump(name):
        path = state / name
        count = int(path.read_text()) if path.exists() else 0
        path.write_text(str(count + 1))
        return count + 1


    def remote_config():
        if scenario in {"existing-different", "pushed-different"}:
            return different_config_digest
        return config_digest


    if args[:2] == ["image", "inspect"]:
        reference = args[2]
        format_value = args[4]
        if reference == local_image:
            if "org.opencontainers.image.revision" in format_value:
                print(revision)
            elif ".Os" in format_value and ".Architecture" in format_value:
                print("linux/amd64")
            else:
                raise SystemExit("unexpected local inspect format: " + format_value)
            raise SystemExit(0)
        if reference.startswith(repository + "@"):
            digest = reference.split("@", 1)[1]
            if "org.opencontainers.image.revision" in format_value:
                print("f" * 40 if scenario == "wrong-revision" else revision)
            elif ".Os" in format_value and ".Architecture" in format_value:
                print("linux/arm64" if scenario == "wrong-architecture" else "linux/amd64")
            elif "RepoDigests" in format_value:
                print(json.dumps([repository + "@" + digest]))
            else:
                raise SystemExit("unexpected remote inspect format: " + format_value)
            raise SystemExit(0)
    if args[:2] == ["image", "save"] and args[2:] == [local_image]:
        archived_config = different_config_digest if scenario == "local-metadata-mismatch" else config_digest
        manifest = json.dumps([{
            "Config": "blobs/sha256/" + archived_config.removeprefix("sha256:"),
            "RepoTags": [local_image],
            "Layers": [],
        }]).encode()
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            member = tarfile.TarInfo("manifest.json")
            member.size = len(manifest)
            archive.addfile(member, io.BytesIO(manifest))
        raise SystemExit(0)
    if args[:2] == ["manifest", "inspect"]:
        if scenario == "index-digest":
            print(json.dumps({
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [],
            }))
        else:
            print(json.dumps({
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {"digest": remote_config()},
            }))
        raise SystemExit(0)
    if args[0] == "pull":
        reference = args[1]
        if reference == tagged_image:
            bump("tagged-pull-count")
            if scenario == "lookup-error":
                print("unauthorized: authentication required", file=sys.stderr)
                raise SystemExit(1)
            if scenario in {"missing-tag", "pushed-different", "push-error"}:
                print("manifest unknown: manifest unknown", file=sys.stderr)
                raise SystemExit(1)
            if scenario == "ambiguous-digest":
                print("Digest: " + first_digest)
                print("Digest: " + different_digest)
                raise SystemExit(0)
            print("Digest: " + first_digest)
            raise SystemExit(0)
        if reference.startswith(repository + "@"):
            bump("immutable-pull-count")
            print("Digest: " + reference.split("@", 1)[1])
            raise SystemExit(0)
    if args[0] == "tag" and args[1:] == [local_image, tagged_image]:
        bump("tag-count")
        raise SystemExit(0)
    if args[0] == "push" and args[1] == tagged_image:
        bump("push-count")
        if scenario == "push-error":
            print("connection reset after upload", file=sys.stderr)
            raise SystemExit(1)
        digest = different_digest if scenario == "pushed-different" else first_digest
        print(tagged_image + ": digest: " + digest + " size: 1")
        raise SystemExit(0)

    print("unexpected fake docker invocation: " + repr(args), file=sys.stderr)
    raise SystemExit(64)
''')


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


class ImagePublicationTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temporary_path = Path(self.temporary_directory.name)
        self.binary_path = self.temporary_path / "bin"
        self.state_path = self.temporary_path / "state"
        self.binary_path.mkdir()
        self.state_path.mkdir()
        fake_docker = self.binary_path / "docker"
        fake_docker.write_text(FAKE_DOCKER)
        fake_docker.chmod(0o700)
        self.metadata_path = self.temporary_path / "tested-image-metadata.json"
        self.metadata_path.write_text(json.dumps({
            "containerimage.digest": "sha256:" + "c" * 64,
            "containerimage.config.digest": PUBLICATION_CONFIG_DIGEST,
        }))
        self.output_path = self.temporary_path / "github-output"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_publication(self, scenario: str) -> subprocess.CompletedProcess[str]:
        for path in self.state_path.iterdir():
            path.unlink()
        self.output_path.unlink(missing_ok=True)
        environment = os.environ.copy()
        environment.update({
            "PATH": str(self.binary_path) + os.pathsep + environment["PATH"],
            "FAKE_DOCKER_SCENARIO": scenario,
            "FAKE_DOCKER_STATE": str(self.state_path),
            "EXPECTED_TEST_REVISION": PUBLICATION_REVISION,
        })
        return subprocess.run(
            [
                str(ROOT / "scripts/deployment/publish-image.sh"),
                PUBLICATION_REVISION,
                str(self.metadata_path),
                str(self.output_path),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def output(self) -> dict[str, str]:
        return dict(line.split("=", 1) for line in self.output_path.read_text().splitlines())

    def count(self, name: str) -> int:
        path = self.state_path / name
        return int(path.read_text()) if path.exists() else 0

    def test_existing_immutable_tag_is_adopted_after_exact_read_back(self):
        completed = self.run_publication("existing")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.output(), {
            "image_digest": PUBLICATION_DIGEST,
            "image_reference": "crabitteam2/crabit-data@" + PUBLICATION_DIGEST,
            "image_tag": "sha-" + PUBLICATION_REVISION[:12],
            "image_architecture": "linux/amd64",
            "image_config_digest": PUBLICATION_CONFIG_DIGEST,
            "image_revision": PUBLICATION_REVISION,
            "publication_result": "adopted",
        })
        self.assertEqual(self.count("tagged-pull-count"), 1)
        self.assertEqual(self.count("immutable-pull-count"), 1)
        self.assertEqual(self.count("push-count"), 0)

    def test_missing_tag_is_published_once_then_read_back_by_digest(self):
        completed = self.run_publication("missing-tag")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.output()["publication_result"], "published")
        self.assertEqual(self.output()["image_digest"], PUBLICATION_DIGEST)
        self.assertEqual(self.count("tagged-pull-count"), 1)
        self.assertEqual(self.count("tag-count"), 1)
        self.assertEqual(self.count("push-count"), 1)
        self.assertEqual(self.count("immutable-pull-count"), 1)

    def test_registry_lookup_error_is_not_treated_as_an_absent_tag(self):
        completed = self.run_publication("lookup-error")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("registry tag lookup failed", completed.stderr)
        self.assertEqual(self.count("push-count"), 0)

    def test_build_metadata_must_identify_the_local_tested_image(self):
        completed = self.run_publication("local-metadata-mismatch")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("local image does not match the tested build metadata", completed.stderr)
        self.assertEqual(self.count("tagged-pull-count"), 0)
        self.assertEqual(self.count("push-count"), 0)

    def test_failed_push_is_reported_as_ambiguous_and_never_retried(self):
        completed = self.run_publication("push-error")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("registry push failed or is ambiguous", completed.stderr)
        self.assertEqual(self.count("push-count"), 1)

    def test_conflicting_image_identity_is_never_adopted(self):
        for scenario in ("existing-different", "pushed-different"):
            with self.subTest(scenario=scenario):
                completed = self.run_publication(scenario)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("does not match the locally tested image", completed.stderr)

    def test_non_single_platform_or_wrong_runtime_identity_fails_closed(self):
        expected_error = {
            "index-digest": "single-platform image manifest",
            "wrong-revision": "revision does not match",
            "wrong-architecture": "must be linux/amd64",
            "ambiguous-digest": "registry digest read-back failed",
        }
        for scenario, error in expected_error.items():
            with self.subTest(scenario=scenario):
                completed = self.run_publication(scenario)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(error, completed.stderr)


if __name__ == "__main__":
    unittest.main()
