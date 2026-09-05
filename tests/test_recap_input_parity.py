"""Exact approved contract checks plus receiver and original-algorithm parity tests.

Contract declarations and runtime acceptance are tested separately below.
"""

import hashlib
from pathlib import Path
import re
import unittest


CONTRACT = Path(__file__).resolve().parents[1] / "api/recap-generation-v1.yaml"
APPROVED_SHA256 = "ec93e480994203a6c8a62d5b9e9992627fba9b71ef346640ea7b80c38f62d233"


class RecapInputParityContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = CONTRACT.read_bytes()
        cls.text = cls.raw.decode("utf-8")

    def schema_block(self, name):
        # Locate a named component, without attempting to parse or validate YAML.
        match = re.search(r"^    " + re.escape(name) + r":[ \t]*(.*?)(?=^    \w+:|\Z)",
                          self.text, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_contract_matches_exact_designer_artifact(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), APPROVED_SHA256)

    def test_aggregate_has_exclusive_legacy_and_complete_branches(self):
        block = self.schema_block("AuthorPreviousMonth")
        self.assertIn("      oneOf:\n", block)
        self.assertIn("- {$ref: '#/components/schemas/LegacyAuthorPreviousMonth'}", block)
        self.assertIn("- {$ref: '#/components/schemas/CompleteAuthorPreviousMonth'}", block)
        self.assertIn("Presence of metrics_version always selects complete validation", block)
        self.assertIn("must never fall back to the legacy branch", block)

    def test_legacy_stays_closed_nonempty_and_partial(self):
        block = self.schema_block("LegacyAuthorPreviousMonth")
        self.assertIn("additionalProperties: false", block)
        self.assertIn("minProperties: 1", block)
        self.assertNotIn("required:", block)
        self.assertNotIn("metrics_version:", block)
        self.assertNotIn("total_savings:", block)
        for field in ("avg_amount", "regularity_std", "pace_bias"):
            self.assertIn(f"{field}: {{type: number, minimum: 0}}", block)

    def test_complete_is_closed_and_requires_all_metrics(self):
        block = self.schema_block("CompleteAuthorPreviousMonth")
        self.assertIn("additionalProperties: false", block)
        self.assertIn("required: [metrics_version, deposit_count, total_savings, avg_amount, "
                      "regularity_std, pace_bias, abandon_count, transfer_count, visit_count]", block)
        self.assertIn("metrics_version: {type: string, const: core-metrics-v1}", block)

    def test_count_fields_keep_safe_integer_references_in_both_branches(self):
        safe = self.schema_block("SafeInteger")
        self.assertIn("type: integer", safe)
        self.assertIn("minimum: 0", safe)
        self.assertIn("maximum: 9007199254740991", safe)
        for name in ("LegacyAuthorPreviousMonth", "CompleteAuthorPreviousMonth"):
            block = self.schema_block(name)
            for field in ("deposit_count", "abandon_count", "transfer_count", "visit_count"):
                with self.subTest(schema=name, field=field):
                    self.assertIn(f"{field}: {{$ref: '#/components/schemas/SafeInteger'}}", block)

    def test_complete_signed_nullable_and_finite_metric_declarations(self):
        block = self.schema_block("CompleteAuthorPreviousMonth")
        self.assertIn("total_savings: {type: integer, minimum: -9007199254740991, "
                      "maximum: 9007199254740991}", block)
        self.assertIn("avg_amount: {type: number, description: Finite signed average amount; "
                      "booleans are invalid.}", block)
        self.assertIn("regularity_std: {type: [number, 'null'], minimum: 0, "
                      "description: Finite nonnegative", block)
        self.assertIn("pace_bias: {type: [number, 'null'], description: Finite signed", block)

    def test_candidate_preserves_required_bounded_type_title(self):
        block = self.schema_block("SuccessStoryCandidate")
        self.assertIn("required: [wish_id, type_title, author_previous_month]", block)
        self.assertIn("type_title: {type: string, minLength: 1, maxLength: 100}", block)
        self.assertIn("author_previous_month: {$ref: '#/components/schemas/AuthorPreviousMonth'}", block)


class RecapInputParityRuntimeTest(unittest.TestCase):
    def complete(self, **changes):
        value = dict(metrics_version="core-metrics-v1", deposit_count=0, total_savings=0,
                     avg_amount=0, regularity_std=None, pace_bias=None,
                     abandon_count=0, transfer_count=0, visit_count=0)
        value.update(changes)
        return value

    def request(self, metrics):
        from tests.test_recap_service import request_for, resign, WISH
        value = request_for()
        value["input"]["success_story_candidates"] = [dict(
            wish_id=WISH, type_title="FROZEN_LEGACY_TITLE", author_previous_month=metrics)]
        return resign(value)

    def test_complete_classifier_matches_all_original_oracle_cases(self):
        import json
        from recap_service.generator import generate_recap
        from recap_service.validation import validate_request
        oracle = json.loads((CONTRACT.parents[1] / "tests/fixtures/recap-input-parity/author-metrics-oracle.json").read_text())
        for case in oracle["cases"]:
            with self.subTest(case=case["case"]):
                metrics = dict(case["metrics"])
                metrics["deposit_count"] = metrics.pop("save_count")
                request = self.request(self.complete(**metrics))
                validate_request(request, request["generation_id"])
                result = generate_recap(request)
                self.assertEqual(result["view"]["page3_academy_success_stories"]["stories"][0]["type_title"],
                                 case["classification"]["type_title"])

    def test_legacy_partial_requests_retain_title_bytes_and_digest(self):
        from copy import deepcopy
        from recap_service.generator import generate_recap
        from recap_service.validation import validate_request
        from recap_service.json_codec import canonical_bytes
        for metrics in ({"deposit_count": 8}, {"avg_amount": 12.5}, {"pace_bias": 2}):
            request = self.request(metrics)
            frozen = deepcopy(request)
            before = canonical_bytes(request)
            for _ in range(2):
                validate_request(request, request["generation_id"])
                result = generate_recap(request)
                self.assertEqual(result["view"]["page3_academy_success_stories"]["stories"][0]["type_title"], "FROZEN_LEGACY_TITLE")
            self.assertEqual(request, frozen)
            self.assertEqual(canonical_bytes(request), before)

    def test_complete_signed_safe_edges_nullable_and_unbounded_pace(self):
        from recap_service.validation import validate_request, MAX_SAFE_INTEGER
        for total in (-MAX_SAFE_INTEGER, -500, 0, MAX_SAFE_INTEGER):
            for pace in (None, -3.5, 2.5):
                request = self.request(self.complete(total_savings=total, avg_amount=-500.25, pace_bias=pace))
                self.assertIs(validate_request(request, request["generation_id"]), request)

    def test_malformed_marker_never_falls_back_and_all_fields_are_required(self):
        from recap_service.errors import InvalidRecapInput
        from recap_service.validation import validate_request
        for marker in (None, "unknown", 1, True, [], {}):
            request = self.request(self.complete(metrics_version=marker))
            with self.subTest(marker=marker), self.assertRaises(InvalidRecapInput):
                validate_request(request, request["generation_id"])
        for missing in self.complete():
            metrics = self.complete()
            del metrics[missing]
            request = self.request(metrics)
            with self.subTest(missing=missing), self.assertRaises(InvalidRecapInput):
                validate_request(request, request["generation_id"])

    def test_closed_numeric_domains_reject_bools_counts_and_nonfinite_values(self):
        from recap_service.errors import InvalidRecapInput
        from recap_service.validation import _validate_author_metrics, MAX_SAFE_INTEGER
        invalid = [dict(extra=0), dict(total_savings=MAX_SAFE_INTEGER + 1),
                   dict(total_savings=-MAX_SAFE_INTEGER - 1), dict(total_savings=1.5),
                   dict(avg_amount=None), dict(regularity_std=-1)]
        for field in ("deposit_count", "abandon_count", "transfer_count", "visit_count"):
            invalid.extend({field: value} for value in (-1, 1.5, MAX_SAFE_INTEGER + 1, None))
        for field in self.complete().keys() - {"metrics_version"}:
            invalid.append({field: True})
        for field in ("avg_amount", "regularity_std", "pace_bias"):
            invalid.extend({field: value} for value in (float("inf"), float("-inf"), float("nan"), 10**1000))
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(InvalidRecapInput):
                _validate_author_metrics(self.complete(**changes), "author")
        for legacy in ({}, {"deposit_count": 1.5}, {"pace_bias": None}, {"total_savings": 1}):
            with self.subTest(legacy=legacy), self.assertRaises(InvalidRecapInput):
                _validate_author_metrics(legacy, "author")

    def test_complete_wsgi_validation_and_frozen_retry_identity(self):
        from tests.test_recap_service import HttpApplicationTest, resign
        call = HttpApplicationTest().call
        request = self.request(self.complete(deposit_count=8, regularity_std=0))
        first = call(request)
        second = call(request)
        self.assertEqual(first[0], "200 OK")
        self.assertEqual(first[2], second[2])
        status, _, body = call(request, HTTP_IDEMPOTENCY_KEY="mismatch")
        self.assertEqual(status, "422 Unprocessable Content")
        self.assertEqual(body["code"], "RECAP_INPUT_INVALID")
        self.assertFalse(body["retryable"])
        status, _, _ = call(request, HTTP_AUTHORIZATION="Bearer wrong")
        self.assertEqual(status, "401 Unauthorized")
        request["input"]["success_story_candidates"][0]["author_previous_month"]["metrics_version"] = "invalid"
        status, _, body = call(resign(request))
        self.assertEqual(status, "422 Unprocessable Content")
        self.assertEqual(body["code"], "RECAP_INPUT_INVALID")

    def test_complete_tamper_rejected_without_normalizing_request(self):
        from copy import deepcopy
        from recap_service.validation import validate_request
        from recap_service.errors import InvalidRecapInput
        request = self.request(self.complete())
        request["input"]["success_story_candidates"][0]["author_previous_month"]["visit_count"] = 15
        before = deepcopy(request)
        with self.assertRaises(InvalidRecapInput):
            validate_request(request, request["generation_id"])
        self.assertEqual(request, before)

    def test_original_visit_messages_and_raw_visit_path_match_adapter(self):
        import json
        from datetime import datetime
        from monthly_recap import ProfileVisit
        from weekly_recap import build_page2
        from recap_service.generator import generate_recap
        from tests.test_recap_service import request_for, resign, ACCOUNT
        oracle = json.loads((CONTRACT.parents[1] / "tests/fixtures/recap-input-parity/visit-message-oracle.json").read_text())
        for case in oracle["cases"]:
            request = request_for()
            request["input"]["visit_metrics"].update(received_visit_count=case["total"],
                unique_received_visitor_count=case["unique"], previous_week_received_visit_count=case["previous"])
            raw = [ProfileVisit(str(i), ACCOUNT, "visitor" + str(i % case["unique"]), datetime(2026, 8, 25))
                   for i in range(case["total"])]
            raw += [ProfileVisit("prev"+str(i), ACCOUNT, "prev-visitor", datetime(2026, 8, 18))
                    for i in range(case["previous"])]
            original = build_page2(ACCOUNT, datetime(2026,8,24), datetime(2026,8,31), raw)
            page = generate_recap(resign(request))["view"]["page2_growth_report"]
            for field in ("message_visits", "message_growth"):
                self.assertEqual(page[field], case["original"][field])
            self.assertEqual(page, {key: value for key, value in original.items() if key != "prev_total_visits"})

    def test_legacy_huge_number_is_invalid_input_instead_of_server_failure(self):
        import json
        from recap_service.validation import _validate_author_metrics
        from recap_service.errors import InvalidRecapInput
        from tests.test_recap_service import request_for, HttpApplicationTest, WISH
        with self.assertRaises(InvalidRecapInput):
            _validate_author_metrics({"avg_amount": 10**1000}, "author")
        request = request_for()
        request["input"]["success_story_candidates"] = [dict(wish_id=WISH, type_title="legacy",
            author_previous_month={"avg_amount": 10**1000})]
        status, _, result = HttpApplicationTest().call(None, raw_body=json.dumps(request).encode())
        self.assertEqual(status, "422 Unprocessable Content")
        self.assertEqual(result["code"], "RECAP_INPUT_INVALID")

    def test_real_http_complete_signed_request_preserves_identity_and_original_type(self):
        import json
        from urllib.request import Request, urlopen
        from recap_service.json_codec import response_bytes
        from tests.real_service_harness import running_recap_service
        request = self.request(self.complete(deposit_count=1, total_savings=-500, avg_amount=-500, visit_count=15))
        with running_recap_service() as service:
            results = []
            for _ in range(2):
                call = Request(service.base_url + "/internal/v1/recap-generations", response_bytes(request),
                    {"Authorization": "Bearer " + service.token, "Content-Type": "application/json",
                     "Idempotency-Key": request["generation_id"]}, method="POST")
                with urlopen(call, timeout=5) as response:
                    results.append(json.load(response))
            self.assertEqual(results[0], results[1])
            for field in ("generation_id", "input_digest", "schema_version", "algorithm_version", "student_id",
                          "card_balance_account_id", "academy_id", "period", "kind"):
                self.assertEqual(results[0][field], request[field])
            self.assertEqual(results[0]["view"]["page3_academy_success_stories"]["stories"][0]["type_title"], "탐색형 토끼")


if __name__ == "__main__":
    unittest.main()
