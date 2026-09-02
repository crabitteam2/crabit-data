"""
학원 전체 학생의 월말 리캡을 생성하는 배치 스크립트.

흐름:
1. academy_id 기준으로 필요한 데이터(위시/거래/방문/계좌/학생)를 한 번만 조회
2. 학원 내 계좌(학생)를 하나씩 돌면서
   - compute_core_metrics로 이번 달 save_count를 먼저 확인
   - save_count < 3 이면 리캡 생성 없이 건너뜀 (비활동 사용자 제외)
   - 3건 이상이면 generate_monthly_recap 호출

fetch_* 함수들은 실제 DB 조회 로직으로 채워 넣어야 하는 부분입니다. (사용 중인 DB 드라이버/ORM에 맞춰 구현하시면 됩니다.)
"""

from __future__ import annotations

import csv
from pathlib import Path
from dataclasses import asdict
from datetime import date, datetime

import json
from pathlib import Path
from recap_presenter import present_monthly_recap, _json_serial

from monthly_recap import (
    Wish,
    WishStatus,
    SavingsTransaction,
    TransactionType,
    ProfileVisit,
    CardAccount,
    UserProfile,
    compute_core_metrics,
    generate_monthly_recap,
    _month_range,
)

# CSV 데이터 폴더: 이 스크립트와 같은 위치의 'data' 폴더
DATA_DIR = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------------------
# 0. CSV 읽기/파싱 유틸리티
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
# 2. DB row -> dataclass 매핑
# ---------------------------------------------------------------------------

def to_wish(row: dict) -> Wish:
    return Wish(
        wish_id=row["wish_id"],
        account_id=row["account_id"],
        academy_id=row["academy_id"],
        title=row["title"],
        target_amount=row["target_amount"],
        target_date=row["target_date"],
        is_representative=bool(row["is_representative"]),
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
#    data/card_accounts.csv, data/users.csv 파일을 읽어온다.
# ---------------------------------------------------------------------------

def fetch_wishes(academy_id: str) -> list[dict]:
    """data/wishes.csv 컬럼: wish_id,account_id,academy_id,title,target_amount,
    target_date,is_representative,status,created_at,closed_at,deleted_at,saved_amount"""
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


def fetch_savings_transactions(account_ids: list[str], month_start: datetime, month_end: datetime) -> list[dict]:
    """data/savings_transactions.csv 컬럼: transaction_id,account_id,wish_id,
    amount,event_type,created_at
    amount은 wish_delta(부호 포함, 예: 출금/이체출은 음수)로 저장되어 있다고 가정."""
    rows = _read_csv("savings_transactions.csv")
    account_id_set = set(account_ids)
    result = []
    for r in rows:
        if r["account_id"] not in account_id_set:
            continue
        created_at = _parse_datetime(r["created_at"])
        if not (month_start <= created_at < month_end):
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


def fetch_profile_visits(account_ids: list[str]) -> list[dict]:
    """data/profile_visits.csv 컬럼: visit_id,visited_account_id,visitor_account_id,created_at"""
    rows = _read_csv("profile_visits.csv")
    account_id_set = set(account_ids)
    return [
        {
            "visit_id": r["visit_id"],
            "visited_account_id": r["visited_account_id"],
            "visitor_account_id": r["visitor_account_id"],
            "created_at": _parse_datetime(r["created_at"]),
        }
        for r in rows
        if r["visited_account_id"] in account_id_set or r["visitor_account_id"] in account_id_set
    ]


def fetch_card_accounts(academy_id: str) -> list[dict]:
    """data/card_accounts.csv 컬럼: account_id,user_id,academy_id,created_at,closed_at"""
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
    """data/users.csv 컬럼: user_id,name,age"""
    rows = _read_csv("users.csv")
    user_id_set = set(user_ids)
    return [
        {"user_id": r["user_id"], "name": r["name"], "age": int(r["age"])}
        for r in rows if r["user_id"] in user_id_set
    ]


# ---------------------------------------------------------------------------
# 4. 학원 단위 배치 실행
# ---------------------------------------------------------------------------

def run_academy_monthly_recap(academy_id: str, academy_name: str, year: int, month: int) -> dict[str, dict]:
    """academy_id 소속 전체 학생의 이번 달 리캡을 계산해서
    {account_id: recap_result_dict} 형태로 반환. (비활동 사용자는 결과에서 제외)"""

    today = date.today()

    # (1) 학원 단위로 필요한 데이터를 한 번에 조회
    card_account_rows = fetch_card_accounts(academy_id)
    card_accounts = [to_card_account(r) for r in card_account_rows]
    account_ids = [a.account_id for a in card_accounts]

    user_ids = [a.user_id for a in card_accounts]
    users = [to_user_profile(r) for r in fetch_users(user_ids)]

    wishes = [to_wish(r) for r in fetch_wishes(academy_id)]

    month_start, month_end = _month_range(year, month)
    savings_tx = [
        to_savings_transaction(r)
        for r in fetch_savings_transactions(account_ids, month_start, month_end)
    ]

    visits = [to_profile_visit(r) for r in fetch_profile_visits(account_ids)]

    # (2) 학원 내 계좌(학생)를 하나씩 순회
    results: dict[str, dict] = {}
    skipped_inactive: list[str] = []

    for account_id in account_ids:
        # (2-1) generate_monthly_recap 호출 전, save_count부터 먼저 확인
        metrics = compute_core_metrics(account_id, year, month, wishes, savings_tx, visits)
        if metrics.save_count < 3:
            skipped_inactive.append(account_id)
            continue  # 비활동 사용자 -> 리캡 생성 자체를 하지 않고 건너뜀

        # (2-2) 3건 이상인 경우에만 리캡 생성
        results[account_id] = generate_monthly_recap(
            account_id=account_id,
            year=year,
            month=month,
            today=today,
            wishes=wishes,
            savings_tx=savings_tx,
            visits=visits,
            card_accounts=card_accounts,
            users=users,
            academy_name=academy_name,
        )

    print(f"[monthly_recap] {academy_name}: 생성 {len(results)}건 / 비활동 제외 {len(skipped_inactive)}건")
    return results


# ---------------------------------------------------------------------------
# 5. 결과를 CSV로 저장 (화면에 표시될 정보 전체를 한 줄로 펼침)
# ---------------------------------------------------------------------------

def _flatten_monthly_result(result: dict) -> dict:
    """generate_monthly_recap의 결과 dict를 CSV 한 행으로 펼친다.
    섹션별로 컬럼명 접두사(metric_/type_/objective_/pattern_/group_/pace_)를 붙여 충돌을 방지."""
    core = asdict(result["core_metrics"])

    row = {"account_id": result["account_id"], "year": result["year"], "month": result["month"]}
    row.update({f"metric_{k}": v for k, v in core.items()})
    row.update({f"type_{k}": v for k, v in result["type_section"].items()})
    row.update({f"objective_{k}": v for k, v in result["objective_performance"].items()})
    row.update({f"pattern_{k}": v for k, v in result["pattern_analysis"].items()})
    row.update({f"group_{k}": v for k, v in result["group_comparison"].items()})
    row.update({f"pace_{k}": v for k, v in result["pace_prediction"].items()})
    return row


def write_monthly_results_csv(results: dict[str, dict], output_path: str | Path) -> None:
    """{account_id: recap_result_dict} 전체를 CSV 한 파일로 저장. 계좌당 한 행."""
    rows = [_flatten_monthly_result(r) for r in results.values()]
    if not rows:
        print("결과가 없어 CSV를 생성하지 않았습니다.")
        return

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[monthly_recap] 결과 {len(rows)}행을 {output_path}에 저장했습니다.")


# if __name__ == "__main__":
#     recaps = run_academy_monthly_recap(
#         academy_id="aca1",
#         academy_name="크래빗학원",
#         year=2026,
#         month=8,
#     )
#     write_monthly_results_csv(recaps, Path(__file__).resolve().parent / "output_monthly_recap.csv")

if __name__ == "__main__":
    monthly_recaps = run_academy_monthly_recap(
        academy_id="aca1",
        academy_name="크래빗학원",
        year=2026,
        month=8,
    )

    monthly_results_json = {
        account_id: present_monthly_recap(result, is_active=True)
        for account_id, result in monthly_recaps.items()
    }

    output_path = Path(__file__).resolve().parent / "output_monthly_recap.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(monthly_results_json, f, ensure_ascii=False, indent=2, default=_json_serial)

    print(f"월말 리캡 JSON 저장 완료: {output_path}")