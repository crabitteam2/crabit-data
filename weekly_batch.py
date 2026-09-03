"""
학원 전체 학생의 주간 활동 요약을 생성하는 배치 스크립트.

흐름:
1. academy_id 기준으로 필요한 데이터(위시/거래/방문/피드/계좌/학생)를 한 번만 조회
2. 학원 내 계좌(학생)를 하나씩 돌면서 generate_weekly_recap 호출

주간 리포트는 활동량과 무관하게 전원에게 보여줌.

fetch_* 함수들은 이 예제에서는 data/ 폴더의 CSV 파일을 읽도록 구현되어 있다. 실제 서비스에서는 DB 조회 로직으로 바꿔 끼우면 된다.
"""

from __future__ import annotations

import csv
from pathlib import Path
from datetime import date, datetime, timedelta

import json
from pathlib import Path
from recap_presenter import present_weekly_recap, _json_serial

from monthly_recap import (
    Wish,
    WishStatus,
    SavingsTransaction,
    TransactionType,
    ProfileVisit,
    CardAccount,
    UserProfile,
)
from weekly_recap import (
    FeedPost,
    generate_weekly_recap,
    get_last_week_range,
    compute_academy_success_stories,
    MAX_STREAK_LOOKBACK_WEEKS,
    get_type_reference_lookback_start,
)

# CSV 데이터 폴더: 이 스크립트와 같은 위치의 'data' 폴더
DATA_DIR = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------------------
# 0. CSV 읽기/파싱 유틸리티 (batch_monthly_recap.py와 동일)
# ---------------------------------------------------------------------------

def _read_csv(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def _parse_bool(value: str | None) -> bool:
    return str(value).strip().upper() in ("TRUE", "1", "T", "Y", "YES")


# ---------------------------------------------------------------------------
# 1. 거래 유형 판별 (event_type + wish_delta 부호 조합)
# ---------------------------------------------------------------------------

def resolve_transaction_type(event_type: str, wish_delta: int) -> str:
    if event_type == "WISH_DEPOSIT":
        return "입금"
    if event_type == "WISH_WITHDRAWAL":
        return "출금"
    if event_type == "WISH_TRANSFER":
        return "이체출" if wish_delta < 0 else "이체입"
    if event_type in ("WISH_COMPLETION_RETURN", "WISH_ABANDONMENT_RETURN", "WISH_DELETION_RETURN"):
        return "환급"
    raise ValueError(f"알 수 없는 event_type: {event_type}")


# ---------------------------------------------------------------------------
# 2. DB(CSV) row -> dataclass 매핑
# ---------------------------------------------------------------------------

def to_wish(row: dict) -> Wish:
    return Wish(
        wish_id=row["wish_id"],
        account_id=row["account_id"],
        academy_id=row["academy_id"],
        title=row["title"],
        target_amount=row["target_amount"],
        target_date=row["target_date"],
        is_representative=row["is_representative"],
        status=WishStatus(row["status"]),
        created_at=row["created_at"],
        closed_at=row.get("closed_at"),
        deleted_at=row.get("deleted_at"),
        saved_amount=row["saved_amount"],
    )


def to_savings_transaction(row: dict) -> SavingsTransaction:
    tx_type = resolve_transaction_type(row["event_type"], row["amount"])
    return SavingsTransaction(
        transaction_id=row["transaction_id"],
        account_id=row["account_id"],
        wish_id=row["wish_id"],
        type=TransactionType(tx_type),
        amount=abs(row["amount"]),
        created_at=row["created_at"],
    )


def to_profile_visit(row: dict) -> ProfileVisit:
    return ProfileVisit(
        visit_id=row["visit_id"],
        visited_account_id=row["visited_account_id"],
        visitor_account_id=row["visitor_account_id"],
        created_at=row["created_at"],
    )


def to_feed_post(row: dict) -> FeedPost:
    return FeedPost(
        feed_id=row["feed_id"],
        account_id=row["account_id"],
        wish_id=row["wish_id"],
        kind=row["kind"],
        updated_at=row["updated_at"],
    )


def to_card_account(row: dict) -> CardAccount:
    return CardAccount(
        account_id=row["account_id"],
        user_id=row["user_id"],
        academy_id=row["academy_id"],
        created_at=row["created_at"],
        closed_at=row.get("closed_at"),
    )


def to_user_profile(row: dict) -> UserProfile:
    return UserProfile(user_id=row["user_id"], name=row["name"], age=row["age"])


# ---------------------------------------------------------------------------
# 3. DB(대신 CSV) 조회
#    data/wishes.csv, data/savings_transactions.csv, data/profile_visits.csv,
#    data/feed_posts.csv, data/card_accounts.csv, data/users.csv 파일을 읽어온다.
# ---------------------------------------------------------------------------

def fetch_wishes(academy_id: str) -> list[dict]:
    rows = _read_csv("wishes.csv")
    return [
        {
            "wish_id": r["wish_id"],
            "account_id": r["account_id"],
            "academy_id": r["academy_id"],
            "title": r["title"],
            "target_amount": int(r["target_amount"]),
            "target_date": _parse_date(r.get("target_date")),
            "is_representative": _parse_bool(r["is_representative"]),
            "status": r["status"],
            "created_at": _parse_datetime(r["created_at"]),
            "closed_at": _parse_datetime(r.get("closed_at")),
            "deleted_at": _parse_datetime(r.get("deleted_at")),
            "saved_amount": int(r["saved_amount"]),
        }
        for r in rows if r["academy_id"] == academy_id
    ]


def fetch_savings_transactions(account_ids: list[str], since: datetime) -> list[dict]:
    """since 이후(>=)의 거래를 전부 가져온다 (스트릭 계산을 위해 상한선 없이 최신까지)."""
    rows = _read_csv("savings_transactions.csv")
    account_id_set = set(account_ids)
    result = []
    for r in rows:
        if r["account_id"] not in account_id_set:
            continue
        created_at = _parse_datetime(r["created_at"])
        if created_at < since:
            continue
        result.append({
            "transaction_id": r["transaction_id"],
            "account_id": r["account_id"],
            "wish_id": r["wish_id"],
            "amount": int(r["amount"]),
            "event_type": r["event_type"],
            "created_at": created_at,
        })
    return result


def fetch_profile_visits(account_ids: list[str], since: datetime) -> list[dict]:
    """since 이후(>=)의 방문 기록만 가져온다 (2페이지 증감률 계산에 전전주까지 필요)."""
    rows = _read_csv("profile_visits.csv")
    account_id_set = set(account_ids)
    result = []
    for r in rows:
        if r["visited_account_id"] not in account_id_set and r["visitor_account_id"] not in account_id_set:
            continue
        created_at = _parse_datetime(r["created_at"])
        if created_at < since:
            continue
        result.append({
            "visit_id": r["visit_id"],
            "visited_account_id": r["visited_account_id"],
            "visitor_account_id": r["visitor_account_id"],
            "created_at": created_at,
        })
    return result


def fetch_feed_posts(account_ids: list[str], last_week_start: datetime, last_week_end: datetime) -> list[dict]:
    """feed_posts에는 academy_id가 없으므로 account_id 기준으로 필터링한다."""
    rows = _read_csv("feed_posts.csv")
    account_id_set = set(account_ids)
    result = []
    for r in rows:
        if r["account_id"] not in account_id_set:
            continue
        updated_at = _parse_datetime(r["updated_at"])
        if not (last_week_start <= updated_at < last_week_end):
            continue
        result.append({
            "feed_id": r["feed_id"],
            "account_id": r["account_id"],
            "wish_id": r["wish_id"],
            "kind": r["kind"],
            "updated_at": updated_at,
        })
    return result


def fetch_card_accounts(academy_id: str) -> list[dict]:
    rows = _read_csv("card_accounts.csv")
    return [
        {
            "account_id": r["account_id"],
            "user_id": r["user_id"],
            "academy_id": r["academy_id"],
            "created_at": _parse_datetime(r["created_at"]),
            "closed_at": _parse_datetime(r.get("closed_at")),
        }
        for r in rows if r["academy_id"] == academy_id
    ]


def fetch_users(user_ids: list[str]) -> list[dict]:
    rows = _read_csv("users.csv")
    user_id_set = set(user_ids)
    return [
        {"user_id": r["user_id"], "name": r["name"], "age": int(r["age"])}
        for r in rows if r["user_id"] in user_id_set
    ]


# ---------------------------------------------------------------------------
# 4. 학원 단위 배치 실행
# ---------------------------------------------------------------------------

def run_academy_weekly_recap(academy_id: str, reference_date: date) -> dict:
    """academy_id 소속 전체 학생의 지난주 리포트를 계산해서 다음 dict를 반환.
    {
        "students": {account_id: recap_result_dict, ...},   # 개인화된 1~3페이지 (3페이지는 본인 제외)
        "all_success_stories": [SuccessStory, ...],           # 제외 없는 학원 전체 완료+공유 목록
    }
    (활동량과 무관하게 전원 포함)"""

    last_week_start, last_week_end = get_last_week_range(reference_date)
    # 2페이지 증감률 계산용(전주 방문 데이터 필요)과
    # 3페이지 유형 판별용(완료 달의 '이전 달' 데이터 필요) 중 더 이른 시점을 기준으로 방문 데이터를 가져온다.
    prev_week_lookback_start = last_week_start - timedelta(weeks=1)
    type_reference_lookback_start = get_type_reference_lookback_start(last_week_start)
    visits_lookback_start = min(prev_week_lookback_start, type_reference_lookback_start)
    # 스트릭 계산이 최대 MAX_STREAK_LOOKBACK_WEEKS(52)주까지 거슬러 올라가므로,
    # 거래 조회 기간도 반드시 이 값과 맞춰야 데이터 부족으로 스트릭이 실제보다 짧게 끊기지 않는다.
    streak_lookback_start = last_week_start - timedelta(weeks=MAX_STREAK_LOOKBACK_WEEKS)

    # (1) 학원 단위로 필요한 데이터를 한 번에 조회
    card_account_rows = fetch_card_accounts(academy_id)
    card_accounts = [to_card_account(r) for r in card_account_rows]
    account_ids = [a.account_id for a in card_accounts]

    user_ids = [a.user_id for a in card_accounts]
    users = [to_user_profile(r) for r in fetch_users(user_ids)]

    wishes = [to_wish(r) for r in fetch_wishes(academy_id)]

    savings_tx = [
        to_savings_transaction(r)
        for r in fetch_savings_transactions(account_ids, since=streak_lookback_start)
    ]

    visits = [
        to_profile_visit(r)
        for r in fetch_profile_visits(account_ids, since=visits_lookback_start)
    ]

    feed_posts = [
        to_feed_post(r)
        for r in fetch_feed_posts(account_ids, last_week_start, last_week_end)
    ]

    # (2) 학원 내 계좌(학생)를 하나씩 순회 — 필터링 없이 전원 대상
    #     generate_weekly_recap 내부에서 각자 본인 스토리는 3페이지에서 제외하고 계산한다.
    results: dict[str, dict] = {}
    for account_id in account_ids:
        results[account_id] = generate_weekly_recap(
            account_id=account_id,
            academy_id=academy_id,
            reference_date=reference_date,
            wishes=wishes,
            savings_tx=savings_tx,
            visits=visits,
            feed_posts=feed_posts,
            card_accounts=card_accounts,
            users=users,
        )

    # 학원 전체 완료+공유 목록 (제외 없음, 관리자/QA 참고용)
    all_success_stories = compute_academy_success_stories(
        academy_id, last_week_start, last_week_end,
        wishes, savings_tx, visits, feed_posts, card_accounts, users,
    )

    print(f"[weekly_recap] 학원({academy_id}): {len(results)}명 리포트 생성 "
          f"({last_week_start.date()} ~ {(last_week_end - timedelta(days=1)).date()})")
    return {"students": results, "all_success_stories": all_success_stories}


# ---------------------------------------------------------------------------
# 5. 결과를 CSV로 저장
#    - page1/page2/page3(개인화, 본인 제외)는 학생마다 다르므로 학생별 한 행씩
#    - "학원 전체 완료+공유 목록"(제외 없음, 관리자/QA 참고용)은 별도 파일로 한 번만 저장
# ---------------------------------------------------------------------------

def _flatten_weekly_student_result(result: dict) -> dict:
    p1 = result["page1_last_week_performance"]
    achievement = p1["weekly_achievement"]
    milestone = p1["representative_milestone"]
    streak = p1["streak"]
    p2 = result["page2_growth_report"]
    p3 = result["page3_academy_success_stories"]

    # 3페이지 (wish_id + type_title 쌍의 리스트로 변경됨)
    stories = p3.get("stories", [])
    wish_ids_joined = ",".join(s["wish_id"] for s in stories)
    type_titles_joined = ",".join(s["type_title"] or "" for s in stories)

    return {
        "account_id": result["account_id"],
        "week_start": result["week_start"],
        "week_end": result["week_end"],
        # 1페이지
        "achv_save_count": achievement["save_count"],
        "achv_net_savings": achievement["net_savings"],
        "achv_new_wish_count": achievement["new_wish_count"],
        "achv_message": achievement["message"],
        "milestone_wish_title": milestone.get("wish_title"),
        "milestone_rate_before": milestone.get("rate_before"),
        "milestone_rate_after": milestone.get("rate_after"),
        "milestone_crossed": ",".join(str(t) for t in milestone.get("crossed", [])),
        "milestone_message": milestone.get("message"),
        "streak_weeks": streak["streak_weeks"],
        "streak_message": streak["message"],
        # 2페이지
        "visit_total": p2["total_visits"],
        "visit_unique": p2["unique_visitors"],
        "visit_prev_total": p2["prev_total_visits"],
        "visit_growth_pct": p2["growth_pct"],
        "visit_message": p2["message_visits"],
        "visit_growth_message": p2["message_growth"],
        # 3페이지 (텍스트 대신 wish_id + type_title 목록으로 변경)
        "page3_message_summary": p3.get("message_summary"),
        "page3_wish_ids": wish_ids_joined,
        "page3_type_titles": type_titles_joined,
    }


def write_weekly_student_results_csv(results: dict[str, dict], output_path: str | Path) -> None:
    rows = [_flatten_weekly_student_result(r) for r in results.values()]
    if not rows:
        print("결과가 없어 학생별 CSV를 생성하지 않았습니다.")
        return

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[weekly_recap] 학생별 결과 {len(rows)}행을 {output_path}에 저장했습니다.")


def write_weekly_success_stories_csv(stories: list, output_path: str | Path) -> None:
    """학원 전체 완료+공유 목록(SuccessStory 리스트, 본인 제외 없음)을 CSV로 저장."""
    from dataclasses import asdict

    if not stories:
        print("완료+공유 사례가 없어 성공 스토리 CSV를 생성하지 않았습니다.")
        return

    rows = [asdict(s) for s in stories]
    fieldnames = ["wish_id", "account_id", "student_name", "wish_title", "type_title"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[weekly_recap] 성공 스토리 {len(rows)}행을 {output_path}에 저장했습니다.")


# if __name__ == "__main__":
#     recaps = run_academy_weekly_recap(
#         academy_id="aca1",
#         reference_date=date.today(),  # 월요일마다 실행
#     )
#     base_dir = Path(__file__).resolve().parent
#     write_weekly_student_results_csv(recaps["students"], base_dir / "output_weekly_recap_students.csv")
#     write_weekly_success_stories_csv(recaps["all_success_stories"], base_dir / "output_weekly_recap_success_stories.csv")

if __name__ == "__main__":
    recaps = run_academy_weekly_recap(academy_id="aca1", reference_date=date.today())

    # 학생별로 view와 internal_metrics가 분리된 JSON 생성
    weekly_results_json = {
        account_id: present_weekly_recap(result)
        for account_id, result in recaps["students"].items()
    }

    # 결과 저장
    output_path = Path(__file__).resolve().parent / "output_weekly_recap.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(weekly_results_json, f, ensure_ascii=False, indent=2, default=_json_serial)

    print(f"주간 리캡 JSON 저장 완료: {output_path}")