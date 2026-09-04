# -*- coding: utf-8 -*-
"""
배치 연산 결과를 UI 렌더링용(view)과 내부 분석용(internal_metrics)으로 분리하는 직렬화기
"""

from __future__ import annotations
from dataclasses import asdict
from datetime import date, datetime
import json


def _json_serial(obj):
    """date/datetime 객체를 ISO 포맷 문자열로 변환하는 헬퍼"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def present_weekly_recap(raw_result: dict) -> dict:
    """주간 활동 요약: 화면용(view)과 내부용(internal_metrics) 분리"""
    p1 = raw_result["page1_last_week_performance"]
    achv = p1["weekly_achievement"]
    mile = p1["representative_milestone"]
    streak = p1["streak"]
    p2 = raw_result["page2_growth_report"]
    p3 = raw_result["page3_academy_success_stories"]

    # 프론트엔드/화면에 바로 바인딩할 데이터
    view = {
        "period": {
            "week_start": raw_result["week_start"],
            "week_end": raw_result["week_end"],
        },
        # 1페이지: 지난주 성과
        "page1_last_week_performance": {
            "achievement": {
                "save_count": achv["save_count"],
                "net_savings": achv["net_savings"],
                "new_wish_count": achv["new_wish_count"],
                "message": achv["message"],
            },
            "milestone": {
                "wish_title": mile.get("wish_title"),
                "rate_before": mile.get("rate_before"),
                "rate_after": mile.get("rate_after"),
                "message": mile.get("message"),
            },
            "streak": {
                "streak_weeks": streak["streak_weeks"],
                "message": streak["message"],
            },
        },
        # 2페이지: 성장 리포트
        "page2_growth_report": {
            "total_visits": p2["total_visits"],
            "unique_visitors": p2["unique_visitors"],
            "growth_pct": p2["growth_pct"],
            "message_visits": p2["message_visits"],
            "message_growth": p2["message_growth"],
        },
        # 3페이지: 학원 친구들의 성공 스토리 (텍스트 대신 wish_id + type_title 쌍의 리스트)
        "page3_academy_success_stories": {
            "message_summary": p3.get("message_summary") or p3.get("message"),
            "stories": p3.get("stories", []),
        },
    }

    # 내부 분석, QA, 디버깅용 메트릭 (UI에서는 사용하지 않음)
    internal_metrics = {
        "account_id": raw_result["account_id"],
        "milestone_crossed": mile.get("crossed", []),
        "prev_total_visits": p2["prev_total_visits"],
    }

    return {
        "view": view,
        "internal_metrics": internal_metrics,
    }


def present_monthly_recap(raw_result: dict, is_active: bool = True) -> dict:
    """월말 리캡: 화면용(view)과 내부용(internal_metrics) 분리"""
    core = asdict(raw_result["core_metrics"])
    t_sec = raw_result["type_section"]
    obj_sec = raw_result["objective_performance"]
    pat_sec = raw_result["pattern_analysis"]
    grp_sec = raw_result["group_comparison"]
    pace_sec = raw_result["pace_prediction"]

    # 프론트엔드/화면에 바로 바인딩할 데이터
    view = {
        "period": {
            "year": raw_result["year"],
            "month": raw_result["month"],
        },
        "is_active": is_active,
        # 0. 4가지 저축 유형
        "type_section": {
            "type_title": t_sec["type_title"],
            "message": t_sec["message"],
        },
        # 1. 객관적 성과
        "objective_performance": {
            "total_savings": obj_sec["total_savings"],
            "completed_wish_count": obj_sec["completed_wish_count"],
            "representative_wish_title": obj_sec.get("representative_wish_title"),
            "prev_rate_pct": obj_sec.get("prev_rate_pct"),
            "curr_rate_pct": obj_sec.get("curr_rate_pct"),
            "message_total_savings": obj_sec["message_total_savings"],
            "message_completed_count": obj_sec["message_completed_count"],
            "message_rate_change": obj_sec.get("message_rate_change"),
        },
        # 2. 저축 패턴 분석
        "pattern_analysis": {
            "top_week": pat_sec.get("top_week"),
            "top_weekday": pat_sec.get("top_weekday"),
            "message_week_weekday": pat_sec["message_week_weekday"],
            "message_regularity": pat_sec["message_regularity"],
            "message_avg_amount": pat_sec["message_avg_amount"],
        },
        # 3. 그룹 내 비교
        "group_comparison": {
            "habit_percentile": grp_sec.get("habit_percentile"),
            "habit_percentile_status": grp_sec.get("habit_percentile_status"),
            "achievement_percentile": grp_sec.get("achievement_percentile"),
            "achievement_percentile_status": grp_sec.get("achievement_percentile_status"),
            "message_habit": grp_sec.get("message_habit"),
            "message_achievement": grp_sec.get("message_achievement"),
        },
        # 4. 페이스 분석 및 성공 가능성 예측
        "pace_prediction": {
            "daily_pace": pace_sec.get("daily_pace"),
            "expected_completion_date": pace_sec.get("expected_completion_date"),
            "required_daily_amount": pace_sec.get("required_daily_amount"),
            "message_daily_pace": pace_sec.get("message_daily_pace"),
            "message_expected_date": pace_sec.get("message_expected_date"),
            "message_required_daily": pace_sec.get("message_required_daily"),
        },
    }

    # 내부 분석, QA, 판별 조건 검증용 메트릭
    internal_metrics = {
        "account_id": raw_result["account_id"],
        "core_metrics": {
            "save_count": core["save_count"],
            "avg_amount": core["avg_amount"],
            "regularity_std": core["regularity_std"],
            "pace_bias": core["pace_bias"],
            "abandon_count": core["abandon_count"],
            "transfer_count": core["transfer_count"],
            "visit_count": core["visit_count"],
        },
        "classification_debug": {
            "priority_matched": t_sec["priority_matched"],
            "is_fallback": t_sec["is_fallback"],
        },
    }

    return {
        "view": view,
        "internal_metrics": internal_metrics,
    }


def to_json(data: dict) -> str:
    """JSON 문자열로 직렬화"""
    return json.dumps(data, ensure_ascii=False, indent=2, default=_json_serial)
