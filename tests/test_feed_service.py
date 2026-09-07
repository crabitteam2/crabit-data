import io
import json
import unittest

from feed_service.app import create_app


def metrics(coverage="COMPLETE", deposits=0):
    return {"month": "2026-02", "coverage": coverage, "metrics_version": "core-metrics-v1", "values": None if coverage != "COMPLETE" else {"deposit_count": deposits, "total_savings": deposits * 1000, "avg_amount": 1000 if deposits else 0, "regularity_std": 1 if deposits > 1 else None, "pace_bias": None, "abandon_count": 0, "transfer_count": 0, "visit_count": 0}}


def request(candidates=None):
    return {"schema_version": 1, "request_id": "11111111-1111-4111-8111-111111111111", "context_id": "22222222-2222-4222-8222-222222222222", "viewer_id": "33333333-3333-4333-8333-333333333333", "academy_id": "44444444-4444-4444-8444-444444444444", "recommendation_at": "2026-03-10T03:00:00Z", "timezone": "Asia/Seoul", "feature_version": "feed-features-v1", "classifier_version": "wish-category-v1@sha256:" + "a" * 64, "viewer_previous_month": metrics(deposits=5), "candidates": candidates or []}


def candidate(number, *, state="IN_PROGRESS", closed=None, category="기타", deposits=0):
    value = str(number).zfill(12)
    return {"card_id": f"00000000-0000-4000-8000-{value}", "author_id": f"10000000-0000-4000-8000-{value}", "state": state, "created_at": "2026-02-01T00:00:00Z", "target_date": None, "closed_at": closed, "content_updated_at": "2026-03-09T00:00:00Z", "category_id": category, "basic_similarity": 0, "title_similarity": 0, "visited_author_before": False, "visited_category_before": False, "author_previous_month": metrics(deposits=deposits)}


class FeedServiceTest(unittest.TestCase):
    def call(self, raw, token="secret", path="/internal/v1/feed-rankings"):
        body = raw if isinstance(raw, bytes) else json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()
        captured = {}
        environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path, "QUERY_STRING": "", "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(body)), "HTTP_AUTHORIZATION": "Bearer " + token, "wsgi.input": io.BytesIO(body)}
        output = b"".join(create_app("secret")(environ, lambda status, headers: captured.update(status=status, headers=dict(headers))))
        return int(captured["status"].split()[0]), captured, json.loads(output)

    def test_empty_request_returns_bound_digest(self):
        status, response, body = self.call(request())
        self.assertEqual(status, 200)
        self.assertEqual(body["ordered_card_ids"], [])
        self.assertEqual(body["request_id"], request()["request_id"])
        self.assertTrue(body["input_digest"].startswith("sha256:"))
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_auth_and_closed_duplicate_json_fail_closed(self):
        self.assertEqual(self.call(request(), token="bad")[0], 401)
        raw = b'{"schema_version":1,"schema_version":1}'
        self.assertEqual(self.call(raw)[2]["code"], "MALFORMED_REQUEST")
        invalid = request(); invalid["unknown"] = True
        self.assertEqual(self.call(invalid)[2]["code"], "INVALID_FEED_INPUT")

    def test_recent_and_two_role_models_survive_final_composition(self):
        values = [candidate(i, category="패션") for i in range(1, 45)]
        values += [candidate(90, state="COMPLETED", closed="2026-03-09T03:00:00Z", deposits=8), candidate(91, state="COMPLETED", closed="2026-02-01T00:00:00Z", deposits=8)]
        status, _, body = self.call(request(values))
        self.assertEqual(status, 200)
        self.assertEqual(len(body["ordered_card_ids"]), 20)
        self.assertEqual(len(set(body["ordered_card_ids"])), 20)
        self.assertIn(values[-2]["card_id"], body["ordered_card_ids"])
        self.assertTrue({values[-2]["card_id"], values[-1]["card_id"]}.issubset(body["ordered_card_ids"][:10]))


if __name__ == "__main__": unittest.main()
