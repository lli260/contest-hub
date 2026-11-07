# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta

from contesthub.rules.rating import (STATUS_STYLE, calc_level, compute_status, enrich,
                               parse_date, parse_datetime)


def test_parse_date_variants():
    assert parse_date("2026-09-11") == date(2026, 9, 11)
    assert parse_date("2026/9/11") == date(2026, 9, 11)
    assert parse_date("2026-09-11T00:00:31+05:30") == date(2026, 9, 11)
    assert parse_date("") is None
    assert parse_date("不是日期") is None


def test_parse_datetime():
    assert parse_datetime("2026-10-24 20:00") == datetime(2026, 10, 24, 20, 0)
    assert parse_datetime("2026-10-24T20:00") == datetime(2026, 10, 24, 20, 0)
    assert parse_datetime("2026-10-24") == datetime(2026, 10, 24)
    assert parse_datetime("") is None


def test_calc_level_monotonic():
    assert calc_level("S", 5, 5, 5, 5) == 5
    assert calc_level("C", 1, 1, 1, 1) == 1
    # 主办方级别权重最高
    assert calc_level("S", 1, 1, 1, 1) > calc_level("C", 1, 1, 1, 1)


def test_status_ended_is_not_open():
    today = date(2026, 9, 26)
    # 结束日期已过 → 已结束，即便有未来的报名截止
    assert compute_status("2026-08-01", "2026-08-05", "2026-09-30", today) == "已结束"
    assert compute_status("2026-11-01", "", "2026-10-20", today) == "报名中"
    assert compute_status("2026-09-20", "", "", today) == "进行中"
    assert compute_status("", "", "", today) == "长期开放"
    # 报名已截止、尚未开赛
    assert compute_status("2026-11-01", "", "2026-09-01", today) == "报名已截止·待开赛"
    # 14 天内截止 → 即将截止
    assert compute_status("2026-12-01", "", "2026-10-01", today) == "即将截止"
    # 在线赛：未来开赛且无报名截止 → 即将开赛（不能被误判为已结束）
    assert compute_status("2026-09-27", "", "", today) == "即将开赛"
    assert compute_status("2027-01-01", "", "", today) == "即将开赛"


def test_status_for_annual_events_without_dates():
    """年度大赛官网还没公布日期时，显示「日期待定」而不是误导性的「长期开放」。"""
    today = date(2026, 10, 18)
    assert compute_status("", "", "", today) == "长期开放"
    assert compute_status("", "", "", today) == "长期开放"


def test_status_uses_source_phase():
    """Codeforces 等来源给出的阶段直接决定状态。"""
    today = date(2026, 10, 18)
    assert compute_status("2026-10-17", "", "", today, phase="CODING") == "进行中"
    assert compute_status("2026-10-17", "", "", today, phase="FINISHED") == "已结束"


def test_status_deadline_only():
    """Kaggle 只给截止日期的情况。"""
    today = date(2026, 10, 18)
    assert compute_status("", "2026-11-02", "", today) == "报名中"
    assert compute_status("", "2026-10-20", "", today) == "即将截止"
    assert compute_status("", "2026-09-01", "", today) == "已结束"


def test_every_status_has_a_style():
    for status, style in STATUS_STYLE.items():
        assert style and style.islower()


def test_enrich_staleness_and_level():
    old = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    fresh = date.today().strftime("%Y-%m-%d")
    comp = enrich({"tier": "A", "s_difficulty": 4, "s_history": 4, "s_policy": 4,
                   "s_industry": 4, "start_date": "", "end_date": "",
                   "reg_deadline": "", "last_checked": old, "source": "kaggle"})
    assert comp["stale"] is True
    assert comp["level"] == calc_level("A", 4, 4, 4, 4)
    comp2 = enrich({"tier": "B", "s_difficulty": 3, "s_history": 3, "s_policy": 3,
                    "s_industry": 3, "start_date": "", "end_date": "",
                    "reg_deadline": "", "last_checked": fresh, "source": "manual"})
    assert comp2["stale"] is False
    assert comp2["verify_status"] == "manual"
    assert comp2["verify_label"] == "日期待核实"


def test_enrich_adds_display_fields():
    comp = enrich({"tier": "B", "s_difficulty": 3, "s_history": 3, "s_policy": 3,
                   "s_industry": 3, "start_date": "2026-10-24",
                   "start_at": "2026-10-24 20:00", "end_at": "2026-10-24 21:40",
                   "end_date": "2026-10-24", "reg_deadline": "", "source": "atcoder",
                   "last_checked": "2026-10-18", "verify_status": "auto"})
    assert comp["has_time"] is True
    assert comp["when_text"] == "2026-10-24 20:00"
    assert comp["duration_text"] == "100 分钟"
    assert comp["verify_label"] == "自动同步"
    assert comp["hidden"] is False


def test_enrich_marks_hidden():
    comp = enrich({"tier": "B", "s_difficulty": 3, "s_history": 3, "s_policy": 3,
                   "s_industry": 3, "start_date": "", "end_date": "",
                   "reg_deadline": "", "missing_since": "2026-10-01"})
    assert comp["hidden"] is True


def test_enrich_clamps_bad_scores():
    comp = enrich({"tier": "X", "s_difficulty": None, "s_history": "abc",
                   "s_policy": 9, "s_industry": -3, "start_date": "", "end_date": "",
                   "reg_deadline": ""})
    assert comp["tier"] == "B"
    assert comp["s_difficulty"] == 3
    assert comp["s_history"] == 3
    assert comp["s_policy"] == 5   # 超出范围被 clamp 到 1~5
    assert comp["s_industry"] == 1
    assert 1 <= comp["level"] <= 5
