"""Adapter from recap-generation-v1 DTOs to the existing pure recap functions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from monthly_recap import (
    CoreMetrics, SavingsTransaction, TransactionType, Wish, WishStatus,
    build_type_section, classify_savings_type, compute_core_metrics,
    compute_group_comparison, compute_objective_performance, compute_pace_prediction,
    compute_pattern_analysis, get_representative_wish,
)
from recap_presenter import present_monthly_recap, present_weekly_recap
from weekly_recap import (
    build_streak_section, build_weekly_achievement_section,
    compute_representative_milestone, compute_streak_weeks,
    compute_weekly_achievement,
)

SEOUL = ZoneInfo("Asia/Seoul")
STATUS = {
    "IN_PROGRESS": WishStatus.IN_PROGRESS,
    "AMOUNT_REACHED": WishStatus.REACHED,
    "COMPLETED": WishStatus.COMPLETED,
    "ABANDONED": WishStatus.ABANDONED,
}
TX_TYPE = {
    "DEPOSIT": TransactionType.DEPOSIT,
    "WITHDRAWAL": TransactionType.WITHDRAWAL,
    "TRANSFER_OUT": TransactionType.TRANSFER_OUT,
    "TRANSFER_IN": TransactionType.TRANSFER_IN,
    "COMPLETION_RETURN": TransactionType.REFUND,
    "ABANDONMENT_RETURN": TransactionType.REFUND,
    "DELETION_RETURN": TransactionType.REFUND,
}


def _local(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(SEOUL).replace(tzinfo=None)


def _domain(request: dict[str, Any]) -> tuple[list[Wish], list[SavingsTransaction]]:
    account = request["card_balance_account_id"]
    academy = request["academy_id"]
    wishes = [
        Wish(
            wish_id=item["wish_id"], account_id=account, academy_id=academy,
            title=item["title"], target_amount=item["target_amount"], target_date=None,
            is_representative=item["is_representative"], status=STATUS[item["status"]],
            created_at=_local(item["created_at"]), closed_at=_local(item["closed_at"]),
            deleted_at=_local(item["deleted_at"]), saved_amount=item["saved_amount_at_period_end"],
        )
        for item in request["input"]["wishes"]
    ]
    transactions = [
        SavingsTransaction(
            transaction_id=item["root_event_id"], account_id=account, wish_id=item["wish_id"],
            type=TX_TYPE[item["type"]], amount=item["amount"], created_at=_local(item["occurred_at"]),
        )
        for item in request["input"]["effective_transactions"]
    ]
    return wishes, transactions


def _weekly(request: dict[str, Any], wishes: list[Wish], txs: list[SavingsTransaction]) -> dict[str, Any]:
    account = request["card_balance_account_id"]
    start = date.fromisoformat(request["period"]["start_date"])
    end = date.fromisoformat(request["period"]["end_date_exclusive"])
    week_start = datetime.combine(start, datetime.min.time())
    week_end = datetime.combine(end, datetime.min.time())
    achievement = compute_weekly_achievement(account, week_start, week_end, wishes, txs)
    milestone = compute_representative_milestone(account, week_start, week_end, wishes, txs, week_end)
    visits = request["input"]["visit_metrics"]
    total = visits["received_visit_count"]
    previous = visits["previous_week_received_visit_count"]
    growth = round((total - previous) / previous * 100) if previous else None
    stories = [
        {"wish_id": item["wish_id"], "type_title": item["type_title"]}
        for item in request["input"]["success_story_candidates"]
    ]
    raw = {
        "account_id": account,
        "week_start": start,
        "week_end": end - timedelta(days=1),
        "page1_last_week_performance": {
            "weekly_achievement": build_weekly_achievement_section(achievement),
            "representative_milestone": milestone,
            "streak": build_streak_section(compute_streak_weeks(account, week_start, week_end, txs)),
        },
        "page2_growth_report": {
            "total_visits": total,
            "unique_visitors": visits["unique_received_visitor_count"],
            "prev_total_visits": previous,
            "growth_pct": growth,
            "message_visits": f"지난주 내 프로필을 {total}번 방문했어요." if total else "지난주 프로필 방문은 없었어요.",
            "message_growth": f"전주보다 방문이 {growth}% 변했어요." if growth is not None else None,
        },
        "page3_academy_success_stories": {
            "stories": stories,
            "message_summary": f"우리 학원 친구 {len(stories)}명이 목표를 이뤘어요!" if stories else "지난주엔 아직 완주한 학원 친구가 없어요. 이번 주 첫 주인공이 되어볼까요?",
        },
    }
    return present_weekly_recap(raw)


def _monthly(request: dict[str, Any], wishes: list[Wish], txs: list[SavingsTransaction]) -> dict[str, Any]:
    account = request["card_balance_account_id"]
    start = date.fromisoformat(request["period"]["start_date"])
    reference = date.fromisoformat(request["reference_date"])
    metrics = compute_core_metrics(account, start.year, start.month, wishes, txs, [])
    visit_count = request["input"]["visit_metrics"]["monthly_outgoing_visit_count"]
    metrics = CoreMetrics(
        save_count=metrics.save_count, total_savings=metrics.total_savings,
        avg_amount=metrics.avg_amount, regularity_std=metrics.regularity_std,
        pace_bias=metrics.pace_bias, abandon_count=metrics.abandon_count,
        transfer_count=metrics.transfer_count, visit_count=visit_count,
    )
    objective = compute_objective_performance(account, start.year, start.month, wishes, txs, metrics)
    period_end = datetime.combine(date.fromisoformat(request["period"]["end_date_exclusive"]), datetime.min.time())
    history_start = period_end - timedelta(weeks=52)
    my_active_weeks = len({
        item.created_at.date() - timedelta(days=item.created_at.weekday())
        for item in txs
        if history_start <= item.created_at < period_end and item.type in {TransactionType.DEPOSIT, TransactionType.TRANSFER_IN}
    })
    peers = request["input"]["peer_metrics"]
    representative = get_representative_wish(account, wishes)
    my_rate = None if representative is None or representative.target_amount <= 0 else representative.saved_amount / representative.target_amount * 100
    group = compute_group_comparison(
        my_active_weeks, peers["habit_active_weeks"], my_rate,
        peers["achievement_rates"], "학원",
    )
    raw = {
        "account_id": account, "year": start.year, "month": start.month,
        "core_metrics": metrics,
        "type_section": build_type_section(classify_savings_type(metrics)),
        "objective_performance": objective,
        "pattern_analysis": compute_pattern_analysis(account, start.year, start.month, txs, metrics),
        "group_comparison": group,
        "pace_prediction": compute_pace_prediction(representative, metrics.total_savings, reference, start.year, start.month, txs),
    }
    return present_monthly_recap(raw, is_active=metrics.save_count >= 3)


def generate_recap(request: dict[str, Any]) -> dict[str, Any]:
    wishes, transactions = _domain(request)
    presented = _weekly(request, wishes, transactions) if request["kind"] == "WEEKLY" else _monthly(request, wishes, transactions)
    return {
        "schema_version": request["schema_version"],
        "algorithm_version": request["algorithm_version"],
        "generation_id": request["generation_id"],
        "input_digest": request["input_digest"],
        "student_id": request["student_id"],
        "card_balance_account_id": request["card_balance_account_id"],
        "academy_id": request["academy_id"],
        "kind": request["kind"],
        "period": request["period"],
        "view": presented["view"],
        "internal_metrics": presented["internal_metrics"],
    }
