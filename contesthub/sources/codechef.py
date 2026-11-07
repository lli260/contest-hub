# -*- coding: utf-8 -*-
"""CodeChef 比赛列表（官方站点公开 JSON）。

旧实现把 ``contest_start_date_iso`` 直接截前 10 位当日期，丢掉时间后
所有场次都显示成「当天」，且没有精确时刻。现在保留到分钟（换算北京时间）
并计算结束时间。
"""
from .base import (Source, duration_text, http_json, make_item, md_date,
                   md_datetime, title_with_brand)

API = "https://www.codechef.com/api/list/contests/all"


class CodeChefSource(Source):
    key = "codechef"
    label = "CodeChef"
    group = "算法/编程在线赛"
    homepage = "https://www.codechef.com/contests"
    nature = "online"

    def fetch(self):
        return parse_contests(http_json(API, timeout=25))


def _minutes(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def parse_contests(data, limit=20):
    """present_contests（进行中） + future_contests（未开始）。"""
    if not isinstance(data, dict) or data.get("status") not in (None, "success"):
        raise ValueError("CodeChef 返回异常")
    out, seen = [], set()
    for group in ("present_contests", "future_contests"):
        for c in data.get(group, []) or []:
            code = c.get("contest_code")
            if not code or code in seen:
                continue
            seen.add(code)
            raw = code.upper()
            if "START" in raw:
                label, difficulty, tag = "Starters 常规赛", 3, "rating 赛"
            elif "COOK" in raw:
                label, difficulty, tag = "Cook-Off 算法赛", 3, "rating 赛"
            elif "LTIME" in raw or "LUNCH" in raw:
                label, difficulty, tag = "Lunchtime 算法赛", 3, "rating 赛"
            else:
                label, difficulty, tag = "特色赛事", 3, ""
            name_raw = (c.get("contest_name") or code).strip()
            start_iso = c.get("contest_start_date_iso") or c.get("contest_start_date")
            end_iso = c.get("contest_end_date_iso") or c.get("contest_end_date")
            mins = _minutes(c.get("contest_duration"))
            start_at = md_datetime(start_iso)
            end_at = md_datetime(end_iso)
            desc = f"CodeChef {label}（{code}），{start_at}（北京时间）开始"
            if mins:
                desc += f"，时长 {duration_text(mins * 60)}"
            desc += "。"
            tags = ["个人赛", "免费"] + ([tag] if tag else [])
            out.append(make_item(
                title_with_brand(name_raw, "CodeChef"),
                f"https://www.codechef.com/{code}",
                start_date=md_date(start_iso),
                end_date=md_date(end_iso),
                start_at=start_at,
                end_at=end_at,
                organizer="CodeChef",
                desc=desc,
                tags=tags,
                tier="B", difficulty=difficulty,
                source_id=f"codechef-{code}",
            ))
            if len(out) >= limit:
                return out
    return out
