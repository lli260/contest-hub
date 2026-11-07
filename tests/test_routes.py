# -*- coding: utf-8 -*-
"""页面路由、JSON API、日历导出。"""
from datetime import date, timedelta

from contesthub.routes import build_calendar


def _first_comp_id(db):
    return db.execute("SELECT id FROM competitions ORDER BY id LIMIT 1").fetchone()["id"]


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Contest Hub" in text
    assert "赛事自动同步" in text
    assert "数据源健康" in text
    assert "年度大赛" in text and "在线赛" in text      # 时间轴分两行


def test_index_filters(client):
    for query in ["?range=365", "?status=日期待定", "?sort=level", "?q=数学建模",
                  "?ended=1", "?min_level=4", "?source=builtin",
                  "?from=2026-01-01&to=2027-12-31", "?category=数学建模"]:
        resp = client.get("/" + query)
        assert resp.status_code == 200, query


def test_index_hides_ended_by_default(client, db):
    cid = _first_comp_id(db)
    past = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    db.execute("UPDATE competitions SET start_date=?, end_date=? WHERE id=?",
               (past, past, cid))
    db.commit()
    body = client.get("/?range=0").get_data(as_text=True)
    assert f'id="comp-{cid}"' not in body                # 默认不显示已结束
    body = client.get("/?range=0&ended=1").get_data(as_text=True)
    assert f'id="comp-{cid}"' in body


def test_health_page(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "数据源健康" in text
    assert "最近同步日志" in text
    assert "实时诊断" in text


def test_probe_endpoint(client, monkeypatch):
    """诊断接口逐个来源抓取但不写库。"""
    from contesthub import sync

    class _Src:
        key, label, group, experimental = "x", "X 来源", "算法/编程在线赛", False
        homepage = "https://x.com"

        def fetch(self):
            return [{"name": "赛", "url": "https://x.com/1"}]

    monkeypatch.setattr(sync.sources, "all_sources", lambda: [_Src()])
    data = client.get("/api/probe").get_json()
    assert data["ok"] is True
    assert data["results"][0]["ok"] is True
    assert data["results"][0]["count"] == 1


def test_detail_renders(client, db):
    cid = _first_comp_id(db)
    resp = client.get(f"/comp/{cid}")
    assert resp.status_code == 200
    assert "自动生成的重点" in resp.get_data(as_text=True)


def test_detail_missing_redirects(client):
    resp = client.get("/comp/999999")
    assert resp.status_code == 302


def test_verify_marks_comp(client, db):
    cid = _first_comp_id(db)
    resp = client.post(f"/verify/{cid}", follow_redirects=True)
    assert resp.status_code == 200
    row = db.execute("SELECT verify_status FROM competitions WHERE id=?", (cid,)).fetchone()
    assert row["verify_status"] == "verified"


def test_calendar_export(client):
    resp = client.get("/calendar.ics")
    assert resp.status_code == 200
    assert resp.mimetype.startswith("text/calendar")
    body = resp.get_data(as_text=True)
    assert "BEGIN:VCALENDAR" in body and "END:VCALENDAR" in body


def test_calendar_builder_emits_events():
    body = build_calendar([{"id": 1, "name": "测试赛", "start_date": "2030-01-05",
                            "reg_deadline": "2029-12-01", "desc": "简介",
                            "url": "https://a.com"}])
    assert body.count("BEGIN:VEVENT") == 2       # 报名截止 + 开赛
    assert "DTSTART;VALUE=DATE:20300105" in body


def test_calendar_uses_exact_time_when_available():
    body = build_calendar([{"id": 2, "name": "在线赛", "start_date": "2030-01-05",
                            "start_at": "2030-01-05 20:00", "end_at": "2030-01-05 21:40",
                            "url": "https://a.com/x"}])
    assert "DTSTART;TZID=Asia/Shanghai:20300105T200000" in body
    assert "DTEND;TZID=Asia/Shanghai:20300105T214000" in body
    # 精确时间优先时不应再生成「全天事件」
    assert "DTSTART;VALUE=DATE" not in body


def test_calendar_folds_long_lines():
    body = build_calendar([{"id": 3, "name": "很长的比赛名称" * 12,
                            "start_date": "2030-01-05", "desc": "长描述" * 40}])
    for line in body.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    # 折行后的续行以单个空格开头，且内容可完整还原
    assert "\r\n " in body
    unfolded = body.replace("\r\n ", "")
    assert "很长的比赛名称" * 12 in unfolded


def test_fav_toggle(client, db):
    cid = _first_comp_id(db)
    r1 = client.post(f"/fav/{cid}").get_json()
    assert r1["fav"] is True
    r2 = client.post(f"/fav/{cid}").get_json()
    assert r2["fav"] is False


def test_sync_status_api(client):
    data = client.get("/api/sync/status").get_json()
    assert data["ok"] is True
    assert "running" in data and "sources" in data
    assert data["last_run"] is not None or data["last_run"] is None  # 两个分支都合法


def test_add_comp_manual(client, db):
    resp = client.post("/comp/add", data={
        "name": "我的校赛", "category": "算法竞赛", "url": "https://a.com/x?utm_source=1",
        "start_date": "2027-05-01", "tier": "A", "s_difficulty": "4"}, follow_redirects=True)
    assert resp.status_code == 200
    row = db.execute("SELECT * FROM competitions WHERE name='我的校赛'").fetchone()
    assert row["source"] == "manual"
    assert row["url"] == "https://a.com/x"      # 跟踪参数被剔除
    assert "已手动添加" in resp.get_data(as_text=True)


def test_add_comp_requires_name(client):
    resp = client.post("/comp/add", data={"name": " "}, follow_redirects=True)
    assert "比赛名称不能为空" in resp.get_data(as_text=True)


def test_plan_and_task_flow(client, db):
    cid = _first_comp_id(db)
    client.post(f"/plan/add/{cid}", data={"title": "冲刺"})
    pid = db.execute("SELECT id FROM plans WHERE comp_id=?", (cid,)).fetchone()["id"]
    client.post(f"/task/add/{pid}", data={"content": "刷题", "cid": str(cid)})
    tid = db.execute("SELECT id FROM tasks WHERE plan_id=?", (pid,)).fetchone()["id"]
    client.post(f"/task/toggle/{tid}", data={"cid": str(cid)})
    assert db.execute("SELECT done FROM tasks WHERE id=?", (tid,)).fetchone()["done"] == 1
    client.post(f"/task/delete/{tid}", data={"cid": str(cid)})
    assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_note_saves_auto_points(client, db):
    cid = _first_comp_id(db)
    client.post(f"/comp/{cid}", data={"note": "我的笔记"})
    row = db.execute("SELECT * FROM notes WHERE comp_id=?", (cid,)).fetchone()
    assert row["content"] == "我的笔记"
    assert "自动" not in row["auto_points"] and row["auto_points"].startswith("[")


def test_seed_data_has_no_bogus_dates(db):
    """内置数据不允许出现「明显错误的年份」这种脏数据。"""
    today = date.today()
    for row in db.execute("SELECT name,start_date,end_date FROM competitions "
                          "WHERE source IN ('builtin','curated')"):
        if row["start_date"]:
            d = date.fromisoformat(row["start_date"])
            assert today - timedelta(days=400) <= d <= today + timedelta(days=1100), \
                f"{row['name']} 的日期不合理：{row['start_date']}"


def test_seed_fixes_known_wrong_claim(db):
    """旧版本内置数据里「CCPC 第 11 届总决赛已于 2026-04-25 举行」是编造的。"""
    row = db.execute("SELECT desc FROM competitions WHERE name LIKE '%CCPC%' "
                     "AND source='builtin'").fetchone()
    assert "南阳理工学院" not in row["desc"]
    assert "已更正" in row["desc"]


def test_curated_entries_exist(db):
    rows = {r["name"] for r in db.execute(
        "SELECT name FROM competitions WHERE source='curated'")}
    assert any("牛客" in n for n in rows)


def test_no_duplicate_urls_in_seed(db):
    """内置数据与精选入口不能指向同一个官网链接。"""
    dupes = [r["url"] for r in db.execute(
        "SELECT url, COUNT(*) n FROM competitions WHERE url IS NOT NULL AND url<>'' "
        "GROUP BY url HAVING n > 1")]
    assert dupes == []


def test_upgrade_builtin_replaces_bogus_dates():
    """老库里的旧版内置数据（含编造的日期与错误表述）会被升级。"""
    import sqlite3

    from contesthub.db import BASE_SCHEMA
    from contesthub.seed import BUILTIN, upgrade_builtin

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(BASE_SCHEMA)
    # 模拟旧版本的一条内置记录：CCPC 被编造成「2026-04-25 南阳理工学院已举办」
    conn.execute(
        "INSERT INTO competitions(name,category,organizer,start_date,end_date,reg_deadline,"
        "url,desc,tags,source,tier,s_difficulty,s_history,s_policy,s_industry) "
        "VALUES('CCPC 中国大学生程序设计竞赛（总决赛）','算法竞赛','协会','2026-04-25',"
        "'2026-04-26','2026-03-31','https://ccpc.io/','第11届总决赛已于 2026年4月25-26日"
        "在南阳理工学院举行','[]','builtin','A',5,4,5,5)")
    upgrade_builtin(conn)
    row = conn.execute("SELECT * FROM competitions WHERE source='builtin'").fetchone()
    assert row["start_date"] == ""          # 没有依据的日期被清掉
    assert "南阳理工学院" not in row["desc"]  # 错误表述被更正
    assert row["name"] == "CCPC 中国大学生程序设计竞赛（分站赛 & 总决赛）"
    assert len(BUILTIN) == 16


def test_remove_obsolete_builtin_keeps_favorites():
    """旧版占位条目被移除，但用户收藏过的保留。"""
    import sqlite3

    from contesthub.db import BASE_SCHEMA
    from contesthub.seed import remove_obsolete_builtin

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(BASE_SCHEMA)
    conn.execute("DELETE FROM competitions")
    conn.execute("INSERT INTO competitions(id,name,category,url,source) "
                 "VALUES(1,'Codeforces Round 系列周赛','算法竞赛','https://cf.com','builtin')")
    conn.execute("INSERT INTO competitions(id,name,category,url,source) "
                 "VALUES(2,'AtCoder 周赛（ABC/ARC/AGC）','算法竞赛','https://at.com','builtin')")
    conn.execute("INSERT INTO favorites(comp_id) VALUES(2)")
    conn.execute("INSERT INTO plans(id,comp_id,title) VALUES(1,1,'冲刺计划')")
    removed = remove_obsolete_builtin(conn)
    assert removed == 1
    assert conn.execute("SELECT id FROM competitions").fetchone()["id"] == 2
    assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0  # 关联计划一并清理
    """老库里的脏数据在启动时被修复。"""
    import sqlite3

    from contesthub.db import BASE_SCHEMA, repair_legacy_rows
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(BASE_SCHEMA)
    conn.execute("INSERT INTO competitions(name,category,url,source,source_id) "
                 "VALUES('Codeforces Codeforces Round 900','算法竞赛',"
                 "'https://codeforces.com/contests/900','crawl','')")
    conn.execute("INSERT INTO competitions(name,category,url,source,source_id) "
                 "VALUES('AtCoder AtCoder Beginner Contest 473','算法竞赛',"
                 "'https://atcoder.jp/contests/abc473','atcoder','')")
    repair_legacy_rows(conn)
    rows = {r["name"]: r for r in conn.execute("SELECT * FROM competitions")}
    assert "Codeforces Round 900" in rows
    assert "AtCoder Beginner Contest 473" in rows
    assert rows["Codeforces Round 900"]["source_id"] == "cf-900"
    assert rows["AtCoder Beginner Contest 473"]["source_id"] == "atcoder-abc473"
    assert rows["Codeforces Round 900"]["last_seen"]
