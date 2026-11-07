# -*- coding: utf-8 -*-
"""同步编排：隔离失败、并行、缓存、反爬来源不假装成功、过期隐藏。"""
import time
from datetime import datetime, timedelta

from contesthub import sync


class _FakeSource:
    key = "fake"
    label = "Fake"
    group = "算法/编程在线赛"
    homepage = ""
    experimental = False
    nature = "online"
    timeout = 5

    def __init__(self, items):
        self.items = items
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return list(self.items)

    def describe(self):
        return {"key": self.key, "label": self.label, "group": self.group,
                "homepage": self.homepage, "experimental": self.experimental,
                "nature": self.nature}


class _BrokenSource(_FakeSource):
    def __init__(self):
        super().__init__([])
        self.key = "broken"
        self.label = "Broken"

    def fetch(self):
        raise RuntimeError("网络挂了")


class _SlowSource(_FakeSource):
    def __init__(self):
        super().__init__([])
        self.key = "slow"
        self.label = "Slow"

    def fetch(self):
        time.sleep(5)
        return []


class _BotBlockedSource(_FakeSource):
    """模拟牛客/天池：明确声明不可抓取。"""

    key = "blocked"
    label = "反爬站点"

    def __init__(self):
        super().__init__([])

    def fetch(self):
        raise RuntimeError("该站反爬，无法自动抓取")


def _patch(monkeypatch, sources):
    monkeypatch.setattr(sync.sources, "all_sources", lambda: list(sources))


def test_run_sync_inserts_and_logs(db, monkeypatch):
    fake = _FakeSource([{"name": "赛 A", "url": "https://a.com/1",
                         "start_date": "2026-12-01"}])
    _patch(monkeypatch, [fake])
    results = sync.run_sync(db, None, use_cache=False)
    assert results[0]["ok"] and results[0]["added"] == 1
    assert db.execute("SELECT COUNT(*) FROM competitions WHERE source='fake'") \
        .fetchone()[0] == 1
    status = sync.sync_status(db)
    assert status["last_run"]
    assert status["sources"][0]["source"] == "fake"
    assert status["live"] == 1


def test_run_sync_isolates_failures(db, monkeypatch):
    good = _FakeSource([{"name": "赛 B", "url": "https://b.com/2"}])
    bad = _BrokenSource()
    _patch(monkeypatch, [bad, good])
    results = {r["key"]: r for r in sync.run_sync(db, None, use_cache=False)}
    assert results["broken"]["ok"] is False
    assert "网络挂了" in results["broken"]["error"]
    assert results["fake"]["ok"] is True


def test_failed_source_keeps_existing_data(db, monkeypatch):
    """抓取失败不能把该来源已有的赛程清空。"""
    good = _FakeSource([{"name": "赛 C", "url": "https://c.com/3"}])
    _patch(monkeypatch, [good])
    sync.run_sync(db, None, use_cache=False)
    _patch(monkeypatch, [_BrokenSource()])
    sync.run_sync(db, None, use_cache=False)
    assert db.execute("SELECT COUNT(*) FROM competitions WHERE source='fake'") \
        .fetchone()[0] == 1


def test_cache_avoids_refetch(db, monkeypatch):
    fake = _FakeSource([{"name": "赛 D", "url": "https://d.com/4"}])
    _patch(monkeypatch, [fake])
    sync.clear_cache()
    sync.run_sync(db, None, use_cache=True)
    sync.run_sync(db, None, use_cache=True)
    assert fake.calls == 1


def test_run_sync_filters_by_key(db, monkeypatch):
    a = _FakeSource([{"name": "赛 E", "url": "https://e.com/5"}])
    b = _FakeSource([{"name": "赛 F", "url": "https://f.com/6"}])
    b.key, b.label = "fake2", "Fake2"
    _patch(monkeypatch, [a, b])
    results = sync.run_sync(db, ["fake"], use_cache=False)
    assert [r["key"] for r in results] == ["fake"]


def test_bot_blocked_source_is_not_reported_as_success(db, monkeypatch):
    """旧实现把反爬站点的「0 条」记成成功；现在必须显示为失败并给出原因。"""
    _patch(monkeypatch, [_BotBlockedSource()])
    results = sync.run_sync(db, None, use_cache=False)
    assert results[0]["ok"] is False
    assert "反爬" in results[0]["error"]
    row = db.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row["ok"] == 0 and "反爬" in row["error"]


def test_empty_result_is_success_with_note(db, monkeypatch):
    """正常但暂时没有场次的来源：算成功，但提示「暂无可抓取场次」。"""
    _patch(monkeypatch, [_FakeSource([])])
    results = sync.run_sync(db, None, use_cache=False)
    assert results[0]["ok"] is True
    assert "暂无可抓取" in results[0]["note"]


def test_slow_source_does_not_block_sync(db, monkeypatch):
    """某个来源卡死时，整次同步仍能在超时时间内完成。"""
    monkeypatch.setattr(sync, "SOURCE_TIMEOUT_SECONDS", 1.0)
    good = _FakeSource([{"name": "赛 G", "url": "https://g.com/7"}])
    _patch(monkeypatch, [_SlowSource(), good])
    started = time.time()
    results = {r["key"]: r for r in sync.run_sync(db, None, use_cache=False, max_workers=2)}
    elapsed = time.time() - started
    assert elapsed < 4.0
    assert results["slow"]["ok"] is False
    assert "超时" in results["slow"]["error"]
    assert results["fake"]["ok"] is True


def test_hide_vanished_marks_only_stale_online_rows(db, monkeypatch):
    live = _FakeSource([])
    live.key, live.label = "codeforces", "CF"
    monkeypatch.setattr(sync.sources, "live_sources", lambda: [live])
    old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    db.execute("INSERT INTO competitions(name,category,url,source,verify_status,last_seen)"
               " VALUES('旧赛','算法竞赛','https://x.com/1','codeforces','auto',?)", (old,))
    db.execute("INSERT INTO competitions(name,category,url,source,verify_status,last_seen)"
               " VALUES('内置赛','数学建模','https://y.com/1','builtin','manual',?)", (old,))
    hidden = sync.hide_vanished(db)
    assert hidden == 1
    rows = {r["name"]: r["missing_since"] for r in db.execute("SELECT * FROM competitions")}
    assert rows["旧赛"]
    assert not rows["内置赛"]      # 内置/人工数据不受影响


def test_error_text_is_human_friendly():
    import requests
    assert "超时" in sync._error_text(TimeoutError("timed out"))
    assert "反爬" in sync._error_text(RuntimeError("403 Client Error"))
    assert "CSRF" in sync._error_text(RuntimeError("code: EBADCSRFTOKEN"))
    assert "网络不可达" in sync._error_text(
        requests.exceptions.ConnectionError("Max retries exceeded"))
    assert "解析失败" in sync._error_text(ValueError("JSON 解析失败"))


def test_coverage_detection_flags_silent_parser_breakage(db, monkeypatch):
    """解析器没报错、但只抓到零头时，必须给出明确警告（而不是静默成功）。"""
    atcoder = _FakeSource([{"name": "仅一条", "url": "https://atcoder.jp/contests/x"}])
    atcoder.key, atcoder.label = "atcoder", "AtCoder"   # 正常应 >= 3 条
    _patch(monkeypatch, [atcoder])
    result = sync.run_sync(db, None, use_cache=False)[0]
    assert result["ok"] is True                       # 仍然是「成功」……
    assert "atcoder" and "低于" in result["warning"]   # ……但带明确警告
    row = db.execute("SELECT error FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    assert "低于" in row["error"]                     # 警告也写进同步日志


def test_coverage_ok_for_normal_count():
    src = _FakeSource([])
    src.key = "codeforces"
    assert sync.check_coverage(src, 7) == ""
    assert "0 条" in sync.check_coverage(src, 0)
    src.key = "lanqiao"                                # 允许为空
    assert sync.check_coverage(src, 0) == ""


def test_last_results_exposed(monkeypatch, db):
    _patch(monkeypatch, [_FakeSource([{"name": "赛 H", "url": "https://h.com/8"}])])
    sync.run_sync(db, None, use_cache=False)
    info = sync.last_results()
    assert "fake" in info and info["fake"]["ok"] is True
