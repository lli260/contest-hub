# -*- coding: utf-8 -*-
"""五维含金量评级与状态判定（纯函数，便于离线测试）。"""
from datetime import datetime

from ..config import STALE_DAYS

TIER_WEIGHTS = dict(S=5, A=4, B=3, C=2)

DIMENSIONS = [("tier", "主办方级别"), ("s_difficulty", "获奖难度"),
              ("s_history", "历史积淀"), ("s_policy", "政策挂钩"),
              ("s_industry", "行业认可")]

STATUS_STYLE = {"报名中": "ok", "即将截止": "warn", "报名已截止·待开赛": "gray",
                "即将开赛": "ok", "进行中": "live", "已结束": "over",
                "长期开放": "ok", "日期待定": "todo"}

#: 状态筛选项（首页下拉框）
STATUS_CHOICES = ["进行中", "即将截止", "报名中", "报名已截止·待开赛", "即将开赛",
                  "日期待定", "长期开放", "已结束"]

VERIFY_LABELS = {
    "verified": ("已人工核实", "ok"),
    "manual": ("日期待核实", "warn"),
    "auto": ("自动同步", "gray"),
}


def parse_date(value):
    """把多种写法的日期解析成 date，失败返回 None。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("/", "-").replace(".", "-")
    # 允许带时间部分：只取日期段
    text = text.split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value):
    """解析「YYYY-MM-DD HH:MM」；失败返回 None。"""
    if not value:
        return None
    text = str(value).strip().replace("/", "-").replace("T", " ").replace("+08:00", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    d = parse_date(text)
    return datetime(d.year, d.month, d.day) if d else None


def calc_level(tier, d, h, p, i):
    """加权：主办方级别35% · 获奖难度25% · 政策挂钩15% · 行业认可15% · 历史积淀10%"""
    base = TIER_WEIGHTS.get(tier, 3)
    score = base * .35 + d * .25 + p * .15 + i * .15 + h * .10
    return max(1, min(5, round(score)))


def compute_status(start_date, end_date, reg_deadline, today=None, *,
                   start_at="", end_at="", phase=""):
    """状态判定（优先级从高到低，避免「已结束却显示报名中」）。

    * 没有任何日期 → 「日期待定」（不再把内置的年度大赛说成「长期开放」）
    * 在线赛直接用来源给的阶段（CF 的 CODING / FINISHED）
    """
    today = today or datetime.now().date()
    st, en, dl = parse_date(start_date), parse_date(end_date), parse_date(reg_deadline)
    if phase == "CODING" or phase in ("PENDING_SYSTEM_TEST", "SYSTEM_TEST"):
        return "进行中"
    if phase == "FINISHED":
        return "已结束"
    if not st and not en and not dl:
        return "长期开放"
    if not st and not dl and en:
        # 只有报名截止 / 结束日期（如 Kaggle 只给 deadline）
        if en < today:
            return "已结束"
        return "即将截止" if (en - today).days <= 14 else "报名中"
    if not st and not dl:
        return "日期待定"
    if en and en < today:
        return "已结束"
    if st and st <= today and (not en or en >= today):
        return "进行中"
    if dl and dl >= today and (not st or st > today):
        return "即将截止" if (dl - today).days <= 14 else "报名中"
    if dl and dl < today and st and st > today:
        return "报名已截止·待开赛"
    if st and st > today:          # 未开始且无报名信息（如在线赛）
        return "即将开赛"
    return "已结束"


def _clamp(value):
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return 3


def enrich(c):
    """给比赛字典补充分数/状态/新鲜度等展示字段。"""
    for key in ("s_difficulty", "s_history", "s_policy", "s_industry"):
        c[key] = _clamp(c.get(key))
    c["tier"] = c.get("tier") if c.get("tier") in TIER_WEIGHTS else "B"
    c["level"] = calc_level(c["tier"], c["s_difficulty"], c["s_history"],
                            c["s_policy"], c["s_industry"])

    today = datetime.now().date()
    st, en, dl = parse_date(c["start_date"]), parse_date(c["end_date"]), parse_date(c["reg_deadline"])
    c["status"] = compute_status(c["start_date"], c["end_date"], c["reg_deadline"], today,
                                 start_at=c.get("start_at") or "",
                                 phase=c.get("phase") or "")
    c["days_dl"] = (dl - today).days if dl else None
    c["days_start"] = (st - today).days if st else None

    checked = parse_date(c.get("last_checked")) or parse_date(c.get("info_updated"))
    c["stale"] = bool(checked) and (today - checked).days > STALE_DAYS
    c["data_age_days"] = (today - checked).days if checked else None
    if not c.get("verify_status"):
        c["verify_status"] = "manual" if c.get("source") == "manual" else "auto"
    label, style = VERIFY_LABELS.get(c["verify_status"], VERIFY_LABELS["auto"])
    c["verify_label"], c["verify_style"] = label, style

    # 精确时间展示：有 start_at 时用「10-24 20:00」这种更直观的写法
    start_dt = parse_datetime(c.get("start_at")) if c.get("start_at") else None
    end_dt = parse_datetime(c.get("end_at")) if c.get("end_at") else None
    c["start_dt"] = start_dt
    c["end_dt"] = end_dt
    c["has_time"] = bool(start_dt and start_dt.hour + start_dt.minute)
    if start_dt:
        c["when_text"] = start_dt.strftime("%Y-%m-%d %H:%M")
    elif st:
        c["when_text"] = st.strftime("%Y-%m-%d")
    else:
        c["when_text"] = ""
    if start_dt and end_dt and end_dt.date() == start_dt.date():
        c["duration_text"] = f"{int((end_dt - start_dt).total_seconds() // 60)} 分钟"
    elif start_dt and end_dt:
        c["duration_text"] = f"{max(1, (end_dt - start_dt).days)} 天"
    else:
        c["duration_text"] = ""
    # 导入语句用：优先精确时间（ICS 可以带 TZ，比整天更准）
    c["hidden"] = bool(c.get("missing_since"))
    return c


def enrich_all(db, include_hidden=False):
    sql = "SELECT * FROM competitions"
    if not include_hidden:
        sql += " WHERE missing_since IS NULL OR missing_since=''"
    return [enrich(dict(r)) for r in db.execute(sql)]


def competition_group(c):
    """把「单场在线赛」和「年度大赛」分开，避免时间轴被周赛淹没。"""
    if (c.get("source") or "") in ("builtin", "manual", "curated"):
        return "major"
    return "online"
