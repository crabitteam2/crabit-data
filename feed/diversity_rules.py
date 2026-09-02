# -*- coding: utf-8 -*-
"""
피드 추천 시스템 - 3단계: 다양성 및 규칙 적용
================================================
2단계에서 점수 매겨진 후보들을 받아서 아래 순서로 보정한 뒤 최종 노출 목록을 만든다.

    1. MMR(Maximal Marginal Relevance): 관련성과 다양성을 함께 고려해 초안 순서 생성
    2. 최근 48시간 내 달성된 완료 피드 강제 포함 (초안에 없으면 끼워넣기)
    3. 상위 10개 중 '불도저형'/'꾸준형' 모범 달성 피드 최소 2개 보장
    4. 동일 카테고리 연속 2개 제한 (마지막에 순서만 재배치, 구성은 유지)

2, 3번은 '어떤 피드가 포함되는가'(구성)를 바꾸고, 4번은 '어떤 순서로 보여주는가'만 바꾼다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from monthly_recap import SavingsType
from feed.feed_scoring import ScoredFeedCandidate

ROLE_MODEL_TYPES = {SavingsType.BULLDOZER, SavingsType.STEADY}


@dataclass
class DiversityRuleConfig:
    final_size: int = 20
    mmr_lambda: float = 0.7                 # 1에 가까울수록 관련성 중시, 0에 가까울수록 다양성 중시
    max_consecutive_same_category: int = 2
    recent_hours_for_forced_slot: float = 48
    forced_slot_position: int = 2           # 강제 포함 피드를 넣을 위치 (0-indexed)
    min_role_model_in_top: int = 2
    top_window: int = 10                    # '상위 10개' 기준


# ---------------------------------------------------------------------------
# 1. MMR
# ---------------------------------------------------------------------------

def _redundancy(a: ScoredFeedCandidate, b: ScoredFeedCandidate) -> float:
    """두 피드가 얼마나 겹치는지(중복도). 같은 카테고리면 1, 같은 작성자면 더 겹치는 것으로 간주."""
    sim = 1.0 if a.candidate.wish_category == b.candidate.wish_category else 0.0
    if a.candidate.account_id == b.candidate.account_id:
        sim = max(sim, 0.8)
    return sim


def apply_mmr(
    scored: Sequence[ScoredFeedCandidate], k: int, lam: float
) -> list[ScoredFeedCandidate]:
    """MMR로 관련성과 다양성을 함께 고려해 k개를 순서대로 선택한다."""
    remaining = sorted(scored, key=lambda s: s.score, reverse=True)
    selected: list[ScoredFeedCandidate] = []

    if not remaining:
        return selected

    selected.append(remaining.pop(0))  # 가장 관련성 높은 것부터 시작

    while remaining and len(selected) < k:
        best_idx, best_mmr = None, float("-inf")
        for i, cand in enumerate(remaining):
            max_sim = max(_redundancy(cand, s) for s in selected)
            mmr_score = lam * cand.score - (1 - lam) * max_sim
            if mmr_score > best_mmr:
                best_mmr, best_idx = mmr_score, i
        selected.append(remaining.pop(best_idx))

    return selected


# ---------------------------------------------------------------------------
# 2. 최근 48시간 내 완료 피드 강제 슬롯
# ---------------------------------------------------------------------------

def _is_recent_completion(s: ScoredFeedCandidate, now: datetime, recent_hours: float) -> bool:
    if s.candidate.wish_status != "완료":
        return False
    hours = (now - s.candidate.updated_at).total_seconds() / 3600
    return 0 <= hours <= recent_hours


def ensure_recent_completion_slot(
    ordered: list[ScoredFeedCandidate],
    all_scored: Sequence[ScoredFeedCandidate],
    now: datetime,
    recent_hours: float,
    forced_slot_position: int,
) -> list[ScoredFeedCandidate]:
    if any(_is_recent_completion(s, now, recent_hours) for s in ordered):
        return ordered  # 이미 자연스럽게 포함됨

    candidates_recent = [s for s in all_scored if _is_recent_completion(s, now, recent_hours)]
    if not candidates_recent:
        return ordered  # 최근 48시간 내 달성 피드 자체가 없으면 강제할 수 없음

    best = max(candidates_recent, key=lambda s: s.score)
    result = list(ordered)
    result.pop()  # 길이를 유지하기 위해 맨 끝(가장 약한 후보)을 하나 밀어냄
    insert_at = min(forced_slot_position, len(result))
    result.insert(insert_at, best)
    return result


# ---------------------------------------------------------------------------
# 3. 상위 N개 중 모범 달성 피드 최소 보장
# ---------------------------------------------------------------------------

def _is_role_model_success(s: ScoredFeedCandidate) -> bool:
    return s.features.author_type in ROLE_MODEL_TYPES and s.candidate.wish_status == "완료"


def ensure_role_model_in_top(
    ordered: list[ScoredFeedCandidate],
    all_scored: Sequence[ScoredFeedCandidate],
    top_window: int,
    min_count: int,
) -> list[ScoredFeedCandidate]:
    top_slice = ordered[:top_window]
    current_count = sum(1 for s in top_slice if _is_role_model_success(s))
    if current_count >= min_count:
        return ordered  # 이미 상위 10개 안에 최소 개수 충족

    needed = min_count - current_count
    result = list(ordered)
    top_feed_ids = {s.candidate.feed_id for s in result[:top_window]}

    # 1. 11위 이하(ordered[top_window:])에 이미 들어와 있는 모범 피드가 있는지 먼저 탐색
    rest_in_ordered = [
        s for s in result[top_window:] if _is_role_model_success(s)
    ]

    # 2. 그래도 부족하면 전체 풀(all_scored) 중 아직 리스트에 없는 모범 피드 탐색
    all_included_ids = {s.candidate.feed_id for s in result}
    outside_candidates = sorted(
        (s for s in all_scored
         if s.candidate.feed_id not in all_included_ids and _is_role_model_success(s)),
        key=lambda s: s.score, reverse=True,
    )

    # 투입할 모범 피드 후보군 확정 (내부 11위 이하 것 우선 -> 외부 것)
    candidates_to_promote = rest_in_ordered + outside_candidates
    if not candidates_to_promote:
        return ordered  # 가져올 수 있는 모범 피드 자체가 없으면 유지

    to_insert = candidates_to_promote[:needed]

    # 3. top_window(상위 10개) 내에서 모범 피드가 아니며 점수가 가장 낮은 피드의 '위치' 찾기
    replaceable_positions = sorted(
        (i for i in range(min(top_window, len(result))) if not _is_role_model_success(result[i])),
        key=lambda i: result[i].score,
    )

    # 4. 안전하게 교체 및 재배치 (밀려난 피드는 뒤로 보내기)
    for pos, new_cand in zip(replaceable_positions, to_insert):
        # 이미 11위 이하에 있던 피드를 올리는 경우, 중복 방지를 위해 기존 위치에서 제거
        if new_cand in result[top_window:]:
            result.remove(new_cand)
        
        # 10위 안에 있던 기존 피드를 꺼내서 맨 뒤로 보냄 (피드 영구 유실 방지)
        displaced = result.pop(pos)
        result.insert(pos, new_cand)
        result.append(displaced)

    return result


# ---------------------------------------------------------------------------
# 4. 동일 카테고리 연속 제한 (구성은 그대로, 순서만 재배치)
# ---------------------------------------------------------------------------

def enforce_category_spacing(
    ordered: Sequence[ScoredFeedCandidate], max_consecutive: int
) -> list[ScoredFeedCandidate]:
    pool = list(ordered)  # 앞쪽일수록 우선순위 높음 (기존 순서 유지)
    result: list[ScoredFeedCandidate] = []

    while pool:
        recent_categories = [s.candidate.wish_category for s in result[-max_consecutive:]]
        blocked_category = None
        if len(recent_categories) == max_consecutive and len(set(recent_categories)) == 1:
            blocked_category = recent_categories[0]

        chosen_idx = 0
        if blocked_category is not None:
            for i, cand in enumerate(pool):
                if cand.candidate.wish_category != blocked_category:
                    chosen_idx = i
                    break
            else:
                chosen_idx = 0  # 전부 같은 카테고리만 남았다면 규칙을 깰 수밖에 없음

        result.append(pool.pop(chosen_idx))

    return result


# ---------------------------------------------------------------------------
# 5. 최상위 오케스트레이션
# ---------------------------------------------------------------------------

def apply_diversity_and_rules(
    scored: Sequence[ScoredFeedCandidate],
    now: datetime,
    config: DiversityRuleConfig = DiversityRuleConfig(),
) -> list[ScoredFeedCandidate]:
    """2단계 점수 결과를 받아 3단계 규칙을 전부 적용한 최종 노출 목록을 반환한다."""

    mmr_pool_size = min(len(scored), max(config.final_size * 3, 40))
    mmr_input = sorted(scored, key=lambda s: s.score, reverse=True)[:mmr_pool_size]

    diversified = apply_mmr(mmr_input, k=min(config.final_size, len(mmr_input)), lam=config.mmr_lambda)

    with_recent = ensure_recent_completion_slot(
        diversified, scored, now, config.recent_hours_for_forced_slot, config.forced_slot_position
    )
    with_role_models = ensure_role_model_in_top(
        with_recent, scored, config.top_window, config.min_role_model_in_top
    )
    final = enforce_category_spacing(with_role_models, config.max_consecutive_same_category)

    return final[: config.final_size]