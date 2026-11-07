# -*- coding: utf-8 -*-
"""蓝桥杯 / 蓝桥云课比赛（官方公开 REST 接口）。

蓝桥杯（工业和信息化部人才交流中心主办）是国内参与人数最多的大学生 IT
赛事之一，但旧版本只在「预置数据」里有一行笼统的描述，没有任何真实赛程。
这里调用蓝桥云课官网前端的公开接口：

    https://www.lanqiao.cn/api/v2/contests/?page=N

字段：``name / subject / open_at / end_at / html_url / slug / status /
users_count``，全部带 +08:00 时区。接口默认按开始时间倒序，取最近两页
即可覆盖「进行中 / 即将开始 / 刚结束」的场次。
"""
import time

from .base import (CST, Source, http_json, make_item, md_date, md_datetime,
                   parse_iso_datetime)

API = "https://www.lanqiao.cn/api/v2/contests/"
HOME_URL = "https://www.lanqiao.cn/contests/"
MAX_PAGES = 2

# 赛事科目 -> 类别，便于平台按类别筛选
_SUBJECT_CATEGORY = {
    "人工智能": "程序设计", "Web 应用开发": "程序设计", "软件测试": "程序设计",
    "网络安全": "网络安全", "电子信息": "嵌入式硬件", "单片机": "嵌入式硬件",
    "视觉艺术设计": "综合创新", "程序设计": "程序设计",
}


class LanqiaoSource(Source):
    key = "lanqiao"
    label = "蓝桥云课 / 蓝桥杯"
    group = "蓝桥杯 & 校赛平台"
    homepage = "https://www.lanqiao.cn/contests/"
    nature = "online"

    def fetch(self):
        results = []
        for page in range(1, MAX_PAGES + 1):
            data = http_json(f"{API}?page={page}", timeout=25,
                            headers={"Referer": HOME_URL, "Accept": "application/json"})
            chunk = (data or {}).get("results") or []
            results.extend(chunk)
            if len(chunk) < ((data or {}).get("page_size") or 16):
                break
        return parse_contests({"results": results})


def parse_contests(data, limit=20, now=None):
    """只保留未结束的比赛（含刚结束 1 天内的，避免状态跳变）。"""
    results = (data or {}).get("results") or []
    if now is not None and hasattr(now, "timestamp"):
        now_ts = now.timestamp()
    elif now is not None:
        now_ts = float(now)
    else:
        now_ts = time.time()
    out, seen = [], set()
    for c in results:
        slug = c.get("slug") or c.get("id")
        name = (c.get("name") or "").strip()
        if not slug or not name or slug in seen:
            continue
        end = parse_iso_datetime(c.get("end_at"), default_tz=CST)
        start = parse_iso_datetime(c.get("open_at"), default_tz=CST)
        if end and end.timestamp() < now_ts - 86400:
            continue
        seen.add(slug)
        subject = (c.get("subject") or "").strip()
        category = _SUBJECT_CATEGORY.get(subject, "程序设计")
        url = c.get("html_url") or f"/contests/{slug}/"
        if url.startswith("/"):
            url = "https://www.lanqiao.cn" + url
        tags = ["蓝桥杯", "模拟赛" if "模拟" in name else "正式赛"]
        if subject:
            tags.append(subject)
        if "大学组" in name:
            tags.append("大学组")
        elif "职业组" in name or "职业院校组" in name:
            tags.append("职业组")
        desc = f"蓝桥杯 / 蓝桥云课 {subject or '比赛'}，"
        if start:
            desc += f"{md_datetime(c.get('open_at'))}（北京时间）开始"
        if end:
            desc += f"，{md_datetime(c.get('end_at'))} 结束"
        desc += "。"
        if c.get("users_count"):
            desc += f"已有 {int(c['users_count']):,} 人参赛。"
        desc += "蓝桥杯为「校赛-省赛-国赛」三级选拔，历年真题可在蓝桥云课刷题。"
        out.append(make_item(
            f"蓝桥杯 {name}" if not name.startswith("蓝桥") else name,
            url,
            start_date=md_date(c.get("open_at")),
            end_date=md_date(c.get("end_at")),
            start_at=md_datetime(c.get("open_at")),
            end_at=md_datetime(c.get("end_at")),
            organizer="工业和信息化部人才交流中心 / 蓝桥云课",
            category=category,
            desc=desc,
            tags=tags,
            tier="B" if "模拟" in name else "A",
            difficulty=3,
            source_id=f"lanqiao-{slug}",
            status=c.get("status") or "",
        ))
        if len(out) >= limit:
            break
    return out
