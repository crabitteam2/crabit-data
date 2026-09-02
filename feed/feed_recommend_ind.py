# -*- coding: utf-8 -*-
"""
피드 추천 시스템 - 메인 실행 모듈 (feed/feed_recommend.py)
- 특정 한명의 피드 추천 목록을 추출합니다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, date
from typing import Sequence, Optional

# ---------------------------------------------------------------------------
# 0. 경로 설정 (feed 폴더 내부 실행 및 상위 폴더 모듈 참조 보장)
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent

for path_str in [str(ROOT_DIR), str(CURRENT_DIR)]:
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from monthly_recap import (
    Wish,
    WishStatus,
    SavingsTransaction,
    TransactionType,
    ProfileVisit,
    CardAccount,
    Thresholds,
    DEFAULT_THRESHOLDS,
)
from weekly_recap import FeedPost
from feed.candidate_extraction import extract_candidates
from feed.feed_scoring import score_and_rank_candidates
from feed.diversity_rules import apply_diversity_and_rules, DiversityRuleConfig


# ---------------------------------------------------------------------------
# 1. 파이썬 표준 csv 모듈 기반 데이터 로더
# ---------------------------------------------------------------------------

# savings_transactions.csv의 event_type 문자열 -> TransactionType Enum 매핑
TRANSACTION_TYPE_MAP = {
    "WISH_DEPOSIT": TransactionType.DEPOSIT,
    "WISH_WITHDRAWAL": TransactionType.WITHDRAWAL,
    "WISH_TRANSFER": TransactionType.TRANSFER_OUT,
    "입금": TransactionType.DEPOSIT,
    "출금": TransactionType.WITHDRAWAL,
    "이체출": TransactionType.TRANSFER_OUT,
    "이체입": TransactionType.TRANSFER_IN,
    "환급": TransactionType.REFUND,
}


def _parse_datetime(val: Optional[str]) -> Optional[datetime]:
    if not val or not val.strip():
        return None
    return datetime.fromisoformat(val.strip())


def _parse_date(val: Optional[str]) -> Optional[date]:
    if not val or not val.strip():
        return None
    return date.fromisoformat(val.strip().split()[0])


def load_all_data(data_dir: Path | str = ROOT_DIR / "data"):
    """data 폴더 내의 CSV 파일들을 순수 csv 모듈로 파싱하여 dataclass 리스트로 변환"""
    data_path = Path(data_dir)

    # 1) wishes.csv
    with open(data_path / "wishes.csv", mode="r", encoding="utf-8-sig") as f:
        wishes = [
            Wish(
                wish_id=r["wish_id"].strip(),
                account_id=r["account_id"].strip(),
                academy_id=r["academy_id"].strip(),
                title=r["title"].strip(),
                target_amount=int(r["target_amount"]),
                target_date=_parse_date(r.get("target_date")),
                is_representative=(r.get("is_representative", "").strip().upper() == "TRUE"),
                status=WishStatus(r["status"].strip()),
                created_at=_parse_datetime(r["created_at"]),
                closed_at=_parse_datetime(r.get("closed_at")),
                deleted_at=_parse_datetime(r.get("deleted_at")),
                saved_amount=int(r["saved_amount"]) if r.get("saved_amount", "").strip() else 0,
            )
            for r in csv.DictReader(f)
        ]

    # 2) savings_transactions.csv
    with open(data_path / "savings_transactions.csv", mode="r", encoding="utf-8-sig") as f:
        savings_tx = [
            SavingsTransaction(
                transaction_id=r["transaction_id"].strip(),
                account_id=r["account_id"].strip(),
                wish_id=r["wish_id"].strip(),
                type=TRANSACTION_TYPE_MAP.get(r.get("event_type") or r.get("type"), TransactionType.DEPOSIT),
                amount=int(r["amount"]),
                created_at=_parse_datetime(r["created_at"]),
            )
            for r in csv.DictReader(f)
        ]

    # 3) card_accounts.csv
    with open(data_path / "card_accounts.csv", mode="r", encoding="utf-8-sig") as f:
        card_accounts = [
            CardAccount(
                account_id=r["account_id"].strip(),
                user_id=r["user_id"].strip(),
                academy_id=r["academy_id"].strip(),
                created_at=_parse_datetime(r["created_at"]),
                closed_at=_parse_datetime(r.get("closed_at")),
            )
            for r in csv.DictReader(f)
        ]

    # 4) feed_posts.csv
    with open(data_path / "feed_posts.csv", mode="r", encoding="utf-8-sig") as f:
        feed_posts = [
            FeedPost(
                feed_id=r["feed_id"].strip(),
                account_id=r["account_id"].strip(),
                wish_id=r["wish_id"].strip(),
                kind=r["kind"].strip(),
                updated_at=_parse_datetime(r["updated_at"]),
            )
            for r in csv.DictReader(f)
        ]

    # 5) profile_visits.csv
    with open(data_path / "profile_visits.csv", mode="r", encoding="utf-8-sig") as f:
        visits = [
            ProfileVisit(
                visit_id=r["visit_id"].strip(),
                visited_account_id=r["visited_account_id"].strip(),
                visitor_account_id=r["visitor_account_id"].strip(),
                created_at=_parse_datetime(r["created_at"]),
            )
            for r in csv.DictReader(f)
        ]

    return wishes, savings_tx, card_accounts, feed_posts, visits


# ---------------------------------------------------------------------------
# 2. 추천 파이프라인 함수
# ---------------------------------------------------------------------------

def recommend_feeds(
    viewer_account_id: str,
    academy_id: str,
    feed_posts: Sequence[FeedPost],
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence[ProfileVisit],
    card_accounts: Sequence[CardAccount],
    now: datetime | None = None,
    rule_config: DiversityRuleConfig | None = None,
):
    now = now or datetime.now()
    rule_config = rule_config or DiversityRuleConfig()

    # [1단계] 후보 추출
    candidates = extract_candidates(
        viewer_account_id=viewer_account_id,
        academy_id=academy_id,
        feed_posts=feed_posts,
        wishes=wishes,
        visits=visits,
        card_accounts=card_accounts,
        top_n=100,
    )
    if not candidates:
        return []

    # [2단계] 점수 계산 및 랭킹
    scored = score_and_rank_candidates(
        viewer_account_id=viewer_account_id,
        candidates=candidates,
        wishes=wishes,
        savings_tx=savings_tx,
        visits=visits,
        now=now,
        top_n=40,
    )

    # [3단계] 다양성 및 규칙 적용
    final_recommendations = apply_diversity_and_rules(
        scored=scored,
        now=now,
        config=rule_config,
    )
    return final_recommendations


# ---------------------------------------------------------------------------
# 3. 직접 실행부
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    data_dir = ROOT_DIR / "data"

    if not data_dir.exists():
        print(f"[오류] 데이터 폴더({data_dir})를 찾을 수 없습니다.")
        sys.exit(1)

    print(f"[*] '{data_dir}' 폴더에서 데이터 로딩 중 (표준 csv 모듈 사용)...")
    wishes, savings_tx, card_accounts, feed_posts, visits = load_all_data(data_dir)
    print(f"    - 위시: {len(wishes)}건 / 거래: {len(savings_tx)}건 / 피드: {len(feed_posts)}건")

    # card_accounts의 첫 번째 학생 계정으로 테스트 실행
    target_student = card_accounts[0]
    viewer_id = target_student.account_id
    academy_id = target_student.academy_id

    # 데이터 기준 최신 일시로 시뮬레이션
    ref_now = max(fp.updated_at for fp in feed_posts)

    print(f"[*] 학생 계정 '{viewer_id}' (학원: {academy_id}) 대상 피드 추천 계산 중...")
    recommendations = recommend_feeds(
        viewer_account_id=viewer_id,
        academy_id=academy_id,
        feed_posts=feed_posts,
        wishes=wishes,
        savings_tx=savings_tx,
        visits=visits,
        card_accounts=card_accounts,
        now=ref_now,
    )

    print(f"\n====================== [최종 추천 피드 목록 ({len(recommendations)}개)] ======================")
    for rank, item in enumerate(recommendations, 1):
        c = item.candidate
        print(
            f"{rank:2d}위 | [Feed {c.feed_id}] {c.wish_title:<10s} | "
            f"카테고리: {c.wish_category:<6s} | 상태: {c.wish_status} | 점수: {item.score:.3f}"
        )