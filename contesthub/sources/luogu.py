# -*- coding: utf-8 -*-
"""洛谷 Luogu 比赛列表（国内最大的中文 OJ 之一）。

洛谷只有 ``/contest/list`` 页面能拿到赛程（接口需要登录态 + 防爬校验）。
页面把整份数据以 ``<script id="lentille-context" type="application/json">``
内嵌在 HTML 里，字段很全，例如：

    {"data": {"contests": {"count": 1393, "result": [{
        "id": 364653, "startTime": 1792821600, "endTime": 1792839600,
        "name": "【LGR-311-Div.2】洛谷 10 月月赛 IV …",
        "method": 4, "rated": 3, "host": {"name": "洛谷官方团队"}}]}}}

- ``method``: 1 IOI / 2 ACM / 3 OI / 4 乐多（按 submission 计分）/ 5 其它
- ``rated`` ≠ 0 表示计入洛谷比赛 rating
- ``host`` 为主办方，``squad`` 表示是否需要组队

旧版本完全没有洛谷这个来源，而它是国内选手最常参加的在线赛平台之一。
"""
import json
import re
from datetime import datetime

from .base import CST, Source, http_text, make_item

LIST_URL = "https://www.luogu.com.cn/contest/list"
_CONTEXT_RE = re.compile(
    r'<script id="lentille-context" type="application/json">(.*?)</script>', re.S)

_METHOD = {1: "IOI 赛制", 2: "ACM 赛制", 3: "OI 赛制", 4: "乐多赛制", 5: "其它赛制"}
_RATED = {0: "", 1: "rated", 2: "rated", 3: "rated", 4: "rated", 5: "rated"}


class LuoguSource(Source):
    key = "luogu"
    label = "洛谷 Luogu"
    group = "算法/编程在线赛"
    homepage = "https://www.luogu.com.cn/contest/list"
    nature = "online"

    def fetch(self):
        html = http_text(LIST_URL, timeout=25,
                         headers={"Referer": "https://www.luogu.com.cn/"})
        return parse_contests(html)


def _ts(value):
    try:
        return datetime.fromtimestamp(int(value), tz=CST)
    except (TypeError, ValueError):
        return None


def parse_contests(html, limit=20, now=None):
    """从列表页提取比赛（只取未开始 / 进行中的）。"""
    m = _CONTEXT_RE.search(html or "")
    if not m:
        return []
    try:
        payload = json.loads(m.group(1))
    except ValueError:
        return []
    result = (((payload.get("data") or {}).get("contests") or {}).get("result")) or []
    now_ts = now if now is not None else datetime.now(tz=CST).timestamp()

    out, seen = [], set()
    for c in result:
        cid = c.get("id")
        start, end = _ts(c.get("startTime")), _ts(c.get("endTime"))
        if not cid or not start or cid in seen:
            continue
        if end and end.timestamp() < now_ts - 86400:
            continue  # 只保留未开始 / 进行中 / 刚结束的
        seen.add(cid)
        method = _METHOD.get(c.get("method"), "算法竞赛")
        host = ((c.get("host") or {}).get("name") or "洛谷").strip()
        name = (c.get("name") or "").strip() or f"洛谷比赛 {cid}"
        rated = _RATED.get(c.get("rated"), "rated" if c.get("rated") else "")
        tags = ["线上赛", "中文", method]
        if rated:
            tags.insert(0, "计 rating")
        if c.get("squad"):
            tags.append("组队赛")

        desc = (f"洛谷比赛（{method}），{start.strftime('%Y-%m-%d %H:%M')}（北京时间）开始")
        if end:
            desc += f"，{end.strftime('%H:%M')} 结束（共 {int((end - start).total_seconds() // 3600)} 小时）"
        desc += "。"
        if rated:
            desc += "本场计入洛谷比赛 rating。"

        out.append(make_item(
            name if name.endswith("洛谷") else f"洛谷 {name}".strip(),
            f"https://www.luogu.com.cn/contest/{cid}",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d") if end else "",
            start_at=start.strftime("%Y-%m-%d %H:%M"),
            end_at=end.strftime("%Y-%m-%d %H:%M") if end else "",
            organizer=host,
            category="算法竞赛",
            desc=desc,
            tags=tags,
            tier="C" if "LGR" not in name else "B",
            difficulty=3,
            source_id=f"luogu-{cid}",
        ))
        if len(out) >= limit:
            break
    return out
