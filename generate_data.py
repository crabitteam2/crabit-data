# -*- coding: utf-8 -*-
"""
테스트용 대규모 시뮬레이션 데이터 생성기.

- 학원 1개(aca1), 학생 30명
- 8월(2026-08) 한 달 거래 패턴을 4가지 저축유형에 맞춰 설계
  (각 학생의 '주 위시' 하나에만 거래를 몰아서, 8월 유형 판정이 의도대로 나오게 함)
- 완료된 '보조 위시'들(saved_amount만 채우고 거래내역은 생성하지 않음 -> 8월 판정에 영향 없음)을
  학생당 1~3개씩 만들어 feed_posts로 공유 -> 50개 이상 피드 확보
- 탐색형 학생 8명 중 일부는 이체출, 일부는 위시 포기(2건), 일부는 프로필 방문(16회 이상)으로
  실제 탐색 조건을 충족시킴 (fallback이 아니라 진짜 조건 충족 케이스도 섞음)
- 시뮬레이션 기간: 2026-07-01 ~ 오늘(스크립트 실행일 기준, datetime.now())
- 모든 datetime은 시/분/초까지 무작위로 생성
"""

from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

random.seed(42)

DATA_DIR = Path(__file__).resolve().parent / "data"
ACADEMY_ID = "aca1"

SIM_START = date(2026, 7, 1)
SIM_END = date.today()  # 오늘
NOW = datetime.now()    # '오늘' 날짜 안에서는 이 시각을 절대 넘지 않도록 사용
AUG_START = date(2026, 8, 1)
AUG_END = date(2026, 8, 31)

NAMES = [
    "민준", "서연", "예준", "하윤", "도윤", "시우", "주원", "지호", "지안", "수아",
    "하은", "지우", "은우", "예은", "다은", "서준", "윤서", "지유", "하람", "유준",
    "수빈", "채원", "민서", "아윤", "현우", "다인", "태윤", "나윤", "시윤", "라온",
]

CATEGORY_TITLES: dict[str, list[str]] = {
    "패션": ["원피스", "크로스백", "패딩자켓", "손목시계", "모자"],
    "문구": ["만년필세트", "다이어리", "플래너", "캘리그라피펜"],
    "전자기기": ["무선이어폰", "블루투스스피커", "스마트워치", "태블릿"],
    "취미": ["보드게임세트", "드론", "우쿨렐레", "캠핑텐트"],
    "스포츠": ["축구화", "자전거", "인라인스케이트", "요가매트", "축구공"],
    "게임": ["닌텐도스위치", "플레이스테이션5", "게임타이틀", "게임머니"],
    "도서": ["소설전집", "만화책세트", "참고서", "전공서적세트"],
    "뷰티": ["쿠션팩트", "향수", "드라이기", "틴트세트"],
    "굿즈": ["포토카드앨범", "아이돌응원봉", "피규어", "포켓몬카드"],
    "생활용품": ["무드등", "텀블러", "전기요", "가습기"],
    "기타": ["제주도 여행", "콘서트 티켓", "캠프 참가비"],
}
AMOUNT_RANGE_BY_CATEGORY: dict[str, tuple[int, int]] = {
    "패션": (10000, 100000), "문구": (5000, 30000), "전자기기": (30000, 300000),
    "취미": (10000, 100000), "스포츠": (10000, 100000), "게임": (30000, 300000),
    "도서": (5000, 30000), "뷰티": (10000, 50000), "굿즈": (5000, 50000),
    "생활용품": (10000, 60000), "기타": (50000, 300000),
}
ALL_CATEGORIES = list(CATEGORY_TITLES.keys())


def rand_time(d: date) -> datetime:
    """날짜 하나를 받아 시/분/초까지 무작위로 채운 datetime 반환."""
    return datetime(d.year, d.month, d.day, random.randint(7, 23), random.randint(0, 59), random.randint(0, 59))


def rand_date_between(start: date, end: date) -> date:
    span = (end - start).days
    if span <= 0:
        return start
    return start + timedelta(days=random.randint(0, span))


def rand_title() -> tuple[str, str]:
    category = random.choice(ALL_CATEGORIES)
    title = random.choice(CATEGORY_TITLES[category])
    return category, title


def rand_amount(category: str) -> int:
    lo, hi = AMOUNT_RANGE_BY_CATEGORY[category]
    return round(random.randint(lo, hi) / 1000) * 1000


# ---------------------------------------------------------------------------
# ID 카운터
# ---------------------------------------------------------------------------
_wish_seq = 0
_tx_seq = 0
_feed_seq = 0
_visit_seq = 0


def next_wish_id() -> str:
    global _wish_seq
    _wish_seq += 1
    return f"w{_wish_seq}"


def next_tx_id() -> str:
    global _tx_seq
    _tx_seq += 1
    return f"t{_tx_seq}"


def next_feed_id() -> str:
    global _feed_seq
    _feed_seq += 1
    return f"f{_feed_seq}"


def next_visit_id() -> str:
    global _visit_seq
    _visit_seq += 1
    return f"v{_visit_seq}"


# ---------------------------------------------------------------------------
# 출력 버퍼
# ---------------------------------------------------------------------------
card_accounts_rows: list[dict] = []
users_rows: list[dict] = []
wishes_rows: list[dict] = []
tx_rows: list[dict] = []
feed_rows: list[dict] = []
visit_rows: list[dict] = []


def fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def fmt_date(d: date | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


# ---------------------------------------------------------------------------
# 학생 30명 생성
# ---------------------------------------------------------------------------

archetypes = (["불도저형"] * 8) + (["꾸준형"] * 7) + (["단기집중형"] * 7) + (["탐색형"] * 8)
random.shuffle(archetypes)

explorer_mechanisms = (["transfer"] * 3) + (["abandon"] * 3) + (["visit"] * 2)
random.shuffle(explorer_mechanisms)
explorer_idx = 0

account_ids = [f"acc{i}" for i in range(1, 31)]

for i in range(1, 31):
    account_id = f"acc{i}"
    user_id = f"u{i}"
    name = NAMES[i - 1]
    age = random.randint(10, 16)
    archetype = archetypes[i - 1]

    card_created_at = rand_time(rand_date_between(date(2025, 9, 1), date(2026, 6, 30)))
    card_accounts_rows.append({
        "account_id": account_id, "user_id": user_id, "academy_id": ACADEMY_ID,
        "created_at": fmt_dt(card_created_at), "closed_at": "",
    })
    users_rows.append({"user_id": user_id, "name": name, "age": age})

    # ---------------------------------------------------------------
    # 주 위시(primary wish): 8월 저축유형 판정용 거래를 전부 여기에 몰아넣는다
    # ---------------------------------------------------------------
    primary_category, primary_title = rand_title()
    primary_wish_id = next_wish_id()
    primary_created_at = rand_time(rand_date_between(date(2026, 7, 1), date(2026, 7, 20)))
    primary_target_amount = rand_amount(primary_category)
    is_representative = random.random() > 0.15  # 85%는 명시적 대표위시, 15%는 fallback 테스트용

    # 8월 저축 패턴 (아키타입별)
    august_deposit_days: list[int] = []
    august_amount_range: tuple[int, int] = (1000, 3000)

    if archetype == "불도저형":
        d = random.randint(1, 3)
        while d <= 29 and len(august_deposit_days) < 10:
            august_deposit_days.append(d)
            d += random.choice([2, 3, 3, 4])
        if len(august_deposit_days) < 8:  # 안전장치
            august_deposit_days = sorted(random.sample(range(1, 30), 8))
        august_amount_range = (2000, 5000)

    elif archetype == "꾸준형":
        n = random.randint(5, 6)
        august_deposit_days = sorted(random.sample(range(1, 30), n))
        august_amount_range = (800, 1800)

    elif archetype == "단기집중형":
        n = random.randint(2, 3)
        august_deposit_days = sorted(random.sample(range(17, 30), n))
        august_amount_range = (4000, 9000)

    else:  # 탐색형
        n = random.randint(1, 2)
        august_deposit_days = sorted(random.sample(range(1, 10), n))  # 전반부, 소액
        august_amount_range = (500, 1500)

    primary_balance = 0
    for day in august_deposit_days:
        amt = random.randint(*august_amount_range)
        tx_dt = rand_time(date(2026, 8, day))
        tx_rows.append({
            "transaction_id": next_tx_id(), "account_id": account_id, "wish_id": primary_wish_id,
            "amount": amt, "event_type": "WISH_DEPOSIT", "created_at": fmt_dt(tx_dt),
        })
        primary_balance += amt

    # 탐색형 실제 조건 충족 (fallback이 아니라 진짜 조건)
    abandoned_wish_ids: list[str] = []
    if archetype == "탐색형":
        mechanism = explorer_mechanisms[explorer_idx % len(explorer_mechanisms)]
        explorer_idx += 1

        if mechanism == "transfer":
            for _ in range(2):
                tx_dt = rand_time(date(2026, 8, random.randint(11, 28)))
                amt = random.randint(1000, 3000)
                tx_rows.append({
                    "transaction_id": next_tx_id(), "account_id": account_id, "wish_id": primary_wish_id,
                    "amount": -amt, "event_type": "WISH_TRANSFER", "created_at": fmt_dt(tx_dt),
                })
                primary_balance -= amt

        elif mechanism == "abandon":
            for _ in range(2):
                aw_id = next_wish_id()
                aw_category, aw_title = rand_title()
                aw_created = rand_time(rand_date_between(date(2026, 7, 1), date(2026, 7, 25)))
                aw_closed = rand_time(date(2026, 8, random.randint(1, 28)))
                aw_target = rand_amount(aw_category)
                wishes_rows.append({
                    "wish_id": aw_id, "account_id": account_id, "academy_id": ACADEMY_ID,
                    "title": aw_title, "target_amount": aw_target, "target_date": "",
                    "is_representative": "FALSE", "status": "포기",
                    "created_at": fmt_dt(aw_created), "closed_at": fmt_dt(aw_closed), "deleted_at": "",
                    "saved_amount": round(aw_target * random.uniform(0.1, 0.5)),
                })
                abandoned_wish_ids.append(aw_id)

        else:  # visit
            n_visits = random.randint(16, 20)
            for _ in range(n_visits):
                target = random.choice([a for a in account_ids if a != account_id])
                visit_dt = rand_time(date(2026, 8, random.randint(1, 30)))
                visit_rows.append({
                    "visit_id": next_visit_id(), "visited_account_id": target,
                    "visitor_account_id": account_id, "created_at": fmt_dt(visit_dt),
                })

    # 7월 / 9월(오늘까지) 가벼운 추가 활동 (아키타입 판정에는 영향 없음 - 다른 달이라 필터링됨)
    for _ in range(random.randint(0, 4)):
        tx_dt = rand_time(rand_date_between(date(2026, 7, 1), date(2026, 7, 31)))
        amt = random.randint(500, 5000)
        tx_rows.append({
            "transaction_id": next_tx_id(), "account_id": account_id, "wish_id": primary_wish_id,
            "amount": amt, "event_type": "WISH_DEPOSIT", "created_at": fmt_dt(tx_dt),
        })
        primary_balance += amt

    if SIM_END >= date(2026, 9, 1):
        for _ in range(random.randint(0, 2)):
            tx_dt = rand_time(rand_date_between(date(2026, 9, 1), SIM_END))
            amt = random.randint(500, 5000)
            tx_rows.append({
                "transaction_id": next_tx_id(), "account_id": account_id, "wish_id": primary_wish_id,
                "amount": amt, "event_type": "WISH_DEPOSIT", "created_at": fmt_dt(tx_dt),
            })
            primary_balance += amt

    wishes_rows.append({
        "wish_id": primary_wish_id, "account_id": account_id, "academy_id": ACADEMY_ID,
        "title": primary_title, "target_amount": primary_target_amount,
        "target_date": fmt_date(rand_date_between(SIM_END, SIM_END + timedelta(days=120))) if random.random() > 0.3 else "",
        "is_representative": "TRUE" if is_representative else "FALSE",
        "status": "진행중", "created_at": fmt_dt(primary_created_at), "closed_at": "", "deleted_at": "",
        "saved_amount": max(primary_balance, 0),
    })

    # 진행중 위시도 일부는 피드에 공유 (kind='진행중')
    if random.random() > 0.5:
        share_dt = rand_time(rand_date_between(max(primary_created_at.date(), SIM_START), SIM_END))
        feed_rows.append({
            "feed_id": next_feed_id(), "account_id": account_id, "wish_id": primary_wish_id,
            "kind": "진행중", "updated_at": fmt_dt(share_dt),
        })

    # ---------------------------------------------------------------
    # 보조 위시(완료): 거래내역 없이 saved_amount만 채움 -> 8월 판정에 영향 없음
    # feed_posts로 공유해서 50개 이상 피드 확보
    # ---------------------------------------------------------------
    n_completed = random.randint(1, 3)
    for _ in range(n_completed):
        c_category, c_title = rand_title()
        c_wish_id = next_wish_id()
        c_created = rand_time(rand_date_between(SIM_START, SIM_END - timedelta(days=1)))
        # closed_at은 created_at 이후여야 하므로, 날짜가 아니라 '분' 단위로 최소 30분~정해진 기간 뒤로 오프셋을 준다.
        max_offset_minutes = max(int((SIM_END - c_created.date()).days * 24 * 60), 60)
        offset_minutes = random.randint(30, max_offset_minutes)
        c_closed = min(c_created + timedelta(minutes=offset_minutes), datetime.combine(SIM_END, datetime.max.time()))
        c_target = rand_amount(c_category)

        wishes_rows.append({
            "wish_id": c_wish_id, "account_id": account_id, "academy_id": ACADEMY_ID,
            "title": c_title, "target_amount": c_target, "target_date": "",
            "is_representative": "FALSE", "status": "완료",
            "created_at": fmt_dt(c_created), "closed_at": fmt_dt(c_closed), "deleted_at": "",
            "saved_amount": c_target,
        })

        share_dt = c_closed + timedelta(hours=random.randint(0, 6), minutes=random.randint(0, 59))
        feed_rows.append({
            "feed_id": next_feed_id(), "account_id": account_id, "wish_id": c_wish_id,
            "kind": "완료", "updated_at": fmt_dt(share_dt),
        })

    # 일반적인 방문 활동(탐색형-visit이 아닌 학생들도 서로 좀 방문하게)
    for _ in range(random.randint(0, 8)):
        target = random.choice([a for a in account_ids if a != account_id])
        visit_dt = rand_time(rand_date_between(SIM_START, SIM_END))
        visit_rows.append({
            "visit_id": next_visit_id(), "visited_account_id": target,
            "visitor_account_id": account_id, "created_at": fmt_dt(visit_dt),
        })


# ---------------------------------------------------------------------------
# CSV로 저장
# ---------------------------------------------------------------------------

def write_csv(filename: str, rows: list[dict], fieldnames: list[str]) -> None:
    path = DATA_DIR / filename
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{filename}: {len(rows)}행")


write_csv("card_accounts.csv", card_accounts_rows,
          ["account_id", "user_id", "academy_id", "created_at", "closed_at"])
write_csv("users.csv", users_rows, ["user_id", "name", "age"])
write_csv("wishes.csv", wishes_rows,
          ["wish_id", "account_id", "academy_id", "title", "target_amount", "target_date",
           "is_representative", "status", "created_at", "closed_at", "deleted_at", "saved_amount"])
write_csv("savings_transactions.csv", tx_rows,
          ["transaction_id", "account_id", "wish_id", "amount", "event_type", "created_at"])
write_csv("feed_posts.csv", feed_rows, ["feed_id", "account_id", "wish_id", "kind", "updated_at"])
write_csv("profile_visits.csv", visit_rows,
          ["visit_id", "visited_account_id", "visitor_account_id", "created_at"])

print()
print("아키타입 분포:", {t: archetypes.count(t) for t in set(archetypes)})
print("시뮬레이션 기간:", SIM_START, "~", SIM_END)