# -*- coding: utf-8 -*-
"""去重、跨来源归并、字段保护、脏数据拦截。"""
from datetime import date

from contesthub.rules.dedup import (clean_dates, is_reasonable_date, name_tokens,
                              normalize_name, normalize_url, upsert_items,
                              validate_item)
from contesthub.rules.moderation import hidden_reason


class _Stub:
    def __init__(self, key):
        self.key = key


def _make_db():
    import sqlite3
    from contesthub.db import BASE_SCHEMA
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(BASE_SCHEMA)
    # 模拟老库（部分新列可能为空）
    return conn


# ------------------------------------------------------------------ 归一化
def test_normalize_url():
    assert normalize_url("https://Codeforces.com/contests/1234/") == \
        "https://codeforces.com/contests/1234"
    assert normalize_url("https://x.com/a?utm_source=t&id=1#frag") == \
        "https://x.com/a?id=1"
    assert normalize_url("#") == ""
    assert normalize_url("") == ""


def test_normalize_name():
    assert normalize_name("Codeforces Round 900 (Div. 2)") == \
        normalize_name("codeforces  round 900 (div. 2)")
    assert normalize_name("第 12 场双周赛") != normalize_name("第 13 场双周赛")
    # 全角数字也要归一化
    assert normalize_name("第１２场") == normalize_name("第12场")


def test_name_tokens_strip_brand_but_keep_numbers():
    assert name_tokens("Codeforces Round 900") == ("round900", ("900",))
    assert name_tokens("AtCoder Beginner Contest 481")[1] == ("481",)
    # Div. 1 / Div. 2 这类分区号不算场次号
    assert name_tokens("Codeforces Round 900 (Div. 2)")[1] == ("900",)
    # 通用年份不算场次号（Kaggle 竞赛名里几乎都带年份）
    assert name_tokens("Kaggle ARC Prize 2026 - ARC-AGI-3")[1] == ()
    # 有无场次号的两种写法不会被误判为同一场
    assert name_tokens("Codeforces Round (Div. 2)") != \
        name_tokens("Codeforces Round 1129 (Div. 2)")


def test_different_competitions_same_year_are_not_merged():
    """回归：Kaggle 名里普遍带「2026」，不能因此把不同竞赛合并成一条。"""
    db = _make_db()
    names = ["Contradictory, My Dear Watson", "Detecting Solar Flares 2026",
             "Multi-Modal AI 2026", "NeurIPS 2026 Kaggle Competition"]
    for idx, name in enumerate(names):
        upsert_items(db, [{"name": f"Kaggle {name}",
                           "url": f"https://www.kaggle.com/competitions/comp-{idx}",
                           "start_date": "2026-10-14"}], source=_Stub("kaggle"))
    assert db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0] == len(names)


def test_competitions_without_numbers_are_not_merged():
    """回归：两边都没有场次号时，空名称元组相等，不能因此合并不同比赛。"""
    db = _make_db()
    for idx, name in enumerate(["Kaggle Titanic", "Kaggle Spaceship Titanic",
                                "Kaggle Digit Recognizer"]):
        upsert_items(db, [{"name": name,
                           "url": f"https://www.kaggle.com/competitions/c{idx}",
                           "start_date": "2026-10-14"}], source=_Stub("kaggle"))
    assert db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0] == 3


# ------------------------------------------------------------------ 校验
def test_validate_item_rejects_incomplete():
    assert validate_item({"name": "", "url": "https://x.com"}) is None
    assert validate_item({"name": "A", "url": ""}) is None
    item = validate_item({"name": "  A赛  ", "url": "https://x.com/a/",
                          "tags": ["a"], "difficulty": 99, "start_date": "2026/1/2"})
    assert item["name"] == "A赛"
    assert item["url"] == "https://x.com/a"
    assert item["difficulty"] == 5
    assert item["start_date"] == "2026-01-02"


def test_validate_item_rejects_non_contest_pages():
    """题库、课程、题解等不是比赛，旧实现会把它们一并写入。"""
    assert validate_item({"name": "题解：P1001 A+B Problem", "url": "https://x.com/p"}) is None
    assert validate_item({"name": "算法详解课程", "url": "https://x.com/c"}) is None
    assert validate_item({"name": "A+B Problem", "url": "https://www.luogu.com.cn/problem/P1001"}) is None
    assert hidden_reason("比赛题解合集", "https://x.com/a") is not None
    assert hidden_reason("Codeforces Round 900", "https://codeforces.com/contest/900") is None
    # 带「比赛」字样的标题不会被误杀
    assert hidden_reason("第 525 场周赛（题解已发布）", "https://x.com/contest/1") is None


def test_validate_item_rejects_bogus_dates():
    """旧数据出现过年份明显错误的开赛日，这里必须拦下。"""
    item = validate_item({"name": "X 赛", "url": "https://x.com/1",
                          "start_date": "2015-03-01", "end_date": "2035-01-01"})
    assert item["start_date"] == ""        # 太早
    assert item["end_date"] == ""          # 太晚
    bad = validate_item({"name": "Y 赛", "url": "https://x.com/2",
                         "start_date": "2026-12-01", "end_date": "2026-11-01"})
    assert bad["start_date"] == "2026-12-01" and bad["end_date"] == ""


def test_is_reasonable_date():
    today = date(2026, 10, 18)
    assert is_reasonable_date("2026-12-01", kind="start", today=today)
    assert not is_reasonable_date("2020-01-01", kind="start", today=today)
    assert not is_reasonable_date("2040-01-01", kind="start", today=today)


def test_clean_dates_reports_warnings():
    start, end, dl, warn = clean_dates({"start_date": "2038-01-01",
                                        "end_date": "2038-01-02",
                                        "reg_deadline": "2038-01-01"})
    assert (start, end, dl) == ("", "", "")
    assert len(warn) == 3


def test_validate_item_keeps_precise_time():
    item = validate_item({"name": "X 赛", "url": "https://x.com/1",
                          "start_date": "2026-10-24", "start_at": "2026-10-24 20:00",
                          "end_at": "2026-10-24 21:40", "ratings": "~ 1999"})
    assert item["start_at"] == "2026-10-24 20:00"
    assert item["end_at"] == "2026-10-24 21:40"
    assert item["ratings"] == "~ 1999"
    # 时间与日期不一致时丢弃时间，避免用户看到错误的时刻
    mismatch = validate_item({"name": "Y 赛", "url": "https://x.com/2",
                              "start_date": "2026-10-25", "start_at": "2026-10-24 20:00"})
    assert mismatch["start_at"] == ""


# ------------------------------------------------------------------ upsert
def test_upsert_dedups_by_url_and_source_id():
    db = _make_db()
    item = {"name": "CF Round 1", "url": "https://codeforces.com/contests/1",
            "organizer": "Codeforces"}
    assert upsert_items(db, [item], source=_Stub("codeforces"))[:2] == (1, 0)
    assert upsert_items(db, [item], source=_Stub("codeforces"))[:2] == (0, 1)
    assert db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0] == 1
    item2 = dict(item, url="https://codeforces.com/contests/1?utm_source=x")
    assert upsert_items(db, [item2], source=_Stub("codeforces"))[0] == 0


def test_upsert_preserves_manual_scores():
    db = _make_db()
    db.execute("INSERT INTO competitions(name,category,url,source,tier,s_difficulty,"
               "s_history,s_policy,s_industry) VALUES('人工赛','其他','https://a.com/x',"
               "'manual','S',5,5,5,5)")
    upsert_items(db, [{"name": "人工赛", "url": "https://a.com/x", "tier": "C",
                       "difficulty": 1}], source=_Stub("kaggle"))
    row = db.execute("SELECT * FROM competitions").fetchone()
    assert row["tier"] == "S"
    assert row["s_difficulty"] == 5
    assert row["source"] == "manual"


def test_upsert_skips_invalid():
    db = _make_db()
    assert upsert_items(db, [{"name": "", "url": "x"}], source=_Stub("kaggle")) == (0, 0, 1)


def test_source_id_match_is_scoped_to_its_own_source():
    """不同来源的 ID 空间互相独立，source_id 不能跨来源命中别人的记录。"""
    db = _make_db()
    upsert_items(db, [{"name": "某站比赛", "source_id": "900",
                       "url": "https://other.example.com/900",
                       "start_date": "2026-11-20"}], source=_Stub("luogu"))
    # 同一 source_id 但属于 Codeforces，URL 与名称也不同 → 必须是新记录
    added, updated, _ = upsert_items(db, [{"name": "Codeforces Round 900",
                                           "source_id": "900",
                                           "url": "https://codeforces.com/contests/900",
                                           "start_date": "2026-11-21"}],
                                     source=_Stub("codeforces"))
    assert (added, updated) == (1, 0)
    assert db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0] == 2


def test_legacy_crawl_rows_can_be_claimed_by_their_source():
    """老库里 source='crawl' 的行，来源补齐 source_id 后应能认领而不是新建。"""
    db = _make_db()
    db.execute("INSERT INTO competitions(name,category,url,source,source_id,start_date) "
               "VALUES('Codeforces Round 1124','算法竞赛',"
               "'https://codeforces.com/contests/2268','crawl','cf-2268','2026-09-26')")
    added, updated, _ = upsert_items(db, [{"name": "Codeforces Round 1124 (Div. 1)",
                                           "source_id": "cf-2268",
                                           "url": "https://codeforces.com/contests/2268",
                                           "start_date": "2026-09-26"}],
                                     source=_Stub("codeforces"))
    assert (added, updated) == (0, 1)
    row = db.execute("SELECT * FROM competitions").fetchone()
    assert row["source"] == "codeforces"


def test_upsert_merges_same_event_across_sources():
    """同一场比赛被两个来源各抓一次时，应归并成一条（旧实现会存两条）。"""
    db = _make_db()
    upsert_items(db, [{"name": "Codeforces Round 900 (Div. 2)",
                       "url": "https://codeforces.com/contests/900",
                       "start_date": "2026-11-20", "desc": "来自 CF"}],
                 source=_Stub("codeforces"))
    added, updated, _ = upsert_items(db, [{"name": "Codeforces Round 900",
                                           "url": "https://mirror.example.com/cf900",
                                           "start_date": "2026-11-21"}],
                                     source=_Stub("luogu"))
    assert (added, updated) == (0, 1)
    assert db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0] == 1
    row = db.execute("SELECT * FROM competitions").fetchone()
    # 描述保留原来源的，来源归属不被抢走
    assert row["desc"] == "来自 CF"
    assert row["source"] == "codeforces"


def test_upsert_merges_same_name_even_without_numbers():
    """名称完全相同、日期相差 1 天以内 → 视为同一场。"""
    db = _make_db()
    upsert_items(db, [{"name": "Kaggle RSNA Knee Abnormality Detection",
                       "url": "https://kaggle.com/competitions/a",
                       "start_date": "2026-11-01"}], source=_Stub("kaggle"))
    upsert_items(db, [{"name": "Kaggle RSNA Knee Abnormality Detection",
                       "url": "https://mirror.example.com/rsna",
                       "start_date": "2026-11-01"}], source=_Stub("luogu"))
    assert db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0] == 1


def test_upsert_does_not_merge_different_rounds():
    db = _make_db()
    upsert_items(db, [{"name": "Codeforces Round (Div. 2)",
                       "url": "https://codeforces.com/contests/2277",
                       "start_date": "2026-10-24"}], source=_Stub("codeforces"))
    upsert_items(db, [{"name": "Codeforces Round (Div. 2)",
                       "url": "https://codeforces.com/contests/2278",
                       "start_date": "2026-10-29"}], source=_Stub("codeforces"))
    assert db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0] == 2


def test_sync_never_steals_other_sources_source_id():
    """旧实现会给别的来源的记录打上自己的 source_id，导致来源归属错乱。"""
    db = _make_db()
    upsert_items(db, [{"name": "Codeforces Round 900", "source_id": "cf-900",
                       "url": "https://codeforces.com/contests/900",
                       "start_date": "2026-11-20"}], source=_Stub("codeforces"))
    upsert_items(db, [{"name": "Codeforces Round 900 (Div. 2)", "source_id": "lg-900",
                       "url": "https://codeforces.com/contests/900",
                       "start_date": "2026-11-20"}], source=_Stub("luogu"))
    row = db.execute("SELECT * FROM competitions").fetchone()
    assert row["source"] == "codeforces"
    assert row["source_id"] == "cf-900"


def test_sync_does_not_overwrite_builtin_description():
    """内置/人工写的描述不能被机器抓取覆盖（旧实现会覆盖）。"""
    db = _make_db()
    db.execute("INSERT INTO competitions(name,category,url,source,desc,verify_status,"
               "start_date) VALUES('全国大学生数学建模竞赛','数学建模',"
               "'https://www.mcm.edu.cn/','builtin','高教社杯，72 小时建模…','manual',"
               "'2026-09-10')")
    upsert_items(db, [{"name": "全国大学生数学建模竞赛", "url": "https://www.mcm.edu.cn/",
                       "desc": "scraped junk", "start_date": "2026-09-10"}],
                 source=_Stub("luogu"))
    row = db.execute("SELECT * FROM competitions").fetchone()
    assert row["desc"] == "高教社杯，72 小时建模…"
    assert row["source"] == "builtin"


def test_sync_upgrades_same_source_description_and_dates():
    db = _make_db()
    upsert_items(db, [{"name": "CF Round (Div. 2)", "url": "https://codeforces.com/contests/1",
                       "start_date": "2026-10-24", "desc": "first"}],
                 source=_Stub("codeforces"))
    upsert_items(db, [{"name": "CF Round (Div. 2)", "url": "https://codeforces.com/contests/1",
                       "start_date": "2026-10-25", "desc": "second"}],
                 source=_Stub("codeforces"))
    row = db.execute("SELECT * FROM competitions").fetchone()
    assert row["desc"] == "second"          # 同一来源可以刷新
    assert row["start_date"] == "2026-10-25"  # 赛程变更要跟上


def test_sync_records_last_seen_and_clears_missing():
    db = _make_db()
    upsert_items(db, [{"name": "赛 A", "url": "https://a.com/1"}], source=_Stub("codeforces"))
    db.execute("UPDATE competitions SET missing_since='2026-01-01'")
    upsert_items(db, [{"name": "赛 A", "url": "https://a.com/1"}], source=_Stub("codeforces"))
    row = db.execute("SELECT * FROM competitions").fetchone()
    assert row["last_seen"]
    assert not row["missing_since"]        # 重新出现时解除隐藏


def test_upsert_merges_tags():
    db = _make_db()
    upsert_items(db, [{"name": "赛 A", "url": "https://a.com/1", "tags": ["人工标签"]}],
                 source=_Stub("codeforces"))
    upsert_items(db, [{"name": "赛 A", "url": "https://a.com/1", "tags": ["rating 赛"]}],
                 source=_Stub("codeforces"))
    row = db.execute("SELECT tags FROM competitions").fetchone()
    assert "人工标签" in row["tags"] and "rating 赛" in row["tags"]
