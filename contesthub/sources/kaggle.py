# -*- coding: utf-8 -*-
"""Kaggle 竞赛列表（站点内部公开 JSON 接口，POST 分页）。

旧实现只用竞赛标题拼出「Kaggle xxx」，把关键信息全丢了：主办方、奖金、
参赛队伍数、数据方向、评审指标。现在把这些都解析出来，写进主办方/简介/标签，
并在卡片上给出「数据科学 · 机器学习」等分类与奖金，信息量大幅提升。
"""
from datetime import datetime, timedelta, timezone

from .base import (Source, http_post_json, make_item, md_date, money_text,
                   title_with_brand)

API = "https://www.kaggle.com/api/i/competitions.CompetitionService/ListCompetitions"
#: 实测该接口忽略 page 参数（每页都从第 1 条开始），一次请求 pageSize=500 即可
#: 覆盖全部竞赛（当前总数约 758，其中仍在进行的只有几十个），不额外分页。
PAGE_SIZE = 500
MIN_REWARD_FOR_A = 50000  # 奖金 >= 5 万美元的竞赛视为高奖金

# Kaggle 的 categories 是扁平的标签列表，这里挑出数据方向相关的标签
_CATEGORY_HINTS = ("data type", "technique", "subject", "analysis", "competition type")


def _host_name(c):
    """主办方：优先 hostName，其次 organization 名称。"""
    host = c.get("hostName")
    if host:
        return str(host).strip()
    org = c.get("organization")
    if isinstance(org, dict):
        return (org.get("name") or "").strip()
    return ""


class KaggleSource(Source):
    key = "kaggle"
    label = "Kaggle"
    group = "数据科学平台"
    homepage = "https://www.kaggle.com/competitions"
    nature = "long"
    timeout = 60

    def fetch(self):
        # Kaggle 对完整浏览器 UA 会返回前端页面，这里用最简 UA 才拿到 JSON
        data = http_post_json(API, {"pageSize": PAGE_SIZE},
                              timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        chunk = (data or {}).get("competitions")
        if chunk is None:
            raise ValueError("Kaggle 返回结构异常")
        return parse_contests({"competitions": chunk})


def _data_tags(c):
    tags = []
    for cat in c.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        full = (cat.get("fullPath") or "").lower()
        if full.startswith("data type") or full.startswith("technique"):
            name = (cat.get("displayName") or cat.get("name") or "").strip()
            if name and name not in tags:
                tags.append(name)
    return tags[:4]


def _reward_amount(c):
    """返回奖金金额（数值）与展示文案。"""
    reward = c.get("reward")
    text = money_text(reward)
    amount = 0
    if isinstance(reward, dict):
        try:
            amount = int(reward.get("quantity") or 0)
        except (TypeError, ValueError):
            amount = 0
    return amount, text


def parse_contests(data, limit=40, now=None):
    """只保留仍在进行 / 即将截止的竞赛，按截止时间排序。

    截止时间按 UTC 解析；判断「是否已结束」时给 1 天宽限，避免因时区
    把当天 UTC 深夜截止的竞赛提前过滤掉。
    """
    now = now or datetime.now(timezone.utc)
    if isinstance(now, datetime) and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    comps = (data or {}).get("competitions")
    if comps is None:
        raise ValueError("Kaggle 返回结构异常")
    active, seen = [], set()
    for c in comps:
        slug = c.get("competitionName")
        if not slug:
            continue
        key = c.get("id") or slug
        if key in seen:  # 分页可能重复返回同一竞赛
            continue
        seen.add(key)
        deadline = md_date(c.get("deadline"), default_tz=timezone.utc)
        if deadline and deadline < today:
            continue  # 只保留仍在进行 / 即将截止的
        active.append((deadline or "9999-99-99", c))
    active.sort(key=lambda x: x[0])

    out = []
    for deadline, c in active[:limit]:
        # 注意：slug 必须在第二个循环里重新取，
        # 否则会一直沿用第一个循环里最后一条记录的 slug（所有竞赛指向同一个 URL）
        slug = c.get("competitionName") or str(c.get("id") or "")
        brief = str(c.get("briefDescription") or "").strip()
        host = _host_name(c)
        amount, reward_text = _reward_amount(c)
        teams = c.get("totalTeams") or c.get("totalJoinedUsers") or 0
        tags = ["机器学习", "数据科学"] + _data_tags(c)
        if amount >= MIN_REWARD_FOR_A:
            tags.insert(0, "高奖金")
        elif amount:
            tags.insert(0, "有奖金")
        if c.get("hasLeaderboard"):
            tags.append("排行榜")

        parts = []
        if brief:
            parts.append(brief.rstrip(".") + "。")
        if host:
            parts.append(f"主办方：{host}。")
        if reward_text:
            parts.append(f"奖金池：{reward_text}。")
        if teams:
            parts.append(f"当前参赛队伍：{int(teams):,} 支。")
        if deadline:
            parts.append(f"截止：{deadline}（UTC 日期，以官网倒计时为准）。")
        if c.get("maxTeamSize") and int(c["maxTeamSize"]) > 1:
            parts.append(f"每队最多 {int(c['maxTeamSize'])} 人。")
        # 每日提交次数上限是很实际的参赛约束，选手据此安排调参节奏
        daily = c.get("maxDailySubmissions")
        if daily:
            parts.append(f"每日最多提交 {int(daily)} 次。")
        final_subs = c.get("numScoredSubmissions")
        if final_subs:
            parts.append(f"最终计分提交 {int(final_subs)} 次。")
        if c.get("totalSubmissions"):
            parts.append(f"累计提交 {int(c['totalSubmissions']):,} 次。")
        algo = c.get("evaluationAlgorithm")
        if isinstance(algo, dict) and algo.get("name"):
            parts.append(f"评测指标：{algo['name']}。")

        if daily:
            tags.append(f"每日 {int(daily)} 次提交")
        ratings = f"{int(teams):,} 支队伍" if teams else ""

        out.append(make_item(
            title_with_brand((c.get("title") or slug).strip(), "Kaggle"),
            f"https://www.kaggle.com/competitions/{slug}",
            start_date=md_date(c.get("dateEnabled"), default_tz=timezone.utc),
            end_date=deadline if deadline != "9999-99-99" else "",
            organizer=host or "Kaggle",
            category="数据科学",
            desc="".join(parts)[:600],
            tags=tags[:6],
            tier="A" if amount >= MIN_REWARD_FOR_A else "B",
            difficulty=4,
            source_id=f"kaggle-{c.get('id') or slug}",
            ratings=ratings,
        ))
    return out
