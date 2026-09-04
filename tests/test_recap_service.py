from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import unittest
from urllib.request import Request, urlopen

from recap_service.app import REQUEST_LIMIT, create_app
from recap_service.errors import InvalidRecapInput, MalformedRequest
from recap_service.generator import generate_recap
from recap_service.json_codec import canonical_bytes, digest, parse_json, response_bytes
from recap_service.validation import validate_request
from tests.real_service_harness import running_recap_service


GENERATION = "00000000-0000-4000-8000-000000000001"
STUDENT = "00000000-0000-4000-8000-000000000002"
ACCOUNT = "00000000-0000-4000-8000-000000000003"
ACADEMY = "00000000-0000-4000-8000-000000000004"
WISH = "00000000-0000-4000-8000-000000000005"


def request_for(kind: str = "WEEKLY") -> dict:
    monthly = kind == "MONTHLY"
    request = {
        "schema_version": 1,
        "algorithm_version": "recap-1",
        "generation_id": GENERATION,
        "input_digest": "",
        "student_id": STUDENT,
        "card_balance_account_id": ACCOUNT,
        "academy_id": ACADEMY,
        "kind": kind,
        "period": {
            "start_date": "2026-08-01" if monthly else "2026-08-24",
            "end_date_exclusive": "2026-09-01" if monthly else "2026-08-31",
            "timezone": "Asia/Seoul",
        },
        "reference_date": "2026-08-31" if monthly else "2026-08-30",
        "snapshot_at": "2026-09-02T00:00:00Z",
        "input": {
            "representative_wish_id": WISH,
            "wishes": [{
                "wish_id": WISH,
                "title": "자전거",
                "target_amount": 100000,
                "created_at": "2026-07-01T00:00:00Z",
                "closed_at": None,
                "deleted_at": None,
                "status": "IN_PROGRESS",
                "is_representative": True,
                "saved_amount_at_period_end": 0,
            }],
            "effective_transactions": [],
            "visit_metrics": {
                "received_visit_count": 0,
                "unique_received_visitor_count": 0,
                "previous_week_received_visit_count": 0,
                "monthly_outgoing_visit_count": 0,
            },
            "peer_metrics": {"habit_active_weeks": [], "achievement_rates": []},
            "success_story_candidates": [],
        },
    }
    return resign(request)


def resign(request: dict) -> dict:
    digestable = {key: value for key, value in request.items() if key not in {"generation_id", "input_digest"}}
    request["input_digest"] = digest(digestable)
    return request


def legacy_insertion_order_digest(request: dict) -> str:
    digestable = {key: value for key, value in request.items() if key not in {"generation_id", "input_digest"}}
    encoded = json.dumps(
        digestable,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def add_deposit(request: dict, day: int, amount: int = 1000) -> None:
    index = len(request["input"]["effective_transactions"]) + 10
    request["input"]["effective_transactions"].append({
        "root_event_id": f"00000000-0000-4000-8000-{index:012d}",
        "wish_id": WISH,
        "occurred_at": f"2026-08-{day:02d}T03:00:00Z",
        "amount": amount,
        "type": "DEPOSIT",
    })
    request["input"]["wishes"][0]["saved_amount_at_period_end"] += amount
    resign(request)


class CanonicalJsonTest(unittest.TestCase):
    def test_shared_java_python_numeric_and_unicode_vectors(self):
        path = Path(__file__).parent / "fixtures" / "jcs-cross-language-vectors.jsonl"
        vectors = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for vector in vectors:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(canonical_bytes(vector["value"]).decode("utf-8"), vector["canonical"])
                self.assertEqual(digest(vector["value"]), vector["digest"])

    def test_unpaired_unicode_surrogates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "surrogate"):
            canonical_bytes({"value": "\ud800"})


class ContractValidationTest(unittest.TestCase):
    def test_valid_request_and_idempotency_key(self):
        request = request_for()
        self.assertIs(validate_request(request, GENERATION), request)

    def test_unknown_fields_are_rejected(self):
        request = request_for()
        request["private_title"] = "must not cross the boundary"
        resign(request)
        with self.assertRaises(InvalidRecapInput):
            validate_request(request, GENERATION)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(MalformedRequest):
            parse_json(b'{"schema_version":1,"schema_version":1}')

    def test_idempotency_key_must_equal_generation_id(self):
        with self.assertRaises(InvalidRecapInput):
            validate_request(request_for(), STUDENT)

    def test_digest_detects_snapshot_tampering(self):
        request = request_for()
        request["reference_date"] = "2026-08-29"
        with self.assertRaises(InvalidRecapInput):
            validate_request(request, GENERATION)

    def test_digest_is_independent_of_object_insertion_order(self):
        request = request_for()
        request["input"]["visit_metrics"] = dict(reversed(list(request["input"]["visit_metrics"].items())))
        request["input"] = dict(reversed(list(request["input"].items())))
        request = dict(reversed(list(request.items())))
        self.assertIs(validate_request(request, GENERATION), request)

    def test_legacy_insertion_order_digest_is_rejected(self):
        request = request_for()
        legacy = legacy_insertion_order_digest(request)
        self.assertNotEqual(legacy, request["input_digest"])
        request["input_digest"] = legacy
        with self.assertRaises(InvalidRecapInput):
            validate_request(request, GENERATION)

    def test_boolean_is_not_an_integer(self):
        request = request_for()
        request["input"]["visit_metrics"]["received_visit_count"] = True
        resign(request)
        with self.assertRaises(InvalidRecapInput):
            validate_request(request, GENERATION)

    def test_week_must_be_monday_through_monday(self):
        request = request_for()
        request["period"]["start_date"] = "2026-08-25"
        request["period"]["end_date_exclusive"] = "2026-09-01"
        resign(request)
        with self.assertRaises(InvalidRecapInput):
            validate_request(request, GENERATION)


class GenerationTest(unittest.TestCase):
    def test_zero_activity_weekly_is_successful_and_deterministic(self):
        request = request_for()
        first = response_bytes(generate_recap(request))
        second = response_bytes(generate_recap(deepcopy(request)))
        self.assertEqual(first, second)
        result = json.loads(first)
        self.assertEqual(result["kind"], "WEEKLY")
        self.assertEqual(result["view"]["page1_last_week_performance"]["achievement"]["save_count"], 0)

    def test_weekly_uses_received_visits_and_bounded_stories(self):
        request = request_for()
        add_deposit(request, 25)
        request["input"]["visit_metrics"].update({
            "received_visit_count": 6,
            "unique_received_visitor_count": 4,
            "previous_week_received_visit_count": 3,
        })
        request["input"]["success_story_candidates"] = [{
            "wish_id": "00000000-0000-4000-8000-000000000099",
            "type_title": "꾸준형 토끼",
            "author_previous_month": {"deposit_count": 8},
        }]
        resign(request)
        view = generate_recap(validate_request(request, GENERATION))["view"]
        self.assertEqual(view["page2_growth_report"]["growth_pct"], 100)
        self.assertEqual(view["page3_academy_success_stories"]["stories"][0]["wish_id"], "00000000-0000-4000-8000-000000000099")

    def test_monthly_three_deposits_is_active_and_keeps_null_rank_states(self):
        request = request_for("MONTHLY")
        for day in (2, 9, 16):
            add_deposit(request, day, 1000)
        view = generate_recap(validate_request(request, GENERATION))["view"]
        self.assertTrue(view["is_active"])
        self.assertIsNone(view["group_comparison"]["habit_percentile"])
        self.assertEqual(view["group_comparison"]["habit_percentile_status"], "no_peers")

    def test_nonpositive_monthly_pace_has_no_expected_date(self):
        request = request_for("MONTHLY")
        view = generate_recap(validate_request(request, GENERATION))["view"]
        self.assertIsNone(view["pace_prediction"]["expected_completion_date"])
        self.assertIsNone(view["pace_prediction"]["required_daily_amount"])

    def test_every_identity_and_period_is_echoed(self):
        request = request_for()
        result = generate_recap(request)
        for field in ("schema_version", "algorithm_version", "generation_id", "input_digest", "student_id", "card_balance_account_id", "academy_id", "kind", "period"):
            self.assertEqual(result[field], request[field])


class HttpApplicationTest(unittest.TestCase):
    def call(self, request: dict | None, raw_body: bytes | None = None, **overrides):
        body = raw_body if raw_body is not None else (response_bytes(request) if request is not None else b"{}")
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/internal/v1/recap-generations",
            "QUERY_STRING": "",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body)),
            "HTTP_AUTHORIZATION": "Bearer secret",
            "HTTP_IDEMPOTENCY_KEY": GENERATION,
            "wsgi.input": BytesIO(body),
        }
        environ.update(overrides)
        captured = {}
        result = b"".join(create_app("secret")(environ, lambda status, headers: captured.update(status=status, headers=dict(headers))))
        return captured["status"], captured["headers"], json.loads(result)

    def test_http_success_matches_direct_function(self):
        request = request_for()
        status, _, result = self.call(request)
        self.assertEqual(status, "200 OK")
        self.assertEqual(result, json.loads(response_bytes(generate_recap(request))))

    def test_auth_failure_is_closed_and_challenges_bearer(self):
        status, headers, result = self.call(request_for(), HTTP_AUTHORIZATION="Bearer wrong")
        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(headers["WWW-Authenticate"], "Bearer")
        self.assertEqual(set(result), {"code", "message", "retryable", "trace_id", "field_errors"})
        self.assertFalse(result["retryable"])

    def test_content_type_and_query_are_rejected(self):
        status, _, result = self.call(request_for(), CONTENT_TYPE="text/plain")
        self.assertEqual(status, "415 Unsupported Media Type")
        self.assertEqual(result["code"], "UNSUPPORTED_MEDIA_TYPE")
        status, _, result = self.call(request_for(), QUERY_STRING="debug=true")
        self.assertEqual(status, "400 Bad Request")

    def test_declared_oversize_body_is_rejected_without_reading(self):
        status, _, result = self.call(request_for(), CONTENT_LENGTH=str(REQUEST_LIMIT + 1))
        self.assertEqual(status, "413 Payload Too Large")
        self.assertEqual(result["code"], "PAYLOAD_TOO_LARGE")

    def test_wsgi_accepts_reordered_unicode_and_numeric_jcs_input(self):
        request = request_for()
        request["input"]["wishes"][0]["title"] = "😀 자전거 €"
        request["input"]["peer_metrics"]["achievement_rates"] = [333333333.33333329, 1e-7]
        resign(request)
        request["input"] = dict(reversed(list(request["input"].items())))
        request = dict(reversed(list(request.items())))
        body = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, _, result = self.call(None, raw_body=body)
        self.assertEqual(status, "200 OK")
        self.assertEqual(result["input_digest"], request["input_digest"])

    def test_wsgi_rejects_legacy_insertion_order_digest(self):
        request = request_for()
        request["input_digest"] = legacy_insertion_order_digest(request)
        status, _, result = self.call(request)
        self.assertEqual(status, "422 Unprocessable Content")
        self.assertEqual(result["code"], "RECAP_INPUT_INVALID")
        self.assertEqual(result["field_errors"], ["input_digest"])


class RealServiceProcessTest(unittest.TestCase):
    def test_ephemeral_service_is_ready_and_serves_the_real_wsgi_app(self):
        request = request_for()
        body = response_bytes(request)
        with running_recap_service() as service:
            http_request = Request(
                service.base_url + "/internal/v1/recap-generations",
                data=body,
                method="POST",
                headers={
                    "Authorization": "Bearer " + service.token,
                    "Content-Type": "application/json",
                    "Idempotency-Key": GENERATION,
                },
            )
            with urlopen(http_request, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), json.loads(response_bytes(generate_recap(request))))
            self.assertIsNone(service.process.poll())


if __name__ == "__main__":
    unittest.main()
