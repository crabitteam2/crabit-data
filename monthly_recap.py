"""
월말 리캡 계산 모듈
==================================
이 모듈은 다음을 담당합니다:
1. 핵심 변수 계산 (save_count, total_savings, avg_amount, regularity_std,
   pace_bias, abandon_count, transfer_count, visit_count)
2. 4가지 저축 유형 판별 (우선순위: 불도저형 -> 꾸준형 -> 단기집중형 -> 탐색형(기본값 겸용))
3. 객관적 성과 / 저축 패턴 분석 / 그룹 내 비교 / 페이스 분석 섹션별 데이터 및 문구 생성

입력 데이터는 데이터_요청서.md 스키마에 대응하는 dataclass로 표현합니다. 실제 서비스에서는 DB 쿼리 결과를 이 dataclass 리스트로 매핑해서 넘겨주면 됩니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from calendar import monthrange
from statistics import pstdev
from typing import Optional, Sequence
from enum import Enum


# ---------------------------------------------------------------------------
# 1. 데이터 모델 (데이터_요청서.md 스키마 대응)
# ---------------------------------------------------------------------------

class WishStatus(str, Enum):
    IN_PROGRESS = "진행중"
    REACHED = "도달"
    COMPLETED = "완료"
    ABANDONED = "포기"


class TransactionType(str, Enum):
    DEPOSIT = "입금"
    WITHDRAWAL = "출금"
    TRANSFER_OUT = "이체출"
    TRANSFER_IN = "이체입"
    REFUND = "환급"


@dataclass
class Wish:
    wish_id: str
    account_id: str
    academy_id: str
    title: str
    target_amount: int
    target_date: Optional[date]
    is_representative: bool
    status: WishStatus
    created_at: datetime
    closed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    saved_amount: int = 0  # wish.wish_amount 스냅샷 (현재 시점 기준)


@dataclass
class SavingsTransaction:
    transaction_id: str
    account_id: str
    wish_id: str
    type: TransactionType
    amount: int  # 항상 양수(거래 금액의 절대값)로 들어온다고 가정
    created_at: datetime


@dataclass
class ProfileVisit:
    visit_id: str
    visited_account_id: str
    visitor_account_id: str
    created_at: datetime


@dataclass
class CardAccount:
    account_id: str
    user_id: str
    academy_id: str
    created_at: datetime
    closed_at: Optional[datetime] = None


@dataclass
class UserProfile:
    user_id: str
    name: str
    age: int


# 위시 잔액에 각 거래 유형이 미치는 부호. 실제 wish_delta 부호 규칙과 다르면 여기만 수정하면 됨.
TYPE_SIGN = {
    TransactionType.DEPOSIT: +1,
    TransactionType.WITHDRAWAL: -1,
    TransactionType.TRANSFER_OUT: -1,
    TransactionType.TRANSFER_IN: +1,
    TransactionType.REFUND: -1,  # 위시 종료/포기 시 잔액이 빠져나가는 것으로 간주
}


# ---------------------------------------------------------------------------
# 2. 판별 임계값 (기획서상 placeholder — 실사용 데이터로 추후 보정)
# ---------------------------------------------------------------------------

@dataclass
class Thresholds:
    bulldozer_min_save_count: int = 8
    bulldozer_max_regularity_std: float = 4.0

    steady_max_avg_amount: int = 2000
    steady_min_save_count: int = 5

    sprint_min_pace_bias: float = 0.3
    sprint_max_save_count: int = 5  # save_count < 5

    explorer_min_abandon_count: int = 2
    explorer_min_transfer_count: int = 2
    explorer_min_visit_count: int = 15


DEFAULT_THRESHOLDS = Thresholds()


def get_representative_wish(account_id: str, wishes: Sequence[Wish]) -> Optional[Wish]:
    """대표 위시를 결정한다.

    1) is_representative=True로 명시된 위시가 있으면 그것을 사용.
    2) 없으면, '진행중' 상태인 위시 중 가장 먼저 생성된 것을 대표 위시로 간주.
    3) 진행중인 위시도 없으면 None.
    """
    explicit = next(
        (w for w in wishes if w.account_id == account_id and w.is_representative and w.deleted_at is None),
        None,
    )
    if explicit is not None:
        return explicit

    in_progress = [
        w for w in wishes
        if w.account_id == account_id and w.status == WishStatus.IN_PROGRESS and w.deleted_at is None
    ]
    if not in_progress:
        return None
    return min(in_progress, key=lambda w: w.created_at)


# ---------------------------------------------------------------------------
# 3. 유틸리티
# ---------------------------------------------------------------------------

def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    """해당 월의 [시작, 다음 달 시작) datetime 범위를 반환."""
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def _in_month(dt: Optional[datetime], start: datetime, end: datetime) -> bool:
    return dt is not None and start <= dt < end


# ---------------------------------------------------------------------------
# 4. 핵심 변수 계산
# ---------------------------------------------------------------------------

@dataclass
class CoreMetrics:
    save_count: int
    total_savings: int
    avg_amount: float
    regularity_std: Optional[float]  # 저축 1건 이하면 계산 불가 -> None
    pace_bias: Optional[float]       # 당월 총 저축액이 0이면 계산 불가 -> None
    abandon_count: int
    transfer_count: int
    visit_count: int


def compute_core_metrics(
    account_id: str,
    year: int,
    month: int,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence[ProfileVisit],
) -> CoreMetrics:
    start, end = _month_range(year, month)

    my_tx = [tx for tx in savings_tx if tx.account_id == account_id and _in_month(tx.created_at, start, end)]
    deposits = [tx for tx in my_tx if tx.type == TransactionType.DEPOSIT]
    withdrawals = [tx for tx in my_tx if tx.type == TransactionType.WITHDRAWAL]
    transfers_out = [tx for tx in my_tx if tx.type == TransactionType.TRANSFER_OUT]

    save_count = len(deposits)
    total_savings = sum(tx.amount for tx in deposits) - sum(tx.amount for tx in withdrawals)
    avg_amount = (total_savings / save_count) if save_count > 0 else 0.0

    # 규칙성: 저축이 발생한 '날짜'(중복 제거) 사이의 간격(일) 표준편차
    deposit_dates = sorted({tx.created_at.date() for tx in deposits})
    if len(deposit_dates) >= 2:
        gaps = [(deposit_dates[i + 1] - deposit_dates[i]).days for i in range(len(deposit_dates) - 1)]
        regularity_std = pstdev(gaps)
    else:
        regularity_std = None  # 저축일이 0~1일뿐이면 규칙성을 판단할 수 없음

    # 페이스 편향: (후반 15일 저축액 - 전반 15일 저축액) / 당월 총 저축액
    mid_point = start + timedelta(days=15)
    first_half = sum(tx.amount for tx in deposits if tx.created_at < mid_point) \
        - sum(tx.amount for tx in withdrawals if tx.created_at < mid_point)
    second_half = total_savings - first_half
    pace_bias = ((second_half - first_half) / total_savings) if total_savings > 0 else None

    # 포기 건수: 이번 달에 '포기'로 종료 처리된 위시 (내 계좌 소유)
    abandon_count = sum(
        1 for w in wishes
        if w.account_id == account_id
        and w.status == WishStatus.ABANDONED
        and _in_month(w.closed_at, start, end)
    )

    transfer_count = len(transfers_out)

    visit_count = sum(
        1 for v in visits
        if v.visitor_account_id == account_id and _in_month(v.created_at, start, end)
    )

    return CoreMetrics(
        save_count=save_count,
        total_savings=total_savings,
        avg_amount=avg_amount,
        regularity_std=regularity_std,
        pace_bias=pace_bias,
        abandon_count=abandon_count,
        transfer_count=transfer_count,
        visit_count=visit_count,
    )


# ---------------------------------------------------------------------------
# 5. 저축 유형 판별
#    우선순위: 1.불도저형 -> 2.꾸준형 -> 3.단기집중형 -> 4.탐색형(자체조건 OR 기본값)
# ---------------------------------------------------------------------------

class SavingsType(str, Enum):
    BULLDOZER = "불도저형 토끼"
    STEADY = "꾸준형 토끼"
    SPRINT = "단기 집중형 토끼"
    EXPLORER = "탐색형 토끼"


@dataclass
class TypeClassification:
    type: SavingsType
    priority: int
    is_fallback: bool  # True면 탐색형 '자체 조건'은 안 맞고 fallback으로 배정된 경우


TYPE_MESSAGES = {
    SavingsType.BULLDOZER: (
        "월 8회 이상의 높은 빈도로 흔들림 없이 목표를 향해 거침없이 질주했어요!"
    ),
    SavingsType.STEADY: (
        "소액이라도 5회 이상 꾸준히 모으며 티끌 모아 태산의 정석을 보여줬어요!"
    ),
    SavingsType.SPRINT: (
        "월말 막판 스퍼트로 집중 저축하며 강력한 뒷심을 발휘했어요!"
    ),
    SavingsType.EXPLORER: (
        "이번 달 위시를 변경하거나 저축액을 옮겨 담고, 친구들 프로필도 자주 구경하며 "
        "나에게 맞는 목표를 활발히 탐색했어요!"
    ),
}

# 탐색형 fallback(진짜 탐색 행동은 없지만 1~3순위도 미충족)일 때 쓸 중립적 문구
EXPLORER_FALLBACK_MESSAGE = "이번 달은 나만의 속도로 위시를 살펴봤어요."


def classify_savings_type(
    metrics: CoreMetrics,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> TypeClassification:
    # 1순위: 불도저형
    if (
        metrics.save_count >= thresholds.bulldozer_min_save_count
        and metrics.regularity_std is not None
        and metrics.regularity_std < thresholds.bulldozer_max_regularity_std
    ):
        return TypeClassification(SavingsType.BULLDOZER, priority=1, is_fallback=False)

    # 2순위: 꾸준형
    if (
        metrics.avg_amount < thresholds.steady_max_avg_amount
        and metrics.save_count >= thresholds.steady_min_save_count
    ):
        return TypeClassification(SavingsType.STEADY, priority=2, is_fallback=False)

    # 3순위: 단기집중형
    if (
        metrics.pace_bias is not None
        and metrics.pace_bias > thresholds.sprint_min_pace_bias
        and metrics.save_count < thresholds.sprint_max_save_count
    ):
        return TypeClassification(SavingsType.SPRINT, priority=3, is_fallback=False)

    # 4순위: 탐색형 (자체 조건 충족 여부와 무관하게 최종 fallback)
    explorer_condition_met = (
        metrics.abandon_count >= thresholds.explorer_min_abandon_count
        or metrics.transfer_count >= thresholds.explorer_min_transfer_count
        or metrics.visit_count >= thresholds.explorer_min_visit_count
    )
    return TypeClassification(
        SavingsType.EXPLORER,
        priority=4,
        is_fallback=not explorer_condition_met,
    )


def build_type_section(classification: TypeClassification) -> dict:
    """0. 저축 유형 섹션 표현 데이터."""
    if classification.type == SavingsType.EXPLORER and classification.is_fallback:
        message = EXPLORER_FALLBACK_MESSAGE
    else:
        message = TYPE_MESSAGES[classification.type]

    return {
        "type_title": classification.type.value,
        "priority_matched": classification.priority,
        "is_fallback": classification.is_fallback,
        "message": message,
        # 캐릭터 일러스트 경로, 다음 달 액션 팁 등은 프론트/컨텐츠 쪽에서 type_title 기준으로 매핑
    }


# ---------------------------------------------------------------------------
# 6. 객관적 성과
# ---------------------------------------------------------------------------

def _month_net_change(wish_id: str, start: datetime, end: datetime, savings_tx: Sequence[SavingsTransaction]) -> int:
    """해당 위시에 대해 이번 달(start~end) 동안 발생한 순변동액(모든 거래유형 반영)."""
    return sum(
        tx.amount * TYPE_SIGN[tx.type]
        for tx in savings_tx
        if tx.wish_id == wish_id and start <= tx.created_at < end
    )


def compute_objective_performance(
    account_id: str,
    year: int,
    month: int,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    metrics: CoreMetrics,
) -> dict:
    start, end = _month_range(year, month)

    # 위시 달성 개수: 이번 달에 '완료' 처리된 위시 수
    completed_count = sum(
        1 for w in wishes
        if w.account_id == account_id
        and w.status == WishStatus.COMPLETED
        and _in_month(w.closed_at, start, end)
    )

    result = {
        "total_savings": metrics.total_savings,
        "completed_wish_count": completed_count,
        "message_total_savings": f"이번 달 총 {metrics.total_savings:,}원을 모았어요.",
        "message_completed_count": f"목표했던 위시 {completed_count}개를 완주했어요!" if completed_count > 0
            else "이번 달엔 아직 완주한 위시가 없어요. 다음 달엔 함께 달성해봐요!",
    }

    # 대표 위시 기준 전월 대비 달성률 변화
    # curr_progress는 wish.saved_amount(현재 누적 저축액)를 그대로 사용하고,
    # prev_progress는 거기서 '이번 달에 발생한 순변동액'만 역산해서 구한다.
    # (위시 생성 시점부터 전체 거래를 리플레이할 필요 없음)
    representative = get_representative_wish(account_id, wishes)
    if representative is not None and representative.target_amount > 0:
        curr_progress = representative.saved_amount
        net_change_this_month = _month_net_change(representative.wish_id, start, end, savings_tx)
        prev_progress = curr_progress - net_change_this_month

        prev_rate = round(prev_progress / representative.target_amount * 100)
        curr_rate = round(curr_progress / representative.target_amount * 100)
        result.update({
            "representative_wish_title": representative.title,
            "prev_rate_pct": prev_rate,
            "curr_rate_pct": curr_rate,
            "message_rate_change": (
                f"{representative.title} 목표가 {prev_rate}% → {curr_rate}%로 "
                f"{curr_rate - prev_rate:+d}%p 변화했어요."
            ),
        })
    else:
        result.update({
            "representative_wish_title": None,
            "prev_rate_pct": None,
            "curr_rate_pct": None,
            "message_rate_change": None,
        })

    return result


# ---------------------------------------------------------------------------
# 7. 저축 패턴 분석
# ---------------------------------------------------------------------------

WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def compute_pattern_analysis(
    account_id: str,
    year: int,
    month: int,
    savings_tx: Sequence[SavingsTransaction],
    metrics: CoreMetrics,
) -> dict:
    start, end = _month_range(year, month)
    deposits = [
        tx for tx in savings_tx
        if tx.account_id == account_id
        and tx.type == TransactionType.DEPOSIT
        and _in_month(tx.created_at, start, end)
    ]

    # 주차별(1~5주차, 해당 월 1일 기준 7일 단위) 총액
    week_totals: dict[int, int] = {}
    for tx in deposits:
        week_idx = (tx.created_at.day - 1) // 7 + 1  # 1~5주차
        week_totals[week_idx] = week_totals.get(week_idx, 0) + tx.amount
    top_week = max(week_totals, key=week_totals.get) if week_totals else None

    # 요일별 빈도
    weekday_counts = [0] * 7
    for tx in deposits:
        weekday_counts[tx.created_at.weekday()] += 1
    top_weekday_idx = weekday_counts.index(max(weekday_counts)) if deposits else None
    top_weekday = WEEKDAY_KR[top_weekday_idx] if top_weekday_idx is not None else None

    if top_week and top_weekday:
        message_week_weekday = f"가장 열심히 모은 주는 {month}월 {top_week}주차였고, 주로 {top_weekday}에 저축했어요."
    else:
        message_week_weekday = "이번 달은 저축 패턴을 분석하기엔 데이터가 부족해요."

    # 규칙성 문구 (3일 미만 = 규칙적)
    if metrics.regularity_std is None:
        message_regularity = "저축 횟수가 적어 규칙성을 판단하기 어려워요."
    elif metrics.regularity_std < 3:
        message_regularity = f"평균 {metrics.regularity_std:.1f}일 주기로 아주 일정하게 저축했어요."
    else:
        message_regularity = f"저축 간격이 평균 {metrics.regularity_std:.1f}일로 다소 불규칙했어요."

    message_avg_amount = f"한 번에 평균 {metrics.avg_amount:,.0f}원씩 나누어 담았어요."

    return {
        "top_week": top_week,
        "top_weekday": top_weekday,
        "message_week_weekday": message_week_weekday,
        "message_regularity": message_regularity,
        "message_avg_amount": message_avg_amount,
    }


# ---------------------------------------------------------------------------
# 8. 그룹 내 비교 (동일 학원/연령대 피어 그룹 대비 백분위)
# ---------------------------------------------------------------------------

def select_peer_account_ids(
    my_account_id: str,
    card_accounts: Sequence[CardAccount],
    users: Sequence[UserProfile],
    age_band: int = 2,
) -> list[str]:
    """동일 학원 + 연령대(내 나이 ± age_band)에 속하는 피어 계좌 ID 목록 (본인/해지 계좌 제외).

    age_band=2 이면 나와 나이가 ±2세 이내인 학생들을 같은 연령대로 간주.
    """
    my_account = next((a for a in card_accounts if a.account_id == my_account_id), None)
    if my_account is None:
        return []
    my_user = next((u for u in users if u.user_id == my_account.user_id), None)
    if my_user is None:
        return []

    user_by_id = {u.user_id: u for u in users}
    peers = []
    for acc in card_accounts:
        if acc.account_id == my_account_id or acc.closed_at is not None:
            continue
        if acc.academy_id != my_account.academy_id:
            continue
        peer_user = user_by_id.get(acc.user_id)
        if peer_user is None:
            continue
        if abs(peer_user.age - my_user.age) <= age_band:
            peers.append(acc.account_id)
    return peers


def compute_active_weeks(
    account_id: str,
    year: int,
    month: int,
    savings_tx: Sequence[SavingsTransaction],
) -> int:
    """이번 달 중 저축(입금)이 1건이라도 발생한 주(1~5주차) 수."""
    start, end = _month_range(year, month)
    deposits = [
        tx for tx in savings_tx
        if tx.account_id == account_id
        and tx.type == TransactionType.DEPOSIT
        and _in_month(tx.created_at, start, end)
    ]
    active_weeks = {(tx.created_at.day - 1) // 7 + 1 for tx in deposits}
    return len(active_weeks)


def compute_wish_achievement_rate(account_id: str, wishes: Sequence[Wish]) -> Optional[float]:
    """대표 위시(get_representative_wish 기준) 달성률(%). 대표 위시가 없으면 None."""
    representative = get_representative_wish(account_id, wishes)
    if representative is None or representative.target_amount <= 0:
        return None
    return representative.saved_amount / representative.target_amount * 100


@dataclass
class PeerGroupMetrics:
    peer_active_weeks: list[int]
    peer_achievement_rates: list[float]


def compute_peer_group_metrics(
    peer_account_ids: Sequence[str],
    year: int,
    month: int,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
) -> PeerGroupMetrics:
    """피어 계좌 목록에 대해 활동 주수 / 대표 위시 달성률 지표를 일괄 계산.

    achievement_rate는 대표 위시가 없는 피어는 목록에서 제외한다(비교 대상에서 스스로 빠짐).
    """
    peer_active_weeks = [
        compute_active_weeks(pid, year, month, savings_tx) for pid in peer_account_ids
    ]
    peer_achievement_rates = [
        rate for pid in peer_account_ids
        if (rate := compute_wish_achievement_rate(pid, wishes)) is not None
    ]
    return PeerGroupMetrics(peer_active_weeks=peer_active_weeks, peer_achievement_rates=peer_achievement_rates)


def _percentile_rank(value: float, peer_values: Sequence[float]) -> float:
    """value가 peer_values 중 상위 몇 %인지 반환 (값이 클수록 상위)."""
    if not peer_values:
        return 0.0
    better_or_equal = sum(1 for v in peer_values if v <= value)
    return round(better_or_equal / len(peer_values) * 100)


def compute_group_comparison(
    my_active_weeks: int,
    peer_active_weeks: Sequence[int],
    my_achievement_rate: Optional[float],
    peer_achievement_rates: Sequence[float],
    academy_name: str,
) -> dict:
    habit_percentile = _percentile_rank(my_active_weeks, peer_active_weeks)

    result = {
        "habit_percentile": habit_percentile,
        "message_habit": f"{academy_name} 친구들 중 저축 습관 유지율 상위 {100 - habit_percentile}%예요.",
    }

    if my_achievement_rate is not None and peer_achievement_rates:
        achievement_percentile = _percentile_rank(my_achievement_rate, peer_achievement_rates)
        result.update({
            "achievement_percentile": achievement_percentile,
            "message_achievement": f"{academy_name} 친구들 중 목표 달성률 상위 {100 - achievement_percentile}%를 기록했어요.",
        })
    else:
        result.update({"achievement_percentile": None, "message_achievement": None})

    return result


# ---------------------------------------------------------------------------
# 9. 페이스 분석 및 성공 가능성 예측 (대표 위시 기준)
# ---------------------------------------------------------------------------

def compute_pace_prediction(
    representative_wish: Optional[Wish],
    total_savings_this_month: int,
    today: date,
    year: int,
    month: int,
) -> dict:
    days_in_month = monthrange(year, month)[1]
    daily_pace = total_savings_this_month / days_in_month if days_in_month else 0.0

    result = {
        "daily_pace": daily_pace,
        "message_daily_pace": f"하루 평균 {daily_pace:,.0f}원씩 모으는 속도예요.",
    }

    if representative_wish is None or daily_pace <= 0:
        result.update({
            "expected_completion_date": None,
            "message_expected_date": None,
            "required_daily_amount": None,
            "message_required_daily": None,
        })
        return result

    remaining_amount = max(representative_wish.target_amount - representative_wish.saved_amount, 0)

    # 현재 페이스 유지 시 달성 예상일
    if remaining_amount == 0:
        expected_date = today
        result["message_expected_date"] = "이미 목표 금액을 달성했어요!"
    else:
        days_needed = remaining_amount / daily_pace
        expected_date = today + timedelta(days=days_needed)
        result["message_expected_date"] = (
            f"지금 페이스를 유지하면 {expected_date.month}월 {expected_date.day}일에 목표를 달성할 수 있어요!"
        )
    result["expected_completion_date"] = expected_date

    # 기한 내 달성을 위한 1일 필요 저축액
    if representative_wish.target_date is not None:
        days_left = (representative_wish.target_date - today).days
        if days_left > 0:
            required_daily = remaining_amount / days_left
            extra_needed = max(required_daily - daily_pace, 0)
            result["required_daily_amount"] = required_daily
            result["message_required_daily"] = (
                f"목표 기간에 맞추려면 매일 {extra_needed:,.0f}원씩 더 저축하면 돼요."
                if extra_needed > 0 else "지금 페이스로도 기한 내 목표 달성이 가능해요!"
            )
        else:
            result["required_daily_amount"] = None
            result["message_required_daily"] = "목표 마감일이 이미 지났어요. 새 목표 기한을 설정해보는 건 어떨까요?"
    else:
        result["required_daily_amount"] = None
        result["message_required_daily"] = None

    return result


# ---------------------------------------------------------------------------
# 10. 최상위 오케스트레이션 함수
# ---------------------------------------------------------------------------

def generate_monthly_recap(
    account_id: str,
    year: int,
    month: int,
    today: date,
    wishes: Sequence[Wish],
    savings_tx: Sequence[SavingsTransaction],
    visits: Sequence[ProfileVisit],
    card_accounts: Sequence[CardAccount],
    users: Sequence[UserProfile],
    academy_name: str,
    age_band: int = 2,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> dict:
    """월말 리캡 전체 데이터를 계산해 하나의 dict로 반환.

    피어 그룹(동일 학원 + 연령대 ±age_band)은 card_accounts/users로부터 자동 선정한다.
    """

    metrics = compute_core_metrics(account_id, year, month, wishes, savings_tx, visits)
    classification = classify_savings_type(metrics, thresholds)
    type_section = build_type_section(classification)

    objective = compute_objective_performance(account_id, year, month, wishes, savings_tx, metrics)
    pattern = compute_pattern_analysis(account_id, year, month, savings_tx, metrics)

    peer_account_ids = select_peer_account_ids(account_id, card_accounts, users, age_band=age_band)
    peer_metrics = compute_peer_group_metrics(peer_account_ids, year, month, wishes, savings_tx)
    my_active_weeks = compute_active_weeks(account_id, year, month, savings_tx)
    group = compute_group_comparison(
        my_active_weeks=my_active_weeks,
        peer_active_weeks=peer_metrics.peer_active_weeks,
        my_achievement_rate=objective.get("curr_rate_pct"),
        peer_achievement_rates=peer_metrics.peer_achievement_rates,
        academy_name=academy_name,
    )

    representative = get_representative_wish(account_id, wishes)
    pace = compute_pace_prediction(representative, metrics.total_savings, today, year, month)

    return {
        "account_id": account_id,
        "year": year,
        "month": month,
        "core_metrics": metrics,
        "type_section": type_section,
        "objective_performance": objective,
        "pattern_analysis": pattern,
        "group_comparison": group,
        "pace_prediction": pace,
    }