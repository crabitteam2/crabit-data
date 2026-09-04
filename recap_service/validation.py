"""Closed-schema validation for recap-generation-v1."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hmac
import math
import re
from typing import Any
from uuid import UUID

from .errors import AuthenticationRequired, InvalidRecapInput
from .json_codec import digest

MAX_SAFE_INTEGER = 9_007_199_254_740_991
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TOP_FIELDS = {
    "schema_version", "algorithm_version", "generation_id", "input_digest",
    "student_id", "card_balance_account_id", "academy_id", "kind", "period",
    "reference_date", "snapshot_at", "input",
}
INPUT_FIELDS = {
    "representative_wish_id", "wishes", "effective_transactions", "visit_metrics",
    "peer_metrics", "success_story_candidates",
}
WISH_FIELDS = {
    "wish_id", "title", "target_amount", "created_at", "closed_at", "deleted_at",
    "status", "is_representative", "saved_amount_at_period_end",
}
TX_FIELDS = {"root_event_id", "wish_id", "occurred_at", "amount", "type"}
VISIT_FIELDS = {
    "received_visit_count", "unique_received_visitor_count",
    "previous_week_received_visit_count", "monthly_outgoing_visit_count",
}
PEER_FIELDS = {"habit_active_weeks", "achievement_rates"}
STORY_FIELDS = {"wish_id", "type_title", "author_previous_month"}
AUTHOR_METRIC_FIELDS = {
    "deposit_count", "avg_amount", "regularity_std", "pace_bias", "abandon_count",
    "transfer_count", "visit_count",
}
TX_TYPES = {
    "DEPOSIT", "WITHDRAWAL", "TRANSFER_OUT", "TRANSFER_IN", "COMPLETION_RETURN",
    "ABANDONMENT_RETURN", "DELETION_RETURN",
}
WISH_STATUSES = {"IN_PROGRESS", "AMOUNT_REACHED", "COMPLETED", "ABANDONED"}


def authenticate(header: str | None, expected_token: str) -> None:
    supplied = header[7:] if header and header.startswith("Bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied.encode(), expected_token.encode()):
        raise AuthenticationRequired("A valid Bearer credential is required.")


def _closed(value: Any, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidRecapInput(f"{path} must be an object.", [path])
    missing = sorted(fields - value.keys())
    unknown = sorted(value.keys() - fields)
    if missing or unknown:
        errors = [f"{path}.{name}: required" for name in missing]
        errors += [f"{path}.{name}: unknown" for name in unknown]
        raise InvalidRecapInput(f"{path} does not match the closed schema.", errors)
    return value


def _uuid(value: Any, path: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidRecapInput(f"{path} must be a UUID.", [path]) from exc
    if str(parsed) != value.lower():
        raise InvalidRecapInput(f"{path} must use canonical UUID text.", [path])
    return value


def _date(value: Any, path: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRecapInput(f"{path} must be an ISO date.", [path]) from exc
    if parsed.isoformat() != value:
        raise InvalidRecapInput(f"{path} must use canonical ISO date text.", [path])
    return parsed


def _instant(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise InvalidRecapInput(f"{path} must be an RFC 3339 UTC Z instant.", [path])
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise InvalidRecapInput(f"{path} must be an RFC 3339 UTC Z instant.", [path]) from exc
    if parsed.tzinfo != timezone.utc:
        raise InvalidRecapInput(f"{path} must be UTC.", [path])
    return parsed


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_SAFE_INTEGER:
        raise InvalidRecapInput(f"{path} must be a nonnegative safe integer.", [path])
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise InvalidRecapInput(f"{path} must be a finite nonnegative number.", [path])
    return float(value)


def _string(value: Any, path: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise InvalidRecapInput(f"{path} must be a nonempty bounded string.", [path])
    return value


def _validate_period(value: Any, kind: str) -> None:
    period = _closed(value, {"start_date", "end_date_exclusive", "timezone"}, "period")
    start = _date(period["start_date"], "period.start_date")
    end = _date(period["end_date_exclusive"], "period.end_date_exclusive")
    if period["timezone"] != "Asia/Seoul":
        raise InvalidRecapInput("period.timezone must be Asia/Seoul.", ["period.timezone"])
    valid = start.weekday() == 0 and end == start + timedelta(days=7) if kind == "WEEKLY" else (
        start.day == 1 and end.day == 1 and (end.year * 12 + end.month) == (start.year * 12 + start.month + 1)
    )
    if not valid:
        raise InvalidRecapInput(f"period is not a complete {kind.lower()} period.", ["period"])


def _validate_input(value: Any) -> None:
    body = _closed(value, INPUT_FIELDS, "input")
    if body["representative_wish_id"] is not None:
        _uuid(body["representative_wish_id"], "input.representative_wish_id")
    if not isinstance(body["wishes"], list):
        raise InvalidRecapInput("input.wishes must be an array.", ["input.wishes"])
    seen_wishes: set[str] = set()
    for index, raw in enumerate(body["wishes"]):
        path = f"input.wishes[{index}]"
        wish = _closed(raw, WISH_FIELDS, path)
        wish_id = _uuid(wish["wish_id"], path + ".wish_id")
        if wish_id in seen_wishes:
            raise InvalidRecapInput("Wish IDs must be unique.", [path + ".wish_id"])
        seen_wishes.add(wish_id)
        _string(wish["title"], path + ".title")
        _integer(wish["target_amount"], path + ".target_amount")
        _instant(wish["created_at"], path + ".created_at")
        for name in ("closed_at", "deleted_at"):
            if wish[name] is not None:
                _instant(wish[name], path + "." + name)
        if wish["status"] not in WISH_STATUSES:
            raise InvalidRecapInput("Wish status is invalid.", [path + ".status"])
        if not isinstance(wish["is_representative"], bool):
            raise InvalidRecapInput("is_representative must be boolean.", [path + ".is_representative"])
        _integer(wish["saved_amount_at_period_end"], path + ".saved_amount_at_period_end")
    representative = body["representative_wish_id"]
    if representative is not None and representative not in seen_wishes:
        raise InvalidRecapInput("Representative Wish must occur in wishes.", ["input.representative_wish_id"])

    if not isinstance(body["effective_transactions"], list):
        raise InvalidRecapInput("input.effective_transactions must be an array.", ["input.effective_transactions"])
    seen_events: set[tuple[str, str]] = set()
    for index, raw in enumerate(body["effective_transactions"]):
        path = f"input.effective_transactions[{index}]"
        tx = _closed(raw, TX_FIELDS, path)
        root = _uuid(tx["root_event_id"], path + ".root_event_id")
        wish_id = _uuid(tx["wish_id"], path + ".wish_id")
        if wish_id not in seen_wishes:
            raise InvalidRecapInput("Transaction Wish must occur in wishes.", [path + ".wish_id"])
        if (root, wish_id) in seen_events:
            raise InvalidRecapInput("Effective event rows must be unique.", [path])
        seen_events.add((root, wish_id))
        _instant(tx["occurred_at"], path + ".occurred_at")
        if _integer(tx["amount"], path + ".amount") <= 0:
            raise InvalidRecapInput("Transaction amount must be positive.", [path + ".amount"])
        if tx["type"] not in TX_TYPES:
            raise InvalidRecapInput("Transaction type is invalid.", [path + ".type"])

    visits = _closed(body["visit_metrics"], VISIT_FIELDS, "input.visit_metrics")
    for name, item in visits.items():
        _integer(item, "input.visit_metrics." + name)
    peers = _closed(body["peer_metrics"], PEER_FIELDS, "input.peer_metrics")
    if not isinstance(peers["habit_active_weeks"], list) or not isinstance(peers["achievement_rates"], list):
        raise InvalidRecapInput("Peer metrics must be arrays.", ["input.peer_metrics"])
    for index, item in enumerate(peers["habit_active_weeks"]):
        _integer(item, f"input.peer_metrics.habit_active_weeks[{index}]")
    for index, item in enumerate(peers["achievement_rates"]):
        _number(item, f"input.peer_metrics.achievement_rates[{index}]")

    stories = body["success_story_candidates"]
    if not isinstance(stories, list) or len(stories) > 5:
        raise InvalidRecapInput("At most five success stories are allowed.", ["input.success_story_candidates"])
    for index, raw in enumerate(stories):
        path = f"input.success_story_candidates[{index}]"
        story = _closed(raw, STORY_FIELDS, path)
        _uuid(story["wish_id"], path + ".wish_id")
        _string(story["type_title"], path + ".type_title", 100)
        metrics = story["author_previous_month"]
        if not isinstance(metrics, dict) or not metrics or metrics.keys() - AUTHOR_METRIC_FIELDS:
            raise InvalidRecapInput("Author metrics must be a closed aggregate object.", [path + ".author_previous_month"])
        for name, item in metrics.items():
            _number(item, path + ".author_previous_month." + name)


def validate_request(request: dict[str, Any], idempotency_key: str | None) -> dict[str, Any]:
    _closed(request, TOP_FIELDS, "request")
    if request["schema_version"] != 1 or isinstance(request["schema_version"], bool):
        raise InvalidRecapInput("schema_version must equal 1.", ["schema_version"])
    if request["algorithm_version"] != "recap-1":
        raise InvalidRecapInput("algorithm_version must equal recap-1.", ["algorithm_version"])
    generation_id = _uuid(request["generation_id"], "generation_id")
    if idempotency_key != generation_id:
        raise InvalidRecapInput("Idempotency-Key must equal generation_id.", ["Idempotency-Key"])
    if not isinstance(request["input_digest"], str) or not DIGEST.fullmatch(request["input_digest"]):
        raise InvalidRecapInput("input_digest must be a lowercase SHA-256 digest.", ["input_digest"])
    for name in ("student_id", "card_balance_account_id", "academy_id"):
        _uuid(request[name], name)
    if request["kind"] not in {"WEEKLY", "MONTHLY"}:
        raise InvalidRecapInput("kind must be WEEKLY or MONTHLY.", ["kind"])
    _validate_period(request["period"], request["kind"])
    _date(request["reference_date"], "reference_date")
    _instant(request["snapshot_at"], "snapshot_at")
    _validate_input(request["input"])
    digestable = {key: value for key, value in request.items() if key not in {"generation_id", "input_digest"}}
    if request["input_digest"] != digest(digestable):
        raise InvalidRecapInput("input_digest does not match the request snapshot.", ["input_digest"])
    return request
