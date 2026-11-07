# -*- coding: utf-8 -*-
"""LeetCode（力扣中国站）比赛列表。

leetcode.cn 的 ``/contest/api/list/`` 返回全部历史赛事（可用的标题是站内
``第 525 场周赛`` / ``第 194 场双周赛`` 这种**中文原始标题**），旧实现的问题：

* 只保留 ``start_time > 现在`` 的场次，周末两天前结束的比赛就再也看不到；
* 完全没有结束时间，卡片上只能看到开始日期。

现在补上时长换算出的结束日期，并把「周赛 / 双周赛」写进标签便于筛选。
"""
import time
from datetime import datetime

from .base import CST, Source, duration_text, http_json, make_item

LIST_URL = "https://leetcode.cn/contest/api/list/"


class LeetCodeSource(Source):
    key = "leetcode"
    label = "LeetCode 力扣"
    group = "算法/编程在线赛"
    homepage = "https://leetcode.cn/contest/"
    nature = "online"

    def fetch(self):
        return parse_contests(http_json(LIST_URL, timeout=25,
                                        headers={"Referer": "https://leetcode.cn/contest/"}))


def parse_contests(data, limit=20, now=None, past_grace_days=1):
    """保留未开始 / 正在进行 / 刚结束（默认 1 天内）的比赛。"""
    now = now if now is not None else time.time()
    out = []
    contests = (data or {}).get("contests", []) or []
    contests = sorted(contests, key=lambda c: c.get("start_time") or 0)
    for c in contests:
        ts = c.get("start_time") or c.get("origin_start_time")
        if not ts:
            continue
        duration = int(c.get("duration") or 5400)
        if ts + duration < now - past_grace_days * 86400:
            continue
        start = datetime.fromtimestamp(ts, tz=CST)
        end = datetime.fromtimestamp(ts + duration, tz=CST)
        slug = c.get("title_slug") or c.get("id")
        title = (c.get("title") or "").strip()
        kind = "双周赛" if "双周" in title else ("周赛" if "周赛" in title else "比赛")
        tags = ["个人赛", "免费", "面试高频", kind]
        desc = (f"力扣{kind}，{start.strftime('%Y-%m-%d %H:%M')}（北京时间）开始，"
                f"时长 {duration_text(duration)}；赛后按排名计入 rating。")
        out.append(make_item(
            f"LeetCode {title}".strip(),
            f"https://leetcode.cn/contest/{slug}/",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            start_at=start.strftime("%Y-%m-%d %H:%M"),
            end_at=end.strftime("%Y-%m-%d %H:%M"),
            organizer="力扣 LeetCode",
            desc=desc,
            tags=tags,
            tier="C", difficulty=3,
            source_id=f"leetcode-{c.get('id')}",
        ))
        if len(out) >= limit:
            break
    return out
