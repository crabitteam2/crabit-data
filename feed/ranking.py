"""Pure feed-rules-v1 scoring and composition for the service wire model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Sequence

from monthly_recap import CoreMetrics, SavingsType, classify_savings_type

MODEL_VERSION = "feed-rules-v1"
ROLE_MODELS = {SavingsType.BULLDOZER, SavingsType.STEADY}
WEIGHTS = {
    "basic_similarity": .20, "title_similarity": .05,
    "visited_author_before": .10, "visited_category_before": .05,
    "type_relevance": .20, "pace_similarity": .10,
    "success_case_fit": .15, "recency_score": .15,
}


@dataclass(frozen=True)
class RankedCandidate:
    value: dict[str, Any]
    score: float
    author_type: SavingsType | None
    input_position: int


def _metrics(value: dict[str, Any]) -> CoreMetrics | None:
    if value["coverage"] != "COMPLETE":
        return None
    fields = value["values"]
    return CoreMetrics(
        save_count=fields["deposit_count"], total_savings=fields["total_savings"],
        avg_amount=fields["avg_amount"], regularity_std=fields["regularity_std"],
        pace_bias=fields["pace_bias"], abandon_count=fields["abandon_count"],
        transfer_count=fields["transfer_count"], visit_count=fields["visit_count"],
    )


def _type(metrics: CoreMetrics | None) -> SavingsType | None:
    return None if metrics is None else classify_savings_type(metrics).type


def _type_relevance(viewer: SavingsType | None, author: SavingsType | None) -> float:
    if viewer is None or author is None:
        return .4
    if viewer == author:
        return 1.0
    return .7 if author in ROLE_MODELS else .4


def _pace(viewer: CoreMetrics | None, author: CoreMetrics | None) -> float:
    if viewer is None or author is None:
        return 0.0
    denominator = max(viewer.save_count, author.save_count, 1)
    return 1.0 - abs(viewer.save_count - author.save_count) / denominator


def _recency(updated: datetime, now: datetime) -> float:
    days = max((now - updated).total_seconds(), 0.0) / 86400
    return max(0.0, 1.0 - days / 14)


def score_candidates(request: dict[str, Any]) -> list[RankedCandidate]:
    now = request["_recommendation_at"]
    viewer_metrics = _metrics(request["viewer_previous_month"])
    viewer_type = _type(viewer_metrics)
    ranked: list[RankedCandidate] = []
    for position, candidate in enumerate(request["candidates"]):
        author_metrics = _metrics(candidate["author_previous_month"])
        author_type = _type(author_metrics)
        features = {
            "basic_similarity": candidate["basic_similarity"],
            "title_similarity": candidate["title_similarity"],
            "visited_author_before": float(candidate["visited_author_before"]),
            "visited_category_before": float(candidate["visited_category_before"]),
            "type_relevance": _type_relevance(viewer_type, author_type),
            "pace_similarity": _pace(viewer_metrics, author_metrics),
            "success_case_fit": 1.0 if candidate["state"] == "COMPLETED" else .5,
            "recency_score": _recency(candidate["_content_updated_at"], now),
        }
        # Explicit binary64 left fold: Python 3.12+ sum uses compensated
        # arithmetic, which changes near-tie ordering across runtimes.
        score = 0.0
        for name, value in features.items():
            score += WEIGHTS[name] * value
        if not math.isfinite(score):
            raise ValueError("candidate score is not finite")
        ranked.append(RankedCandidate(candidate, score, author_type, position))
    return sorted(ranked, key=lambda item: (-item.score, item.input_position))


def _redundancy(left: RankedCandidate, right: RankedCandidate) -> float:
    result = 1.0 if left.value["category_id"] == right.value["category_id"] else 0.0
    if left.value["author_id"] == right.value["author_id"]:
        result = max(result, .8)
    return result


def _mmr(scored: Sequence[RankedCandidate], size: int) -> list[RankedCandidate]:
    remaining = list(scored)
    selected: list[RankedCandidate] = []
    while remaining and len(selected) < size:
        if not selected:
            selected.append(remaining.pop(0))
            continue
        best = max(range(len(remaining)), key=lambda i: (
            .7 * remaining[i].score - .3 * max(_redundancy(remaining[i], old) for old in selected),
            -remaining[i].input_position,
        ))
        selected.append(remaining.pop(best))
    return selected


def _recent(item: RankedCandidate, now: datetime) -> bool:
    closed = item.value["_closed_at"]
    return item.value["state"] == "COMPLETED" and closed is not None and 0 <= (now - closed).total_seconds() <= 172800


def _role(item: RankedCandidate) -> bool:
    return item.value["state"] == "COMPLETED" and item.author_type in ROLE_MODELS


def _replace_weakest(result: list[RankedCandidate], candidate: RankedCandidate, window: int | None = None) -> None:
    if candidate in result:
        return
    upper = min(len(result), window or len(result))
    choices = [i for i in range(upper) if not _role(result[i])]
    if not choices:
        choices = list(range(upper))
    if choices:
        result[min(choices, key=lambda i: (result[i].score, -result[i].input_position))] = candidate


def _spacing(items: Sequence[RankedCandidate]) -> list[RankedCandidate]:
    pool, result = list(items), []
    while pool:
        blocked = result[-1].value["category_id"] if len(result) >= 2 and result[-1].value["category_id"] == result[-2].value["category_id"] else None
        index = next((i for i, item in enumerate(pool) if item.value["category_id"] != blocked), 0)
        result.append(pool.pop(index))
    return result


def rank(request: dict[str, Any]) -> list[str]:
    scored = score_candidates(request)
    if not scored:
        return []
    # Protect guarantee candidates while taking the score-ranked intermediate 40.
    pool = list(scored[:40])
    protected = []
    recent = next((item for item in scored if _recent(item, request["_recommendation_at"])), None)
    if recent is not None:
        protected.append(recent)
    protected.extend(item for item in scored if _role(item))
    for item in protected:
        if item not in pool:
            pool[-1] = item
    unique = {item.value["card_id"]: item for item in pool}
    pool = sorted(unique.values(), key=lambda item: (-item.score, item.input_position))
    result = _mmr(pool, min(20, len(scored)))
    if recent is not None and not any(_recent(item, request["_recommendation_at"]) for item in result):
        _replace_weakest(result, recent)
    available_roles = [item for item in scored if _role(item)]
    target = min(2, len(available_roles), len(result), 10)
    for item in available_roles:
        if sum(_role(x) for x in result[:10]) >= target:
            break
        if item in result:
            old = result.index(item)
            new = next((i for i in range(min(10, len(result))) if not _role(result[i])), None)
            if new is not None:
                result[old], result[new] = result[new], result[old]
        else:
            _replace_weakest(result, item, 10)
    result = _spacing(result)
    # Spacing may move role models out of top 10; guarantees take precedence.
    for item in available_roles:
        if sum(_role(x) for x in result[:10]) >= target:
            break
        if item in result[10:]:
            new = next(i for i in range(min(10, len(result))) if not _role(result[i]))
            old = result.index(item)
            result[old], result[new] = result[new], result[old]
    if recent is not None and recent not in result:
        _replace_weakest(result, recent)
    return [item.value["card_id"] for item in result]
