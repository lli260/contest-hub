# -*- coding: utf-8 -*-
"""各数据源解析器的离线测试（用真实响应片段做 fixture）。"""
import json
from datetime import datetime, timezone

import pytest
from conftest import read_fixture

from contesthub.sources import (atcoder, codechef, codeforces, kaggle, lanqiao,
                                leetcode, luogu, moe, nowcoder, tianchi)
from contesthub.sources.base import (duration_text, money_text,
                                     title_with_brand)

# 2026-10-18 16:00（北京时间），与线上一致的时间基准
NOW = datetime(2026, 10, 18, 8, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- Codeforces
def test_codeforces_keeps_recent_and_hides_old():
    """未开始 + 进行中的比赛都要保留，很久以前结束的不再展示。"""
    data = json.loads(read_fixture("codeforces.json"))
    items = codeforces.parse_contests(data, now=NOW)
    ids = [i["source_id"] for i in items]
    assert "cf-1900" in ids and "cf-1899" in ids
    assert "cf-1898" not in ids          # 很久之前结束的比赛不再展示
    before = [i for i in items if i["source_id"] == "cf-1900"][0]
    assert before["url"] == "https://codeforces.com/contests/1900"
    assert before["start_date"] == "2030-01-01"
    assert before["start_at"] == "2030-01-01 08:00"     # 北京时间


def test_codeforces_dedups_same_id_and_prefers_numbered_title():
    """线上真实 bug：同一 id 同时以 BEFORE / FINISHED 两条出现，后者名字被抹掉编号。"""
    data = json.loads(read_fixture("codeforces_dupack.json"))
    items = codeforces.parse_contests(data, now=NOW)
    ids = [i["source_id"] for i in items]
    assert ids.count("cf-2277") == 1                      # 不再重复入库
    title = [i["name"] for i in items if i["source_id"] == "cf-2277"][0]
    assert "1129" in title                                # 保留带编号的完整名称
    assert items[0]["start_at"]                            # 带精确时间
    # Gym（id >= 100000）不作为公开可报名赛事
    assert all(not i["source_id"].startswith("cf-100001") for i in items)


def test_codeforces_end_date_and_duration():
    data = json.loads(read_fixture("codeforces_dupack.json"))
    items = {i["source_id"]: i for i in codeforces.parse_contests(data, now=NOW)}
    item = items["cf-2261"]
    assert item["end_date"] == "2026-10-18"               # 3 小时赛跨零点的情况由时间体现
    assert "3 小时" in item["desc"]


def test_codeforces_scrape_titles_fills_missing_number():
    """未开始的比赛 API 会抹掉编号，用 /contests 页面补全。"""
    data = json.loads(read_fixture("codeforces_untitled.json"))
    html = """
    <tr data-contestId="2277">
        <td>
    Codeforces Round 1129 (Div. 2)
                    <br/>
                        <a style="font-size: 0.8em;" href="/contest/2277">Enter &raquo;</a>
        </td>
    </tr>
    <tr data-contestId="2278"><td>
    Codeforces Round 1130 (Div. 3)
                    <br/><a href="/contest/2278">Enter &raquo;</a>
        </td></tr>
    """
    titles = codeforces.scrape_contest_titles(html)
    assert titles[2277] == "Codeforces Round 1129 (Div. 2)"
    assert titles[2278] == "Codeforces Round 1130 (Div. 3)"
    items = codeforces.parse_contests(data, now=NOW, titles=titles)
    names = {i["source_id"]: i["name"] for i in items}
    assert "1129" in names["cf-2277"]
    assert "1130" in names["cf-2278"]


# ---------------------------------------------------------------- AtCoder
def test_atcoder_parses_official_table():
    items = atcoder.parse_contests(read_fixture("atcoder_upcoming.html"))
    ids = [i["source_id"] for i in items]
    assert ids == ["atcoder-abc481", "atcoder-arc233", "atcoder-ahc074",
                   "atcoder-agc079"]                     # daily 表格不被混入
    abc = items[0]
    assert abc["start_at"] == "2026-10-24 20:00"          # 21:00 JST -> 20:00 CST
    assert abc["end_at"] == "2026-10-24 21:40"
    assert abc["ratings"] == "~ 1999"
    assert "SMBC" in abc["name"]                          # 真实名称，不是空字符串
    assert not abc["name"].startswith("AtCoder AtCoder")  # 不再重复前缀
    assert items[2]["difficulty"] == 4                    # AHC 难度更高
    assert items[3]["end_date"] == "2026-11-08"


def test_atcoder_archive_titles_take_precedence():
    items = atcoder.parse_contests(
        read_fixture("atcoder_upcoming.html"),
        archive={"abc481": "SMBC Programming Contest #2 (AtCoder Beginner Contest 481)"})
    assert items[0]["name"] == \
        "AtCoder SMBC Programming Contest #2 (AtCoder Beginner Contest 481)"


def test_atcoder_old_broken_fixture_still_works():
    """旧 fixture 的结构（<time> 与 <a> 同表行）也应能被解析，防止回退。"""
    items = atcoder.parse_contests(read_fixture("atcoder.html"))
    assert [i["source_id"] for i in items] == ["atcoder-abc400", "atcoder-arc200",
                                               "atcoder-agc100"]
    assert items[2]["difficulty"] == 4
    assert items[0]["start_date"] == "2030-01-05"


def test_atcoder_empty_page_returns_empty():
    assert atcoder.parse_contests("<html></html>") == []


# ---------------------------------------------------------------- LeetCode
def test_leetcode_parser_filters_past():
    data = json.loads(read_fixture("leetcode.json"))
    assert len(leetcode.parse_contests(data, now=0)) == 2
    items = leetcode.parse_contests(data, now=1_800_000_000)
    assert items and all("第 500 场" in i["name"] for i in items)


def test_leetcode_has_end_time_and_kind_tag():
    data = json.loads(read_fixture("leetcode.json"))
    items = leetcode.parse_contests(data, now=0)
    item = items[0]
    assert item["start_at"] and item["end_at"]
    assert item["end_date"] >= item["start_date"]
    assert any("周赛" in t for t in item["tags"])


# ---------------------------------------------------------------- CodeChef
def test_codechef_parser():
    items = codechef.parse_contests(json.loads(read_fixture("codechef.json")))
    assert len(items) == 1
    assert items[0]["url"] == "https://www.codechef.com/START200"
    assert items[0]["start_date"] == "2030-01-05"


def test_codechef_keeps_exact_time():
    """旧实现只截前 10 位，所有场次都显示成同一天；现在保留到分钟并换算北京时间。"""
    items = {i["source_id"]: i for i in
             codechef.parse_contests(json.loads(read_fixture("codechef_real.json")))}
    assert items["codechef-START261"]["start_at"] == "2026-10-21 22:30"
    assert items["codechef-START261"]["end_at"] == "2026-10-22 00:30"
    assert "rating 赛" in items["codechef-START261"]["tags"]


# ---------------------------------------------------------------- Kaggle
def test_kaggle_parser_filters_and_enriches():
    data = json.loads(read_fixture("kaggle_active.json"))
    items = kaggle.parse_contests(data, now=NOW)
    ids = [i["source_id"] for i in items]
    assert "kaggle-9002" not in ids                       # 已结束的被过滤
    assert ids.count("kaggle-154281") == 1                # 分页重复不会重复入库
    rsna = [i for i in items if i["source_id"] == "kaggle-154281"][0]
    assert rsna["organizer"] == "Radiological Society of North America"
    assert rsna["tier"] == "A"                            # 奖金 >= 5 万美元
    assert "$77,000" in rsna["desc"]
    assert "6,164" in rsna["desc"]                        # 参赛队伍数
    assert "每日最多提交 5 次" in rsna["desc"]             # 提交次数限制
    assert "Image" in rsna["tags"]                        # 数据方向标签
    assert rsna["start_date"] == "2026-08-06"             # UTC -> 北京时间
    assert rsna["end_date"] == "2026-10-23"               # UTC 23:59 截止 -> 北京时间次日
    know = [i for i in items if i["source_id"] == "kaggle-9001"][0]
    assert know["tier"] == "B"


def test_kaggle_urls_are_unique_per_competition():
    """回归：同一批数据里每条竞赛都必须指向自己的 slug。

    曾经写错成在第二个循环里没有重新取 slug，导致所有竞赛都指向
    第一个循环最后一条记录的 URL，进而被去重逻辑合并成一条。
    """
    data = json.loads(read_fixture("kaggle_active.json"))
    items = kaggle.parse_contests(data, now=NOW)
    urls = [i["url"] for i in items]
    assert len(urls) == len(set(urls))
    rsna = [i for i in items if i["source_id"] == "kaggle-154281"][0]
    assert rsna["url"] == "https://www.kaggle.com/competitions/rsna-knee-abnormality-detection"


def test_kaggle_old_fixture_compat():
    items = kaggle.parse_contests(json.loads(read_fixture("kaggle.json")))
    assert [i["source_id"] for i in items] == ["kaggle-1"]
    assert items[0]["end_date"] == "2030-01-01"


# ---------------------------------------------------------------- 洛谷
def test_luogu_parses_embedded_json():
    payload = read_fixture("luogu_context.json")
    html = ('<script id="lentille-context" type="application/json">'
            + json.dumps({"data": {"contests": json.loads(payload)}}, ensure_ascii=False)
            + "</script>")
    items = luogu.parse_contests(html, now=1792750000)
    ids = [i["source_id"] for i in items]
    assert "luogu-364653" in ids
    assert "luogu-300001" not in ids                      # 很久以前的比赛被过滤
    lgr = [i for i in items if i["source_id"] == "luogu-364653"][0]
    assert "计 rating" in lgr["tags"]
    assert lgr["organizer"] == "洛谷官方团队"
    assert lgr["start_at"]
    icpc = [i for i in items if i["source_id"] == "luogu-366008"][0]
    assert "ACM 赛制" in icpc["tags"] and "组队赛" in icpc["tags"]


def test_luogu_without_payload_returns_empty():
    assert luogu.parse_contests("<html>no data</html>") == []


# ---------------------------------------------------------------- 蓝桥云课
def test_lanqiao_parses_official_api():
    data = json.loads(read_fixture("lanqiao_contests.json"))
    ts = datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()
    items = lanqiao.parse_contests(data, now=ts)
    assert [i["source_id"] for i in items] == ["lanqiao-code-2027-dx-1"]
    item = items[0]
    assert item["start_at"] == "2027-04-01 09:00"
    assert item["end_at"] == "2027-04-12 18:00"
    assert item["url"] == "https://www.lanqiao.cn/contests/code-2027-dx-1/challenges/"
    assert "大学组" in item["tags"]
    assert "1,200" in item["desc"]


# ---------------------------------------------------------------- 大学生竞赛白名单
def test_university_whitelist_has_84_unique_entries():
    items = moe.build_items()
    assert len(items) == 84
    assert len({i["name"] for i in items}) == 84
    assert len({i["url"] for i in items}) == 84
    assert len({i["source_id"] for i in items}) == 84
    assert items[0]["name"] == "中国国际大学生创新大赛"
    assert items[0]["url"] == "https://cy.ncss.cn/"
    assert items[-1]["name"] == "码蹄杯全国职业院校程序设计大赛"


def test_university_whitelist_does_not_invent_dates():
    items = moe.build_items()
    assert all(i["start_date"] == "" and i["end_date"] == "" for i in items)
    assert all(i["start_at"] == "" and i["end_at"] == "" for i in items)
    assert all("以主办方官网" in i["desc"] for i in items)


def test_university_whitelist_worldskills_entries_stay_distinct():
    """两条「世界技能大赛」名称互为前缀，不能在建库时被误合并。"""
    names = {i["name"] for i in moe.build_items()}
    assert "世界技能大赛（WorldSkills Competition）" in names
    assert "世界技能大赛中国选拔赛" in names
    from contesthub.rules.dedup import name_tokens
    a, nums_a = name_tokens("世界技能大赛（WorldSkills Competition）")
    b, nums_b = name_tokens("世界技能大赛中国选拔赛")
    assert not (a == b or a.startswith(b) or b.startswith(a))


def test_university_whitelist_uses_existing_categories():
    categories = {i["category"] for i in moe.build_items()}
    assert {"算法竞赛", "数学建模", "网络安全", "创新创业", "学科专业",
            "设计艺术", "嵌入式硬件", "程序设计", "外语人文", "职业技能",
            "综合创新", "数据科学"} <= categories


# ---------------------------------------------------------------- 不可抓取的来源
def test_bot_blocked_sources_declare_unavailable():
    with pytest.raises(nowcoder.SourceUnavailable):
        nowcoder.NowCoderSource().fetch()
    with pytest.raises(tianchi.SourceUnavailable):
        tianchi.TianchiSource().fetch()
    assert nowcoder.NowCoderSource().experimental is True
    assert tianchi.TianchiSource().experimental is True


def test_nowcoder_check_detects_login_shell(fake_transport, monkeypatch):
    routes, FakeResponse = fake_transport
    routes["ac.nowcoder.com"] = FakeResponse(
        "<script>window.isLogin = false;</script>", content_type="text/html")
    info = nowcoder.NowCoderSource().check()
    assert info["ok"] is True and "反爬" in info["detail"]


def test_tianchi_check_reports_entrances(fake_transport):
    routes, FakeResponse = fake_transport
    routes["tianchi.aliyun.com"] = FakeResponse(
        '<a href="https://tianchi.aliyun.com/competition/entrance/532503"><img/></a>')
    info = tianchi.TianchiSource().check()
    assert info["ok"] is True and "1 个赛事入口" in info["detail"]


# ---------------------------------------------------------------- 助手函数
def test_duration_text():
    assert duration_text(7200) == "2 小时"
    assert duration_text(5400) == "1 小时 30 分钟"
    assert duration_text(2700) == "45 分钟"
    assert duration_text(240 * 3600) == "10 天"
    assert duration_text(0) == ""


def test_money_text():
    assert money_text({"id": "USD", "quantity": 1500000}) == "$1,500,000"
    assert money_text({"id": "USD", "quantity": 70000, "clarification": "x"}) == "$70,000"
    assert money_text("Knowledge") == "Knowledge"


def test_title_with_brand_dedupes_prefix():
    assert title_with_brand("Codeforces Round 900", "Codeforces") == "Codeforces Round 900"
    assert title_with_brand("Round 900", "Codeforces") == "Codeforces Round 900"
    assert title_with_brand("AtCoder Beginner Contest 481", "AtCoder") == \
        "AtCoder Beginner Contest 481"
