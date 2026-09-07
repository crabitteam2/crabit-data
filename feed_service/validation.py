"""Closed-schema validation for feed-ranking-v1."""

from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any
from uuid import UUID

CLASSIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*@sha256:[a-f0-9]{64}$")
CATEGORIES = {"패션", "문구", "전자기기", "취미", "스포츠", "게임", "도서", "뷰티", "굿즈", "생활용품", "기타"}
METRIC_KEYS = {"deposit_count", "total_savings", "avg_amount", "regularity_std", "pace_bias", "abandon_count", "transfer_count", "visit_count"}


class InvalidInput(Exception):
    def __init__(self, paths: list[str]):
        self.paths = sorted(set(paths))[:64]


def _closed(value: Any, required: set[str], path: str, errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(path); return False
    for name in required - value.keys(): errors.append(f"{path}.{name}")
    for name in value.keys() - required: errors.append(f"{path}.{name}")
    return not ((required - value.keys()) or (value.keys() - required))


def _number(value: Any, path: str, errors: list[str], *, integer=False, low=None, high=None) -> None:
    good = isinstance(value, int if integer else (int, float)) and not isinstance(value, bool)
    if not good or not math.isfinite(float(value)) or (integer and int(value) != value) or (low is not None and value < low) or (high is not None and value > high):
        errors.append(path)


def _uuid(value: Any, path: str, errors: list[str]) -> None:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower(): raise ValueError
    except (ValueError, AttributeError): errors.append(path)


def _instant(value: Any, path: str, errors: list[str]) -> datetime | None:
    try:
        if not isinstance(value, str) or not (value.endswith("Z") or re.search(r"[+-]\d\d:\d\d$", value)): raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None: raise ValueError
        return parsed
    except (ValueError, TypeError): errors.append(path); return None


def _month_metrics(value: Any, path: str, errors: list[str]) -> None:
    keys = {"month", "coverage", "metrics_version", "values"}
    if not _closed(value, keys, path, errors): return
    if not isinstance(value["month"], str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value["month"]): errors.append(path + ".month")
    if value["coverage"] not in {"COMPLETE", "PARTIAL", "UNOBSERVED"}: errors.append(path + ".coverage")
    if value["metrics_version"] != "core-metrics-v1": errors.append(path + ".metrics_version")
    values = value["values"]
    if value["coverage"] != "COMPLETE":
        if values is not None: errors.append(path + ".values")
        return
    if not _closed(values, METRIC_KEYS, path + ".values", errors): return
    safe = 9_007_199_254_740_991
    for key in ("deposit_count", "abandon_count", "transfer_count", "visit_count"):
        _number(values[key], f"{path}.values.{key}", errors, integer=True, low=0, high=safe)
    _number(values["total_savings"], path + ".values.total_savings", errors, integer=True, low=-safe, high=safe)
    _number(values["avg_amount"], path + ".values.avg_amount", errors, low=-safe, high=safe)
    for key in ("regularity_std", "pace_bias"):
        if values[key] is not None: _number(values[key], f"{path}.values.{key}", errors, low=0 if key == "regularity_std" else None)


def validate(value: Any) -> dict[str, Any]:
    keys = {"schema_version", "request_id", "context_id", "viewer_id", "academy_id", "recommendation_at", "timezone", "feature_version", "classifier_version", "viewer_previous_month", "candidates"}
    errors: list[str] = []
    if not _closed(value, keys, "$", errors): raise InvalidInput(errors)
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool): errors.append("$.schema_version")
    for key in ("request_id", "context_id", "viewer_id", "academy_id"): _uuid(value[key], f"$.{key}", errors)
    recommendation_at = _instant(value["recommendation_at"], "$.recommendation_at", errors)
    if value["timezone"] != "Asia/Seoul": errors.append("$.timezone")
    if value["feature_version"] != "feed-features-v1": errors.append("$.feature_version")
    if not isinstance(value["classifier_version"], str) or not CLASSIFIER.fullmatch(value["classifier_version"]): errors.append("$.classifier_version")
    _month_metrics(value["viewer_previous_month"], "$.viewer_previous_month", errors)
    candidates = value["candidates"]
    if not isinstance(candidates, list) or len(candidates) > 100: errors.append("$.candidates")
    else:
        seen = set()
        required = {"card_id", "author_id", "state", "created_at", "target_date", "closed_at", "content_updated_at", "category_id", "basic_similarity", "title_similarity", "visited_author_before", "visited_category_before", "author_previous_month"}
        for index, candidate in enumerate(candidates):
            path = f"$.candidates[{index}]"
            if not _closed(candidate, required, path, errors): continue
            for key in ("card_id", "author_id"): _uuid(candidate[key], f"{path}.{key}", errors)
            if candidate["card_id"] in seen: errors.append(path + ".card_id")
            seen.add(candidate["card_id"])
            if candidate["state"] not in {"IN_PROGRESS", "AMOUNT_REACHED", "COMPLETED"}: errors.append(path + ".state")
            _instant(candidate["created_at"], path + ".created_at", errors)
            candidate["_content_updated_at"] = _instant(candidate["content_updated_at"], path + ".content_updated_at", errors)
            closed = None if candidate["closed_at"] is None else _instant(candidate["closed_at"], path + ".closed_at", errors)
            candidate["_closed_at"] = closed
            if (candidate["state"] == "COMPLETED") != (closed is not None): errors.append(path + ".closed_at")
            if candidate["target_date"] is not None:
                try: datetime.strptime(candidate["target_date"], "%Y-%m-%d")
                except (ValueError, TypeError): errors.append(path + ".target_date")
            if candidate["category_id"] not in CATEGORIES: errors.append(path + ".category_id")
            _number(candidate["basic_similarity"], path + ".basic_similarity", errors, low=0, high=1)
            if candidate["basic_similarity"] not in {0, 1 / 3, 2 / 3, 1}: errors.append(path + ".basic_similarity")
            _number(candidate["title_similarity"], path + ".title_similarity", errors, low=0, high=1)
            for key in ("visited_author_before", "visited_category_before"):
                if not isinstance(candidate[key], bool): errors.append(f"{path}.{key}")
            _month_metrics(candidate["author_previous_month"], path + ".author_previous_month", errors)
    if errors: raise InvalidInput(errors)
    value["_recommendation_at"] = recommendation_at
    return value
