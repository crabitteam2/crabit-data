# -*- coding: utf-8 -*-
"""
피드 추천 시스템 - 메인 실행 모듈 (feed/feed_recommend.py)
- 학원 전체 학생의 추천 피드 ID 순서 목록을 JSON으로 추출합니다.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from datetime import datetime, date
from typing import Sequence, Optional, Dict, List, Any

# ---------------------------------------------------------------------------
# 0. 경로 설정
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
)
from weekly_recap import FeedPost
from feed.candidate_extraction import extract_candidates
from feed.feed_scoring import score_and_rank_candidates, ScoredFeedCandidate
from feed.diversity_rules import apply_diversity_and_rules, DiversityRuleConfig


# ---------------------------------------------------------------------------
# 1. 파이썬 표준 csv 모듈 기반 데이터 로더
# ---------------------------------------------------------------------------

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
# 2. 추천 파이프라인
# ---------------------------------------------------------------------------

def recommend_feeds_for_student(
    viewer_account_id: str,
    academy_id: str,
    feed_posts: Sequence[FeedPost],
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence[ProfileVisit],
    card_accounts: Sequence[CardAccount],
    now: datetime,
    rule_config: DiversityRuleConfig | None = None,
) -> list[str]:
    """학생 1명에 대해 파이프라인을 실행하고 최종 피드 ID 리스트(순서대로)만 반환"""
    rule_config = rule_config or DiversityRuleConfig()

    candidates = extract_candidates(
        viewer_account_id=viewer_account_id,
        academy_id=academy_id,
        feed_posts=feed_posts,
        wishes=wishes,
        visits=visits,
        card_accounts=card_accounts,
        now=now,
        top_n=100,
    )
    if not candidates:
        return []

    scored = score_and_rank_candidates(
        viewer_account_id=viewer_account_id,
        candidates=candidates,
        wishes=wishes,
        savings_tx=savings_tx,
        visits=visits,
        now=now,
        top_n=40,
    )

    final_candidates = apply_diversity_and_rules(
        scored=scored,
        now=now,
        config=rule_config,
    )

    # 순서대로 feed_id만 추출
    return [item.candidate.feed_id for item in final_candidates]


def generate_academy_feed_recommendations(
    academy_id: str,
    feed_posts: Sequence[FeedPost],
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence[ProfileVisit],
    card_accounts: Sequence[CardAccount],
    now: datetime | None = None,
    rule_config: DiversityRuleConfig | None = None,
) -> dict[str, Any]:
    """학원 소속의 모든 학생 계정을 순회하며 {학생ID: [feed_id, ...]} 딕셔너리 생성"""
    now = now or datetime.now()
    rule_config = rule_config or DiversityRuleConfig()

    # 해당 학원에 속한 활성 계정 목록 필터링
    student_accounts = [
        acc for acc in card_accounts
        if acc.academy_id == academy_id and acc.closed_at is None
    ]

    academy_results: dict[str, list[str]] = {}
    for idx, student in enumerate(student_accounts, start=1):
        feed_ids = recommend_feeds_for_student(
            viewer_account_id=student.account_id,
            academy_id=academy_id,
            feed_posts=feed_posts,
            wishes=wishes,
            savings_tx=savings_tx,
            visits=visits,
            card_accounts=card_accounts,
            now=now,
            rule_config=rule_config,
        )
        academy_results[student.account_id] = feed_ids

    return {
        "academy_id": academy_id,
        "generated_at": now.isoformat(),
        "total_students": len(academy_results),
        "recommendations": academy_results,
    }


# ---------------------------------------------------------------------------
# 3. 직접 실행부
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    data_dir = ROOT_DIR / "data"
    target_academy_id = "aca1"  # 대상 학원 ID

    print(f"[*] '{data_dir}' 폴더에서 데이터 로딩 중...")
    wishes, savings_tx, card_accounts, feed_posts, visits = load_all_data(data_dir)

    # 기준 시각 설정 (데이터 내 최신 피드 작성일시 기준)
    ref_now = max(fp.updated_at for fp in feed_posts)

    print(f"[*] 학원 '{target_academy_id}' 소속 학생 전체 피드 추천 생성 중...")
    result_data = generate_academy_feed_recommendations(
        academy_id=target_academy_id,
        feed_posts=feed_posts,
        wishes=wishes,
        savings_tx=savings_tx,
        visits=visits,
        card_accounts=card_accounts,
        now=ref_now,
    )

    # JSON 파일로 저장
    output_path = ROOT_DIR / f"feed_recommendations_{target_academy_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    print(f"[성공] 총 {result_data['total_students']}명 학생의 피드 ID 추천 결과가 저장되었습니다: {output_path}")