# -*- coding: utf-8 -*-
"""AtCoder 比赛数据源。

旧实现只有一个正则：

    <time>…</time>.*?<a href="/contests/(\\w+)">([^<]*)</a>

它在真实页面上一行都匹配不到——列表页里 ``</time>`` 与 ``<a>`` 之间还隔着
``</a></td><td><span …></span><span …></span> `` 一大段标签，于是 AtCoder 来源
长期是「实验性 / 无数据」状态。

现在改为：

1. 解析 ``#contest-table-upcoming`` 表格里的每一行（开始时间 / 名称 / 时长 / 难度区间），
   这是官方列表页的稳定结构；
2. 名称优先使用 kenkoooo 的 AtCoder Problems 公开数据（``contests.json``），
   它保存的是**原始比赛名**（例如 ``Toyota Programming Contest 2024#1（AtCoder Beginner Contest 337）``），
   比列表页里被缩短过的名字信息更全；拿不到时自动退回列表页的名字；
3. 时间按日本时间（+0900）换算成北京时间，避免「比赛日期差一天」。
"""
import re
from datetime import timedelta

from .base import (JST, Source, duration_text, http_json, http_text, make_item,
                   md_datetime, parse_iso_datetime, title_with_brand)

LIST_URL = "https://atcoder.jp/contests/?lang=en"
ARCHIVE_URL = "https://kenkoooo.com/atcoder/resources/contests.json"

_RATE = {"abc": ("ABC", 2), "arc": ("ARC", 3), "agc": ("AGC", 4),
         "ahc": ("AHC 启发式", 4), "awc": ("AWC", 2)}

_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_TIME_RE = re.compile(r"<time[^>]*>\s*([\d\-/: ]+?)(\+\d{4})?\s*</time>", re.S)
_LINK_RE = re.compile(r'<a href="/contests/([\w\-]+)"[^>]*>(.*?)</a>', re.S)
_DUR_RE = re.compile(r"(\d+(?::\d+){1,2})")
_RATE_RANGE_RE = re.compile(r'<td class="text-center">\s*([\d\s\-]*)\s*</td>\s*</tr>')
_TAG_RE = re.compile(r"<[^>]+>")


class AtCoderSource(Source):
    key = "atcoder"
    label = "AtCoder"
    group = "算法/编程在线赛"
    homepage = "https://atcoder.jp/contests/"
    nature = "online"

    def fetch(self):
        html = http_text(LIST_URL, timeout=20)
        archive = {}
        try:  # archive 只用于补全标题，失败不应影响主流程
            archive = _load_archive(http_json(ARCHIVE_URL, timeout=25))
        except Exception:
            archive = {}
        return parse_contests(html, archive=archive)


def _clean_text(html):
    text = _TAG_RE.sub(" ", html or "")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">") \
               .replace("&#39;", "'").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def _load_archive(data):
    """kenkoooo contests.json -> {contest_id: title}。"""
    out = {}
    for c in data or []:
        cid = (c or {}).get("id")
        title = ((c or {}).get("title") or "").strip()
        if cid and title:
            out[cid] = title
    return out


def _duration_minutes(text):
    """'01:40' -> 100；'240:00' -> 14400。"""
    if not text:
        return 0
    parts = [int(p) for p in text.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def _rated_range(cid, title):
    """按赛制推测 AtCoder 的 rated 区间（列表页某些行取不到时用）。"""
    low = cid.lower()
    if low.startswith("abc"):
        return "~ 1999"
    if low.startswith("arc"):
        return "~ 2799"
    if low.startswith("agc"):
        return "1200 ~"
    return ""


def parse_contests(html, limit=30, archive=None):
    """从列表页 HTML 提取比赛（按官方表格结构解析）。"""
    archive = archive or {}
    html = html or ""
    # 只解析 upcoming 表格，避免把历史 / daily 场次混进来
    start = html.find('id="contest-table-upcoming"')
    if start >= 0:
        end = html.find('id="contest-table-', start + 10)
        html = html[start:end if end > 0 else len(html)]

    out, seen = [], set()
    for row_html in _ROW_RE.findall(html):
        tm = _TIME_RE.search(row_html)
        link = _LINK_RE.search(row_html)
        if not tm or not link:
            continue
        cid = link.group(1)
        if cid in seen:
            continue
        # 只保留真正的比赛链接；排除 /contests/ 下的官方占位锚点
        raw_title = _clean_text(link.group(2))
        if not raw_title:
            continue
        seen.add(cid)

        tz = tm.group(2) or "+0900"
        start = f"{tm.group(1).strip()}{tz}"
        # 时长：表格第三列 01:40 形式
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
        duration_cell = ""
        rated = ""
        for cell in cells:
            text = _clean_text(cell)
            if _DUR_RE.fullmatch(text or ""):
                duration_cell = text
            elif re.fullmatch(r"[\d\s]+\-[\s\d]*", text or "") or text == "All":
                rated = text
        minutes = _duration_minutes(duration_cell)

        prefix = cid[:3].lower()
        label, difficulty = _RATE.get(prefix, (prefix.upper() or "比赛", 2))
        # 名称：archive 里的原始全名优先（信息更全），否则用列表页名字
        name_text = archive.get(cid) or raw_title
        name = title_with_brand(name_text, "AtCoder")
        if not rated:
            rated = _rated_range(cid, name_text)

        # 用 start/end 日期把长赛（AHC 240 小时）也标清楚
        start_at = md_datetime(start, default_tz=JST)
        if not minutes:
            # 表格里没给时长时按 2 小时兜底
            minutes = 120
        end_at = ""
        dt = parse_iso_datetime(start, default_tz=JST)
        if dt:
            end_at = (dt + timedelta(minutes=minutes)).astimezone(JST) \
                .strftime("%Y-%m-%d %H:%M+0900")
            end_at = md_datetime(end_at, default_tz=JST)

        desc = (f"AtCoder {label} 场次，{start_at}（北京时间）开始，"
                f"时长 {duration_text(minutes * 60)}")
        if rated:
            desc += f"，rated 区间 {rated}"
        desc += "。ABC 适合入门，ARC/AGC 难度更高。"

        tags = ["个人赛", "免费"]
        if prefix in ("abc", "arc", "agc"):
            tags.append("rating 赛")

        out.append(make_item(
            name,
            f"https://atcoder.jp/contests/{cid}",
            start_date=start_at[:10],
            end_date=end_at[:10],
            start_at=start_at,
            end_at=end_at,
            organizer="AtCoder",
            desc=desc,
            tags=tags,
            tier="B", difficulty=difficulty,
            source_id=f"atcoder-{cid}",
            ratings=rated,
        ))
        if len(out) >= limit:
            break
    return out
