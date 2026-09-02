# -*- coding: utf-8 -*-
"""
피드 추천 시스템 - 1단계: 후보 추출
=====================================
연산이 가벼운 피처로 연관성 높은 피드만 빠르게 걸러내는 게 목적이라, 학습 모델이 아니라 고정된 규칙(카테고리/금액대/기간 일치 + 과거 방문 여부)으로 계산한다.

기준:
- 사용자 벡터 = 사용자의 대표 위시 (get_representative_wish: 명시적 대표 위시 없으면
  진행중인 위시 중 가장 먼저 생성된 것)
- 후보 풀 = 같은 학원 전체 피드 (친구 개념 없음)
- 기본 속성 유사도 = 위시 카테고리 / 금액대 / 기간, 3개 중 몇 개가 일치하는지 (0, 1/3, 2/3, 1)
  -> 이는 3차원을 원-핫으로 이어붙인 벡터의 코사인 유사도와 수학적으로 동일하다.
- 텍스트 유사도 = 위시 제목 문자열 유사도 (difflib, 외부 의존성 없음)
- 과거 방문 신호 = 이 피드 작성자를 방문한 적 있는지 / 방문했던 계정들의 위시 카테고리와
  겹치는지 (가벼운 휴리스틱)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional, Sequence

from monthly_recap import Wish, CardAccount, get_representative_wish
from weekly_recap import FeedPost
from wish_category_classifier import classify_wish_category


# ---------------------------------------------------------------------------
# 1. 금액대 / 기간 버킷 정의
# ---------------------------------------------------------------------------

AMOUNT_BUCKETS: list[tuple[float, str]] = [
    (10_000, "1만원 미만"),
    (30_000, "1~3만원"),
    (50_000, "3~5만원"),
    (100_000, "5~10만원"),
    (300_000, "10~30만원"),
    (float("inf"), "30만원 이상"),
]

DURATION_BUCKETS_DAYS: list[tuple[float, str]] = [
    (30, "1개월 이내"),
    (90, "1~3개월"),
    (180, "3~6개월"),
    (float("inf"), "6개월 이상"),
]
NO_DEADLINE_LABEL = "기한 미설정"


def _amount_bucket(amount: int) -> str:
    for threshold, label in AMOUNT_BUCKETS:
        if amount < threshold:
            return label
    return AMOUNT_BUCKETS[-1][1]


def _duration_bucket(wish: Wish) -> str:
    """target_date - created_at(일) 기준 버킷. 기한 미설정이면 별도 라벨."""
    if wish.target_date is None:
        return NO_DEADLINE_LABEL
    days = (wish.target_date - wish.created_at.date()).days
    for threshold, label in DURATION_BUCKETS_DAYS:
        if days < threshold:
            return label
    return DURATION_BUCKETS_DAYS[-1][1]


# ---------------------------------------------------------------------------
# 2. 후보 결과 자료구조
# ---------------------------------------------------------------------------

@dataclass
class FeedCandidate:
    feed_id: str
    account_id: str
    wish_id: str
    wish_title: str
    wish_category: str
    wish_status: str
    kind: str
    updated_at: datetime

    basic_similarity: float       # 카테고리/금액대/기간 3개 중 일치 비율 (0, 1/3, 2/3, 1)
    title_similarity: float       # 위시 제목 문자열 유사도 (0~1)
    visited_author_before: bool   # 이 작성자를 과거에 방문한 적 있는지
    visited_category_before: bool  # 과거 방문했던 계정들의 위시와 카테고리가 겹치는지

    relevance_score: float        # 위 신호들을 가볍게 합친 필터링용 점수 (최종 랭킹 점수 아님)


# ---------------------------------------------------------------------------
# 3. 후보 추출 가중치 (필터링용 — 2단계의 최종 점수와는 별개)
# ---------------------------------------------------------------------------

WEIGHT_BASIC_SIMILARITY = 0.4
WEIGHT_TITLE_SIMILARITY = 0.2
WEIGHT_VISITED_AUTHOR = 0.25
WEIGHT_VISITED_CATEGORY = 0.15


def extract_candidates(
    viewer_account_id: str,
    academy_id: str,
    feed_posts: Sequence[FeedPost],
    wishes: Sequence[Wish],
    visits: Sequence,  # ProfileVisit
    card_accounts: Sequence[CardAccount],
    top_n: int = 100,
) -> list[FeedCandidate]:
    """같은 학원 피드 전체에서, 사용자와 관련성이 높은 순으로 top_n개만 골라 2단계로 넘긴다."""

    wish_by_id = {w.wish_id: w for w in wishes}
    account_by_id = {a.account_id: a for a in card_accounts}

    # 사용자 벡터: 대표 위시(없으면 진행중 위시 중 최초 생성) 기준
    viewer_wish = get_representative_wish(viewer_account_id, wishes)
    if viewer_wish is not None:
        viewer_category = classify_wish_category(viewer_wish.title)
        viewer_amount_bucket = _amount_bucket(viewer_wish.target_amount)
        viewer_duration_bucket = _duration_bucket(viewer_wish)
    else:
        viewer_category = viewer_amount_bucket = viewer_duration_bucket = None

    # 과거 방문 정보: 이 사용자가 방문했던 계정들 + 그 계정들 위시의 카테고리
    visited_accounts = {
        v.visited_account_id for v in visits if v.visitor_account_id == viewer_account_id
    }
    visited_categories = {
        classify_wish_category(w.title)
        for w in wishes
        if w.account_id in visited_accounts and w.deleted_at is None
    }

    candidates: list[FeedCandidate] = []
    for fp in feed_posts:
        if fp.account_id == viewer_account_id:
            continue  # 본인 피드는 추천 대상에서 제외

        account = account_by_id.get(fp.account_id)
        if account is None or account.academy_id != academy_id:
            continue  # 같은 학원 피드만 대상 (친구 개념 없음)

        wish = wish_by_id.get(fp.wish_id)
        if wish is None or wish.deleted_at is not None:
            continue

        candidate_category = classify_wish_category(wish.title)
        candidate_amount_bucket = _amount_bucket(wish.target_amount)
        candidate_duration_bucket = _duration_bucket(wish)

        if viewer_wish is not None:
            match_count = sum([
                candidate_category == viewer_category,
                candidate_amount_bucket == viewer_amount_bucket,
                candidate_duration_bucket == viewer_duration_bucket,
            ])
            basic_similarity = match_count / 3
            title_similarity = SequenceMatcher(None, viewer_wish.title, wish.title).ratio()
        else:
            # 사용자에게 진행중인 위시가 하나도 없는 경우 (신규 유저 등):
            # 속성 기반 유사도는 계산 불가 -> 과거 방문 신호만으로 후보를 추린다.
            basic_similarity = 0.0
            title_similarity = 0.0

        visited_author_before = fp.account_id in visited_accounts
        visited_category_before = candidate_category in visited_categories

        relevance_score = (
            WEIGHT_BASIC_SIMILARITY * basic_similarity
            + WEIGHT_TITLE_SIMILARITY * title_similarity
            + WEIGHT_VISITED_AUTHOR * float(visited_author_before)
            + WEIGHT_VISITED_CATEGORY * float(visited_category_before)
        )

        candidates.append(FeedCandidate(
            feed_id=fp.feed_id,
            account_id=fp.account_id,
            wish_id=wish.wish_id,
            wish_title=wish.title,
            wish_category=candidate_category,
            wish_status=wish.status.value,
            kind=fp.kind,
            updated_at=fp.updated_at,
            basic_similarity=basic_similarity,
            title_similarity=title_similarity,
            visited_author_before=visited_author_before,
            visited_category_before=visited_category_before,
            relevance_score=relevance_score,
        ))

    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    return candidates[:top_n]