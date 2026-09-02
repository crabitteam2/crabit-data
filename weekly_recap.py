"""
주간 활동 요약 계산 모듈
==========================
- 1페이지: 지난주 성과 (주간 성취, 대표 위시 마일스톤, 주간 스트릭)
- 2페이지: 성장 리포트 (프로필 방문 횟수/방문자수, 전주 대비 증감률)
- 3페이지: 학원 친구들의 성공 스토리 (완료 + 피드 공유된 위시 소개)

월말 리캡 모듈(monthly_recap.py)의 데이터 모델과 일부 함수를 재사용
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Sequence

from monthly_recap import (
    Wish,
    WishStatus,
    SavingsTransaction,
    TransactionType,
    ProfileVisit,
    CardAccount,
    UserProfile,
    TYPE_SIGN,
    get_representative_wish,
    compute_core_metrics,
    classify_savings_type,
    build_type_section,
    DEFAULT_THRESHOLDS,
    Thresholds,
)


# ---------------------------------------------------------------------------
# 0. 데이터 모델 추가분 (feed_posts)
# ---------------------------------------------------------------------------

@dataclass
class FeedPost:
    feed_id: str
    account_id: str
    wish_id: str
    kind: str  # 위시 상태 표현 (예: "완료" 공유 등, 백엔드 정의에 따름)
    updated_at: datetime


# ---------------------------------------------------------------------------
# 1. 주(week) 범위 유틸
# ---------------------------------------------------------------------------

def get_last_week_range(reference_date: date) -> tuple[datetime, datetime]:
    """reference_date(보통 리포트 발송일=이번 주 월요일) 기준,
    가장 최근에 끝난 '완결된 한 주'(월요일 00:00 ~ 다음 월요일 00:00 직전)의 범위를 반환."""
    this_monday = reference_date - timedelta(days=reference_date.weekday())
    last_week_start = datetime.combine(this_monday - timedelta(days=7), datetime.min.time())
    last_week_end = datetime.combine(this_monday, datetime.min.time())
    return last_week_start, last_week_end


def _shift_week(week_start: datetime, week_end: datetime, weeks: int) -> tuple[datetime, datetime]:
    """주어진 주 범위를 weeks주만큼 앞/뒤로 이동. weeks=-1이면 한 주 전."""
    delta = timedelta(weeks=weeks)
    return week_start + delta, week_end + delta


def _in_range(dt: Optional[datetime], start: datetime, end: datetime) -> bool:
    return dt is not None and start <= dt < end


# ---------------------------------------------------------------------------
# 2. 1페이지: 지난주 성과
# ---------------------------------------------------------------------------

@dataclass
class WeeklyAchievement:
    save_count: int
    net_savings: int
    new_wish_count: int


def compute_weekly_achievement(
    account_id: str,
    week_start: datetime,
    week_end: datetime,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
) -> WeeklyAchievement:
    my_tx = [tx for tx in savings_tx if tx.account_id == account_id and _in_range(tx.created_at, week_start, week_end)]
    deposits = [tx for tx in my_tx if tx.type == TransactionType.DEPOSIT]
    withdrawals = [tx for tx in my_tx if tx.type == TransactionType.WITHDRAWAL]

    save_count = len(deposits)
    net_savings = sum(tx.amount for tx in deposits) - sum(tx.amount for tx in withdrawals)

    new_wish_count = sum(
        1 for w in wishes
        if w.account_id == account_id and _in_range(w.created_at, week_start, week_end)
    )

    return WeeklyAchievement(save_count=save_count, net_savings=net_savings, new_wish_count=new_wish_count)


def build_weekly_achievement_section(achievement: WeeklyAchievement) -> dict:
    parts = []
    if achievement.save_count > 0:
        parts.append(f"지난주에 {achievement.save_count}번 저축")
    if achievement.new_wish_count > 0:
        parts.append(f"새 위시 {achievement.new_wish_count}개 등록")

    if parts:
        message = " · ".join(parts) + "했어요!"
    else:
        message = "지난주는 조용히 쉬어갔어요. 이번 주에 다시 시작해볼까요?"

    return {
        "save_count": achievement.save_count,
        "net_savings": achievement.net_savings,
        "new_wish_count": achievement.new_wish_count,
        "message": message,
    }


def _wish_progress_asof(
    wish: Wish,
    cutoff: datetime,
    anchor: datetime,
    savings_tx: Sequence[SavingsTransaction],
) -> int:
    """wish.saved_amount는 anchor 시점 기준 스냅샷이라고 가정하고,
    거기서 [cutoff, anchor) 구간에 발생한 순변동을 역산해 cutoff 시점의 잔액을 구한다."""
    net_change_after_cutoff = sum(
        tx.amount * TYPE_SIGN[tx.type]
        for tx in savings_tx
        if tx.wish_id == wish.wish_id and cutoff <= tx.created_at < anchor
    )
    return wish.saved_amount - net_change_after_cutoff


MILESTONE_THRESHOLDS = (50, 80, 100)


def compute_representative_milestone(
    account_id: str,
    week_start: datetime,
    week_end: datetime,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    anchor: datetime,
    milestone_thresholds: Sequence[int] = MILESTONE_THRESHOLDS,
) -> dict:
    representative = get_representative_wish(account_id, wishes)
    if representative is None or representative.target_amount <= 0:
        return {"crossed": [], "message": None}

    progress_before = _wish_progress_asof(representative, week_start, anchor, savings_tx)
    progress_after = _wish_progress_asof(representative, week_end, anchor, savings_tx)

    rate_before = progress_before / representative.target_amount * 100
    rate_after = progress_after / representative.target_amount * 100

    crossed = [t for t in milestone_thresholds if rate_before < t <= rate_after]

    if crossed:
        top = max(crossed)
        message = f"대표 위시 '{representative.title}'가 {top}% 지점을 돌파했어요! 🎉"
    else:
        message = None

    return {
        "wish_title": representative.title,
        "rate_before": round(rate_before),
        "rate_after": round(rate_after),
        "crossed": crossed,
        "message": message,
    }


def _week_has_deposit(
    account_id: str,
    week_start: datetime,
    week_end: datetime,
    savings_tx: Sequence[SavingsTransaction],
) -> bool:
    return any(
        tx.account_id == account_id
        and tx.type == TransactionType.DEPOSIT
        and _in_range(tx.created_at, week_start, week_end)
        for tx in savings_tx
    )


def compute_streak_weeks(
    account_id: str,
    last_week_start: datetime,
    last_week_end: datetime,
    savings_tx: Sequence[SavingsTransaction],
    max_lookback_weeks: int = 52,
) -> int:
    """지난주부터 거꾸로 훑으며, 저축이 1건도 없는 주가 나올 때까지의 연속 주 수(스트릭)."""
    streak = 0
    week_start, week_end = last_week_start, last_week_end
    for _ in range(max_lookback_weeks):
        if not _week_has_deposit(account_id, week_start, week_end, savings_tx):
            break
        streak += 1
        week_start, week_end = _shift_week(week_start, week_end, weeks=-1)
    return streak


def build_streak_section(streak_weeks: int) -> dict:
    if streak_weeks <= 0:
        message = "이번 주 저축을 시작하면 새로운 스트릭이 시작돼요!"
    else:
        message = f"{streak_weeks}주 연속 저축 스트릭 유지 중! 다음 주에도 불꽃을 이어가 봐요."
    return {"streak_weeks": streak_weeks, "message": message}


def build_page1(
    account_id: str,
    last_week_start: datetime,
    last_week_end: datetime,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    anchor: datetime,
) -> dict:
    achievement = compute_weekly_achievement(account_id, last_week_start, last_week_end, wishes, savings_tx)
    milestone = compute_representative_milestone(
        account_id, last_week_start, last_week_end, wishes, savings_tx, anchor
    )
    streak_weeks = compute_streak_weeks(account_id, last_week_start, last_week_end, savings_tx)

    return {
        "weekly_achievement": build_weekly_achievement_section(achievement),
        "representative_milestone": milestone,
        "streak": build_streak_section(streak_weeks),
    }


# ---------------------------------------------------------------------------
# 3. 2페이지: 성장 리포트 (프로필 방문)
# ---------------------------------------------------------------------------

def compute_profile_visit_stats(
    account_id: str,
    week_start: datetime,
    week_end: datetime,
    visits: Sequence[ProfileVisit],
) -> dict:
    week_visits = [
        v for v in visits
        if v.visited_account_id == account_id and _in_range(v.created_at, week_start, week_end)
    ]
    total_visits = len(week_visits)
    unique_visitors = len({v.visitor_account_id for v in week_visits})
    return {"total_visits": total_visits, "unique_visitors": unique_visitors}


def build_page2(
    account_id: str,
    last_week_start: datetime,
    last_week_end: datetime,
    visits: Sequence[ProfileVisit],
) -> dict:
    this_week = compute_profile_visit_stats(account_id, last_week_start, last_week_end, visits)

    prev_week_start, prev_week_end = _shift_week(last_week_start, last_week_end, weeks=-1)
    prev_week = compute_profile_visit_stats(account_id, prev_week_start, prev_week_end, visits)

    total_visits = this_week["total_visits"]
    unique_visitors = this_week["unique_visitors"]
    prev_total_visits = prev_week["total_visits"]

    if prev_total_visits > 0:
        growth_pct = round((total_visits - prev_total_visits) / prev_total_visits * 100)
    else:
        growth_pct = None  # 전주 방문 0건이면 증감률 정의 불가

    if total_visits > 0:
        message_visits = f"내 위시리스트를 지난주 {unique_visitors}명이 {total_visits}번 방문했어요."
    else:
        message_visits = "지난주엔 내 위시리스트를 방문한 친구가 없었어요."

    if growth_pct is not None:
        if growth_pct > 0:
            message_growth = f"지난주보다 내 위시리스트 인기가 {growth_pct}% 더 올라갔어요!"
        elif growth_pct < 0:
            message_growth = f"지난주보다 방문이 {abs(growth_pct)}% 줄었어요."
        else:
            message_growth = "지난주와 비슷한 수준의 방문을 유지했어요."
    else:
        message_growth = None

    return {
        "total_visits": total_visits,
        "unique_visitors": unique_visitors,
        "prev_total_visits": prev_total_visits,
        "growth_pct": growth_pct,
        "message_visits": message_visits,
        "message_growth": message_growth,
    }


# ---------------------------------------------------------------------------
# 4. 3페이지: 학원 친구들의 성공 스토리
# ---------------------------------------------------------------------------

@dataclass
class SuccessStory:
    wish_id: str
    account_id: str
    student_name: str
    wish_title: str
    type_title: Optional[str]  # 저축 유형 타이틀 (예: "불도저형 토끼")


def compute_academy_success_stories(
    academy_id: str,
    last_week_start: datetime,
    last_week_end: datetime,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence[ProfileVisit],
    feed_posts: Sequence[FeedPost],
    card_accounts: Sequence[CardAccount],
    users: Sequence[UserProfile],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    max_stories: int = 5,
    viewer_account_id: Optional[str] = None,
) -> list[SuccessStory]:
    """같은 학원 학생 중 지난주에 위시를 완료하고, 그 위시를 피드에 공유한 사례를 찾는다.

    viewer_account_id를 주면, '친구들의 성공 스토리'이므로 본인(viewer) 것은 목록에서 제외한다.
    """

    user_by_id = {u.user_id: u for u in users}
    account_by_id = {a.account_id: a for a in card_accounts}

    # 지난주에 '완료' 처리된 위시들 (해당 학원 소속, 본인 것은 제외)
    completed_wishes = [
        w for w in wishes
        if w.academy_id == academy_id
        and w.account_id != viewer_account_id
        and w.status == WishStatus.COMPLETED
        and _in_range(w.closed_at, last_week_start, last_week_end)
    ]

    # 완료된 위시 중, 피드에 공유(feed_posts 존재)된 것만
    shared_wish_ids = {fp.wish_id for fp in feed_posts}

    stories: list[SuccessStory] = []
    for wish in completed_wishes:
        if wish.wish_id not in shared_wish_ids:
            continue

        account = account_by_id.get(wish.account_id)
        if account is None:
            continue
        user = user_by_id.get(account.user_id)
        student_name = user.name if user is not None else "친구"

        # 유형 타이틀: 완료 시점이 속한 달 기준으로 월간 유형 판별 로직을 재사용
        ref_year, ref_month = wish.closed_at.year, wish.closed_at.month
        metrics = compute_core_metrics(wish.account_id, ref_year, ref_month, wishes, savings_tx, visits)
        classification = classify_savings_type(metrics, thresholds)
        type_title = build_type_section(classification)["type_title"]

        stories.append(SuccessStory(
            wish_id=wish.wish_id,
            account_id=wish.account_id,
            student_name=student_name,
            wish_title=wish.title,
            type_title=type_title,
        ))

        if len(stories) >= max_stories:
            break

    return stories


def build_page3(stories: Sequence[SuccessStory]) -> dict:
    if not stories:
        return {
            "wish_ids": [],
            "message_summary": "지난주엔 아직 완주한 학원 친구가 없어요. 이번 주 첫 주인공이 되어볼까요?",
        }

    summary = f"우리 학원 친구 {len(stories)}명이 목표를 이뤘어요!"

    return {
        "wish_ids": [s.wish_id for s in stories],  # wish_id 리스트만 심플하게 전달
        "message_summary": summary,
    }


# ---------------------------------------------------------------------------
# 5. 최상위 오케스트레이션 함수
# ---------------------------------------------------------------------------

def generate_weekly_recap(
    account_id: str,
    academy_id: str,
    reference_date: date,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence[ProfileVisit],
    feed_posts: Sequence[FeedPost],
    card_accounts: Sequence[CardAccount],
    users: Sequence[UserProfile],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> dict:
    """주간 활동 요약(1~3페이지) 전체를 계산해 하나의 dict로 반환.

    reference_date: 리포트를 발송하는 시점 (보통 이번 주 월요일).
                    이 값을 기준으로 '지난주'(월~일) 범위를 자동 계산한다.
    """
    last_week_start, last_week_end = get_last_week_range(reference_date)
    anchor = datetime.combine(reference_date, datetime.min.time())

    page1 = build_page1(account_id, last_week_start, last_week_end, wishes, savings_tx, anchor)
    page2 = build_page2(account_id, last_week_start, last_week_end, visits)

    stories = compute_academy_success_stories(
        academy_id, last_week_start, last_week_end,
        wishes, savings_tx, visits, feed_posts, card_accounts, users,
        thresholds=thresholds,
        viewer_account_id=account_id,
    )
    page3 = build_page3(stories)

    return {
        "account_id": account_id,
        "week_start": last_week_start.date(),
        "week_end": (last_week_end - timedelta(days=1)).date(),
        "page1_last_week_performance": page1,
        "page2_growth_report": page2,
        "page3_academy_success_stories": page3,
    }