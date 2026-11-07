# -*- coding: utf-8 -*-
"""Codeforces 官方 API 数据源。

修复要点（旧实现的问题）：

* 旧代码只保留 ``phase == "BEFORE"``，一旦订阅列表里已经有同 id 的记录，
  比赛进入 CODING 阶段后两条数据（一条 BEFORE、一条 CODING 或
  旧名字）会同时入库，出现「Codeforces Round (Div. 2)」这类**没有编号**的标题；
* 比赛开始时 Codeforces 会把标题里的编号抹掉（``Round 1124 (Div. 2)`` →
  ``Round (Div. 2)``），于是同一场比赛出现两个不同的名字；
* 只取前 20 场，且没有带上精确开始时间 / 时长。

现在改为抓取**全部阶段**，并在来源内部按 id 去重：同一个 id 优先采用
带编号的标题，并记录 phase，让状态判定更准确。
"""
import re

from datetime import datetime, timezone

from .base import (CST, Source, duration_text, html_unescape, http_json,
                   http_text, make_item, title_with_brand)

API_LIST = "https://codeforces.com/api/contest.list"
API_LIST_GYM = "https://codeforces.com/api/contest.list?gym=true"
CONTESTS_URL = "https://codeforces.com/contests"

# Codeforces id >= 100000 为 Gym（训练/校赛/ICPC 镜像），通常不是公开可报名的比赛
GYM_ID_BASE = 100000

_PHASE_ORDER = {"BEFORE": 0, "CODING": 1, "PENDING_SYSTEM_TEST": 2,
                "SYSTEM_TEST": 3, "FINISHED": 4}


class CodeforcesSource(Source):
    key = "codeforces"
    label = "Codeforces"
    group = "算法/编程在线赛"
    homepage = "https://codeforces.com/contests"
    nature = "online"

    def fetch(self):
        data = http_json(API_LIST, timeout=20)
        titles = {}
        try:  # 比赛列表中未开始的场次会隐藏编号，用比赛页补全真实标题
            titles = scrape_contest_titles(http_text(CONTESTS_URL, timeout=20))
        except Exception:
            titles = {}
        return parse_contests(data, titles=titles)


def scrape_contest_titles(html):
    """从 /contests 页面抽取 {contest_id: 完整标题}，用于补全被抹掉的编号。

    页面结构为 ``<tr data-contestId="2276"> <td>标题<br/><a href="/contest/2276">Enter »</a>``，
    标题位于第一列、并可能紧跟空的 ``a[data-contestId]`` 锚点，需在这个锚点处截断。
    """
    out = {}
    for row in re.split(r"<tr\b", html or ""):
        m = re.search(r'data-contestId="(\d+)"', row)
        if not m:
            continue
        cell = re.search(r"<td[^>]*>(.*?)</td>", row, re.S)
        if not cell:
            continue
        body = cell.group(1)
        anchor = re.search(r"<a\b", body)  # 第一列后面紧跟着 Enter / Virtual 等按钮
        if anchor:
            body = body[:anchor.start()]
        title = re.sub(r"<[^>]+>", " ", body)
        title = html_unescape(re.sub(r"\s+", " ", title)).strip()
        if title and title not in ("Register", "Enter »"):
            out[int(m.group(1))] = title
    return out


def _title_has_number(name):
    """标题里是否仍带场次编号（如 ``Round 1127``）。

    注意不能简单地判断「有没有数字」：``Round (Div. 2)`` 里的 ``2`` 是难度分区，
    并非场次号。这里要求出现 3 位以上的数字（CF 的场次号已是 4 位数）。
    """
    return bool(re.search(r"\d{3,}", name or ""))


def parse_contests(data, limit=40, now=None, include_finished_days=7, titles=None):
    """把 contest.list 结果转成规范化条目。

    返回最近（含刚结束的若干天）到全部未开始的比赛；同一 id 只保留一条。
    ``titles`` 可选：{contest_id: 完整标题}，用于补全被抹掉编号的名字。
    """
    titles = titles or {}
    if not isinstance(data, dict) or data.get("status") != "OK":
        raise ValueError("Codeforces API 返回异常")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_ts = now.timestamp()

    best = {}
    for c in data.get("result", []) or []:
        cid = c.get("id")
        secs = c.get("startTimeSeconds")
        if not cid or not secs:
            continue
        if cid >= GYM_ID_BASE:  # Gym 无公开报名页，跳过
            continue
        phase = c.get("phase") or ""
        name = (titles.get(int(cid)) or c.get("name") or "").strip()
        if not name:
            continue
        key = int(cid)
        prev = best.get(key)
        # 同一 id 只保留信息量最高的那条：带编号 > 未结束阶段 > 名字更长
        rank = (0 if _title_has_number(name) else 1, _PHASE_ORDER.get(phase, 9), -len(name))
        if prev is None or rank < prev["_rank"]:
            best[key] = {"_rank": rank, "raw": c, "phase": phase, "name": name,
                         "start": int(secs), "duration": c.get("durationSeconds") or 7200}

    out = []
    for cid, rec in sorted(best.items(), key=lambda kv: kv[1]["start"]):
        start_ts = rec["start"]
        end_ts = start_ts + int(rec["duration"] or 0)
        phase = rec["phase"]
        if phase == "FINISHED" or phase in ("SYSTEM_TEST", "PENDING_SYSTEM_TEST"):
            # 只展示刚结束若干天内的比赛（更早的没人关心，API 里几千条）
            if end_ts < now_ts - include_finished_days * 86400:
                continue
        start = datetime.fromtimestamp(start_ts, tz=CST)
        end = datetime.fromtimestamp(end_ts, tz=CST)
        hours = duration_text(rec["duration"])
        ctype = rec["raw"].get("type") or ""
        title = title_with_brand(rec["name"], "Codeforces")
        desc = (f"Codeforces 在线赛，{start.strftime('%Y-%m-%d %H:%M')}（北京时间）开始，"
                f"时长 {hours}，会后按表现计入 rating")
        if ctype:
            desc += f"。赛制类型：{ctype}"
        out.append(make_item(
            title,
            f"https://codeforces.com/contests/{cid}",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            start_at=start.strftime("%Y-%m-%d %H:%M"),
            end_at=end.strftime("%Y-%m-%d %H:%M"),
            organizer="Codeforces",
            desc=desc + "。",
            tags=["个人赛", "免费", "rating 赛"],
            tier="B", difficulty=4,
            source_id=f"cf-{cid}",
            status=phase,
        ))
        if len(out) >= limit:
            break
    return out
