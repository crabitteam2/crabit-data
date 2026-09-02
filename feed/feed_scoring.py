# -*- coding: utf-8 -*-
"""
피드 추천 시스템 - 2단계: 점수 계산
=====================================
지금은 가중합(WeightedSumScorer)으로 계산하지만, FeedScorer 프로토콜만 지키면 나중에 학습된 모델(Learning-to-Rank 등)로 교체할 수 있다.

    class MyTrainedModelScorer:
        def score(self, features: CandidateFeatures) -> float:
            return my_model.predict(features_to_array(features))

    score_and_rank_candidates(..., scorer=MyTrainedModelScorer())

이런 식으로 scorer 인자만 바꿔 끼우면 나머지 파이프라인(피처 계산, 정렬, top_n 자르기)은 그대로 재사용된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, Sequence, Optional

from monthly_recap import (
    Wish,
    SavingsTransaction,
    CoreMetrics,
    compute_core_metrics,
    classify_savings_type,
    SavingsType,
    DEFAULT_THRESHOLDS,
    Thresholds,
)
from feed.candidate_extraction import FeedCandidate


# ---------------------------------------------------------------------------
# 1. 피처 정의
# ---------------------------------------------------------------------------

@dataclass
class CandidateFeatures:
    basic_similarity: float          # 1단계: 카테고리/금액대/기간 일치 비율 (0~1)
    title_similarity: float          # 1단계: 위시 제목 문자열 유사도 (0~1)
    visited_author_before: bool      # 1단계: 작성자 방문 이력
    visited_category_before: bool    # 1단계: 방문했던 카테고리와 겹치는지
    type_relevance: float            # 저축유형 기반 적합도 (0~1)
    pace_similarity: float           # 저축 빈도(페이스) 유사도 (0~1)
    success_case_fit: float          # 완료 위시(성공사례) 여부 기반 가산 (0~1)
    recency_score: float             # 최신성 (0~1, 최근일수록 1에 가까움)
    author_type: Optional[SavingsType] = None  # 작성자의 저축 유형 (3단계 다양성 규칙에서 재사용)


# ---------------------------------------------------------------------------
# 2. 스코어러 인터페이스 (여기만 지키면 다른 구현으로 교체 가능)
# ---------------------------------------------------------------------------

class FeedScorer(Protocol):
    def score(self, features: CandidateFeatures) -> float: ...


DEFAULT_WEIGHTS: dict[str, float] = {
    "basic_similarity": 0.20,
    "title_similarity": 0.05,
    "visited_author_before": 0.10,
    "visited_category_before": 0.05,
    "type_relevance": 0.20,
    "pace_similarity": 0.10,
    "success_case_fit": 0.15,
    "recency_score": 0.15,
}


@dataclass
class WeightedSumScorer:
    """지금 단계의 기본 스코어러. weights 총합이 1일 필요는 없지만,
    해석하기 쉽도록 기본값은 1로 맞춰뒀다."""
    weights: dict[str, float] | None = None

    def __post_init__(self):
        if self.weights is None:
            self.weights = dict(DEFAULT_WEIGHTS)

    def score(self, features: CandidateFeatures) -> float:
        w = self.weights
        return (
            w["basic_similarity"] * features.basic_similarity
            + w["title_similarity"] * features.title_similarity
            + w["visited_author_before"] * float(features.visited_author_before)
            + w["visited_category_before"] * float(features.visited_category_before)
            + w["type_relevance"] * features.type_relevance
            + w["pace_similarity"] * features.pace_similarity
            + w["success_case_fit"] * features.success_case_fit
            + w["recency_score"] * features.recency_score
        )


# ---------------------------------------------------------------------------
# 3. 저축 유형 기반 적합도
#    - 나와 같은 유형: 공감할 수 있는 사례
#    - 불도저형/꾸준형: 행동을 보완할 수 있는 모범 사례
#    - 그 외: 기본값
# ---------------------------------------------------------------------------

ROLE_MODEL_TYPES = {SavingsType.BULLDOZER, SavingsType.STEADY}


def _type_relevance(viewer_type: SavingsType, candidate_type: SavingsType) -> float:
    if candidate_type == viewer_type:
        return 1.0
    if candidate_type in ROLE_MODEL_TYPES:
        return 0.7
    return 0.4


# ---------------------------------------------------------------------------
# 4. 페이스 유사도, 성공사례 적합도, 최신성
# ---------------------------------------------------------------------------

def _pace_similarity(viewer_metrics: CoreMetrics, candidate_metrics: CoreMetrics) -> float:
    """이번 달 저축 빈도(save_count)를 기준으로 한 페이스 유사도."""
    v, c = viewer_metrics.save_count, candidate_metrics.save_count
    denom = max(v, c, 1)
    return 1 - abs(v - c) / denom


def _success_case_fit(wish_status: str) -> float:
    return 1.0 if wish_status == "완료" else 0.5


def _recency_score(updated_at: datetime, now: datetime, half_life_days: float = 14) -> float:
    hours_since = max((now - updated_at).total_seconds() / 3600, 0)
    days_since = hours_since / 24
    return max(0.0, 1 - days_since / half_life_days)


# ---------------------------------------------------------------------------
# 5. 피처 계산 + 스코어링 + 랭킹
# ---------------------------------------------------------------------------

def compute_candidate_features(
    viewer_account_id: str,
    viewer_metrics: CoreMetrics,
    viewer_type: SavingsType,
    candidate: FeedCandidate,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence,
    now: datetime,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> CandidateFeatures:
    ref_year, ref_month = candidate.updated_at.year, candidate.updated_at.month
    candidate_metrics = compute_core_metrics(
        candidate.account_id, ref_year, ref_month, wishes, savings_tx, visits
    )
    candidate_classification = classify_savings_type(candidate_metrics, thresholds)

    return CandidateFeatures(
        basic_similarity=candidate.basic_similarity,
        title_similarity=candidate.title_similarity,
        visited_author_before=candidate.visited_author_before,
        visited_category_before=candidate.visited_category_before,
        type_relevance=_type_relevance(viewer_type, candidate_classification.type),
        pace_similarity=_pace_similarity(viewer_metrics, candidate_metrics),
        success_case_fit=_success_case_fit(candidate.wish_status),
        recency_score=_recency_score(candidate.updated_at, now),
        author_type=candidate_classification.type,
    )


@dataclass
class ScoredFeedCandidate:
    candidate: FeedCandidate
    features: CandidateFeatures
    score: float


def score_and_rank_candidates(
    viewer_account_id: str,
    candidates: Sequence[FeedCandidate],
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence,
    now: datetime | None = None,
    scorer: FeedScorer | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    top_n: int = 20,
) -> list[ScoredFeedCandidate]:
    """1단계에서 걸러진 후보들에 점수를 매기고, 높은 순으로 top_n개를 반환한다."""

    now = now or datetime.now()
    scorer = scorer or WeightedSumScorer()

    ref_year, ref_month = now.year, now.month
    viewer_metrics = compute_core_metrics(viewer_account_id, ref_year, ref_month, wishes, savings_tx, visits)
    viewer_classification = classify_savings_type(viewer_metrics, thresholds)

    scored: list[ScoredFeedCandidate] = []
    for candidate in candidates:
        features = compute_candidate_features(
            viewer_account_id, viewer_metrics, viewer_classification.type,
            candidate, wishes, savings_tx, visits, now, thresholds,
        )
        score = scorer.score(features)
        scored.append(ScoredFeedCandidate(candidate=candidate, features=features, score=score))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_n]