# -*- coding: utf-8 -*-
"""多源同步编排：并行抓取、硬超时、隔离失败、过期隐藏、同步日志。

与旧实现的差别：

* **并行 + 硬超时**：旧实现串行抓取，一个卡死的站点会把整次同步拖到几分钟；
  现在每个来源一个线程、按来源自带超时 + 全局上限强制结束，整次同步约 40 秒内完成；
* **不再假成功**：反爬 / 需登录的来源会显式报错（见 sources/nowcoder.py），
  同步日志里写明原因，而不是「✅ 0 条」；
* **失败保留旧数据**：抓取失败的来源不会被清空，已有赛程继续展示，
  只是标上最后成功时间与错误原因；
* **过期自动隐藏**：来源里已经消失的在线赛（比如已经比完、被官方下架）会在
  连续 3 天未出现后隐藏，避免「已结束的比赛一直挂在首页」；
* **抓取质量提示**：如果某来源返回 0 条，会在结果里标出「官网暂无可抓取的场次」。
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import sources
from .config import (CACHE_TTL_SECONDS, MAX_PARALLEL, SOURCE_TIMEOUT_SECONDS,
                     SYNC_INITIAL_DELAY, SYNC_INTERVAL_HOURS, VANISH_HIDE_DAYS)
from .rules.dedup import upsert_items
from .db import connect

log = logging.getLogger(__name__)

_lock = threading.Lock()          # 同一时刻只允许一次同步写库
_cache = {}                       # source key -> (timestamp, items)
_last_results = {}                # source key -> 最近一次同步结果（内存，便于前端轮询）

_bg_started = False
_bg_guard = threading.Lock()


def _fetch_one(source, use_cache):
    """在线程池中执行：返回 (source, items, cached, error, elapsed)。

    这里刻意不做缓存写入，缓存统一在 ``_fetch_all`` 里、按完成顺序写入，
    避免多线程同时改 ``_cache``。
    """
    started = time.time()
    now = time.time()
    hit = _cache.get(source.key)
    if use_cache and hit and now - hit[0] < CACHE_TTL_SECONDS:
        return source, hit[1], True, None, round(time.time() - started, 2)
    try:
        items = list(source.fetch() or [])
        return source, items, False, None, round(time.time() - started, 2)
    except Exception as exc:  # 单源失败不影响其它源
        return source, [], False, exc, round(time.time() - started, 2)


#: 各来源「正常应至少抓到的条数」——低于该值说明解析可能部分失效
#: （页面改版常见的症状不是报错，而是只匹配到零星几条）
COVERAGE_FLOOR = {
    "codeforces": 1,
    "atcoder": 3,
    "leetcode": 2,
    "codechef": 2,
    "luogu": 2,
    "kaggle": 5,
    "lanqiao": 0,   # 真有可能没有进行中的赛事
    "moe": 80,      # 大学生竞赛白名单共 84 项，明显少于 80 说明目录数据被误改
}


def check_coverage(source, count):
    """覆盖率检测：返回提示文案；正常返回空字符串。

    这类问题最隐蔽：解析器没抛异常、同步显示成功，但实际只抓到零头，
    用户看到的是「来源变少了」而不知道是解析失效。
    """
    floor = COVERAGE_FLOOR.get(source.key)
    if floor is None or count >= floor:
        return ""
    if count == 0:
        return (f"⚠️ 0 条：该来源可能需要更新解析规则"
                f"（正常应至少 {floor} 条）——请到健康页执行「实时诊断」")
    return (f"⚠️ 仅 {count} 条，低于该来源的常规数量（至少 {floor} 条），"
            f"解析可能部分失效")


def _fetch_all(targets, use_cache, workers):
    """并行抓取所有来源；单个来源超时被强制标记为失败，不影响其它来源。"""
    results = []
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch")
    try:
        futures = {pool.submit(_fetch_one, s, use_cache): s for s in targets}
        deadline = time.time() + SOURCE_TIMEOUT_SECONDS
        for fut, source in futures.items():
            try:
                results.append(fut.result(timeout=max(0.1, deadline - time.time())))
            except TimeoutError:
                fut.cancel()
                results.append((source, [], False,
                                TimeoutError(f"抓取超过 {SOURCE_TIMEOUT_SECONDS} 秒未完成"),
                                float(SOURCE_TIMEOUT_SECONDS)))
            except Exception as exc:  # pragma: no cover - 线程内部已捕获
                results.append((source, [], False, exc, 0.0))
    finally:
        # 不等待仍在阻塞的线程，直接返回（daemon 线程随进程结束）
        pool.shutdown(wait=False, cancel_futures=True)
    # 写入缓存：只缓存成功的抓取结果
    for source, items, cached, error, _elapsed in results:
        if error is None and not cached:
            _cache[source.key] = (time.time(), items)
    return results


def run_sync(db, source_keys=None, use_cache=False, max_workers=None):
    """同步指定数据源（None = 全部），返回每个源的结果列表。

    抓取阶段使用 ``SOURCE_TIMEOUT_SECONDS`` 的硬超时：即使某个来源的
    网络请求卡住，整次同步也不会无限期挂起（超时的来源标记为失败）。
    """
    wanted = set(source_keys) if source_keys else None
    targets = [s for s in sources.all_sources() if not wanted or s.key in wanted]
    if not targets:
        return []

    workers = max_workers or max(1, min(MAX_PARALLEL, len(targets)))
    with _lock:
        started = time.time()
        fetched = _fetch_all(targets, use_cache, workers)

        results = []
        now = datetime.now()
        for source, items, cached, error, elapsed in fetched:
            entry = {"key": source.key, "label": source.label, "group": source.group,
                     "experimental": source.experimental, "ok": False,
                     "added": 0, "updated": 0, "count": len(items), "error": "",
                     "elapsed": elapsed, "cached": cached}
            if error is not None:
                entry["error"] = _error_text(error)
                _write_log(db, entry)
                results.append(entry)
                _last_results[source.key] = entry
                continue
            try:
                added, updated, skipped = upsert_items(db, items, source)
                db.commit()
                entry.update(ok=True, added=added, updated=updated, skipped=skipped)
                if cached:
                    entry["note"] = "本次使用缓存结果"
                if not items:
                    entry["note"] = "官方暂无可抓取的场次（不是抓取失败）"
                # 覆盖率异常时给出显式警告（不是失败，但需要人工留意）
                warning = check_coverage(source, len(items))
                if warning:
                    entry["warning"] = warning
                    log.warning("%s 覆盖率异常：%s", source.label, warning)
            except Exception as exc:  # 写库失败：回滚，不影响其它源
                db.rollback()
                entry["error"] = _error_text(exc)
            _write_log(db, entry)
            results.append(entry)
            _last_results[source.key] = entry
        db.commit()
        # 过期隐藏只在「整轮同步」时执行，避免单源同步误伤
        if wanted is None:
            hidden = hide_vanished(db, now=now)
            if hidden:
                _last_results["_hidden"] = {"hidden": hidden}
        total = round(time.time() - started, 1)
        _last_results["_meta"] = {"last_run": now.strftime("%Y-%m-%d %H:%M:%S"),
                                  "elapsed": total, "sources": len(targets)}
    return results


def _error_text(exc):
    """把异常转成对人友好的说明。"""
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "unavailable" in type(exc).__name__.lower() or "反爬" in text or "无法自动抓取" in text:
        return str(exc)[:200]
    if "ebadcsrftoken" in lowered or "csrf" in lowered:
        return "站点接口需要 CSRF 校验，无法自动抓取"
    if "403" in text:
        return "站点拒绝访问（403），可能已启用反爬"
    if "401" in text or "login" in lowered:
        return "站点需要登录态，无法自动抓取"
    if "timed out" in lowered or "timeout" in lowered:
        return "请求超时，请稍后重试"
    if "certificate" in lowered or "ssl" in lowered:
        return "TLS 证书校验失败（可尝试关闭代理或更新证书）"
    if "connection" in lowered or "name or service not known" in lowered \
            or "getaddrinfo" in lowered or "max retries" in lowered:
        return "网络不可达（断网/被墙/代理问题）"
    if "json" in lowered:
        return "站点返回格式变化，解析失败（需要更新解析规则）"
    if "status" in lowered and "valueerror" in lowered:
        return "站点接口返回异常状态"
    return text[:200]


def _write_log(db, entry):
    try:
        db.execute(
            "INSERT INTO sync_log(source,label,ok,added,updated,count,error) "
            "VALUES(?,?,?,?,?,?,?)",
            (entry["key"], entry["label"], 1 if entry["ok"] else 0,
             entry["added"], entry["updated"], entry["count"],
             entry["error"] or entry.get("warning") or entry.get("note", "")))
    except Exception:  # pragma: no cover
        pass


def hide_vanished(db, now=None, days=None):
    """来源里消失超过 N 天的「在线赛」记录标记隐藏（missing_since）。"""
    days = VANISH_HIDE_DAYS if days is None else days
    now = now or datetime.now()
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    live_keys = [s.key for s in sources.live_sources()]
    if not live_keys:
        return 0
    placeholders = ",".join("?" * len(live_keys))
    cur = db.execute(
        f"UPDATE competitions SET missing_since=? "
        f"WHERE source IN ({placeholders}) AND (verify_status IS NULL OR verify_status='auto') "
        f"AND (missing_since IS NULL OR missing_since='') "
        f"AND (last_seen IS NULL OR last_seen < ?)",
        (now.strftime("%Y-%m-%d"), *live_keys, cutoff))
    db.commit()
    return cur.rowcount or 0


def sync_status(db):
    """返回最近一次各源同步状态与全局最后同步时间。"""
    rows = []
    for r in db.execute(
            "SELECT source,label,ok,added,updated,count,error,ran_at,id FROM sync_log "
            "WHERE id IN (SELECT MAX(id) FROM sync_log GROUP BY source)"):
        row = dict(r)
        # 历史成功次数、连续失败次数，用于展示来源健康度
        ok_total = db.execute(
            "SELECT COUNT(*) FROM sync_log WHERE source=? AND ok=1",
            (row["source"],)).fetchone()[0]
        fail_total = db.execute(
            "SELECT COUNT(*) FROM sync_log WHERE source=? AND ok=0",
            (row["source"],)).fetchone()[0]
        last_ok = db.execute(
            "SELECT MAX(ran_at) FROM sync_log WHERE source=? AND ok=1",
            (row["source"],)).fetchone()[0]
        row.update(ok_total=ok_total, fail_total=fail_total, last_ok=last_ok)
        rows.append(row)
    rows.sort(key=lambda r: r["ran_at"] or "", reverse=True)
    last = db.execute("SELECT MAX(ran_at) AS t FROM sync_log").fetchone()
    total = db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0]
    live = db.execute("SELECT COUNT(*) FROM competitions WHERE source NOT IN "
                      "('builtin','curated','manual')").fetchone()[0]
    hidden = db.execute("SELECT COUNT(*) FROM competitions WHERE missing_since "
                        "IS NOT NULL AND missing_since<>''").fetchone()[0]
    stale = 0
    for r in db.execute("SELECT last_checked FROM competitions"):
        if r["last_checked"] and r["last_checked"] < (
                datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"):
            stale += 1
    meta = dict(_last_results.get("_meta") or {})
    return {"sources": rows, "last_run": (last["t"] if last else None),
            "total": total, "live": live, "hidden": hidden, "stale": stale,
            "meta": meta, "running": _lock.locked(),
            "interval_hours": int(SYNC_INTERVAL_HOURS)}


def last_results():
    """最近一次同步的逐源结果（供前端轮询刷新状态面板）。"""
    return {k: v for k, v in _last_results.items() if not k.startswith("_")}


def clear_cache():
    _cache.clear()


def _worker(app, db_path, interval, delay):
    time.sleep(max(1.0, delay))
    while True:
        db = connect(db_path)
        try:
            results = run_sync(db, None, use_cache=False)
            failed = [r for r in results if not r["ok"]]
            if failed:
                app.logger.info("后台同步完成，%d/%d 个来源失败：%s",
                                len(failed), len(results),
                                "；".join(f"{r['label']}({r['error'][:40]})" for r in failed))
        except Exception as exc:  # 后台线程永不崩溃
            app.logger.warning("后台同步失败: %s", exc)
        finally:
            db.close()
        time.sleep(max(300.0, interval * 3600))


def start_background_sync(app):
    """启动后台定时同步线程（每个进程最多一次）。"""
    global _bg_started
    with _bg_guard:
        if _bg_started or app.config.get("DISABLE_BG_SYNC"):
            return None
        _bg_started = True

    interval = app.config.get("SYNC_INTERVAL_HOURS", SYNC_INTERVAL_HOURS)
    delay = app.config.get("SYNC_INITIAL_DELAY", SYNC_INITIAL_DELAY)
    db_path = app.config["DATABASE"]

    thread = threading.Thread(target=_worker, args=(app, db_path, interval, delay),
                              name="contesthub-sync", daemon=True)
    thread.start()
    return thread


def probe_sources(timeout=None):
    """诊断：逐个来源做一次抓取（不写库），返回每个来源的健康状况。"""
    results = []
    for source in sources.all_sources():
        started = time.time()
        entry = {"key": source.key, "label": source.label, "group": source.group,
                 "experimental": source.experimental, "homepage": source.homepage}
        try:
            items = source.fetch()
            entry.update(ok=True, count=len(items),
                         detail=f"抓取到 {len(items)} 条赛程")
            warning = check_coverage(source, len(items))
            if warning:
                entry["warning"] = warning
        except Exception as exc:
            has_check = hasattr(source, "check")
            entry.update(ok=False, count=0, error=_error_text(exc))
            if has_check:
                try:
                    info = source.check() or {}
                    entry["detail"] = info.get("detail", "")
                except Exception as exc2:
                    entry["detail"] = f"入口探测失败：{_error_text(exc2)}"
        entry["elapsed"] = round(time.time() - started, 2)
        results.append(entry)
    return results
