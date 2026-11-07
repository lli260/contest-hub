# -*- coding: utf-8 -*-
"""页面路由（蓝图）。"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, Response, flash, jsonify, redirect,
                   render_template, request, url_for)

from . import sources, sync
from .db import connect, get_db
from .rules.dedup import mark_verified, normalize_url
from .rules.rating import (DIMENSIONS, STATUS_CHOICES, STATUS_STYLE, TIER_WEIGHTS,
                     enrich, enrich_all, parse_date)
from .util import auto_keypoints

bp = Blueprint("main", __name__)

# 卡片上的来源徽章文案
SOURCE_LABELS = {
    "builtin": "预置精选",
    "manual": "手动添加",
    "curated": "官网入口",
    "crawl": "历史抓取",
}
for _s in sources.describe_all():
    SOURCE_LABELS[_s["key"]] = _s["label"]

#: 手动同步使用独立连接（后台线程里没有 Flask 请求上下文）
_sync_thread = None
_sync_guard = threading.Lock()
_sync_state = {"running": False, "started": None, "finished": None, "result": None}


def _date_filter_bounds(args):
    """解析日期范围过滤（起止日期 + 只显示未结束）。"""
    start_from = parse_date(args.get("from"))
    start_to = parse_date(args.get("to"))
    return start_from, start_to


def _in_range(c, start_from, start_to):
    d = parse_date(c.get("start_date")) or parse_date(c.get("end_date"))
    if not d:
        return start_from is None and start_to is None
    if start_from and d < start_from:
        return False
    if start_to and d > start_to:
        return False
    return True


@bp.get("/")
def index():
    range_days = request.args.get("range", 90, type=int)
    category = request.args.get("category", "").strip()
    min_level = request.args.get("min_level", 0, type=int)
    tier = request.args.get("tier", "").strip()
    status = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()
    fav_only = request.args.get("fav", 0, type=int)
    sort = request.args.get("sort", "deadline").strip()
    source = request.args.get("source", "").strip()
    hide_ended = request.args.get("ended", 0, type=int) == 0  # 默认不显示已结束
    start_from, start_to = _date_filter_bounds(request.args)

    db = get_db()
    all_comps = enrich_all(db)
    fav_ids = {r["comp_id"] for r in db.execute("SELECT comp_id FROM favorites")}
    for c in all_comps:
        c["fav"] = c["id"] in fav_ids

    comps = all_comps
    if hide_ended and not status:
        comps = [c for c in comps if c["status"] != "已结束"]
    if range_days > 0:  # 未来 N 天内开赛 或 长期开放/日期待定的年度大赛
        comps = [c for c in comps
                 if (c["days_start"] is not None and -3 <= c["days_start"] <= range_days)
                 or (c["days_start"] is None and c["status"] in ("长期开放", "日期待定", "报名中", "即将截止"))]
    if start_from or start_to:
        comps = [c for c in comps if _in_range(c, start_from, start_to)]
    if fav_only:
        comps = [c for c in comps if c["fav"]]
    if category:
        comps = [c for c in comps if c["category"] == category]
    if tier:
        comps = [c for c in comps if c["tier"] == tier]
    if status:
        comps = [c for c in comps if c["status"] == status]
    if source:
        comps = [c for c in comps if c["source"] == source]
    if min_level:
        comps = [c for c in comps if c["level"] >= min_level]
    if q:
        ql = q.lower()
        comps = [c for c in comps if ql in c["name"].lower()
                 or ql in (c["tags"] or "").lower() or ql in (c["desc"] or "").lower()
                 or ql in (c["organizer"] or "").lower()
                 or ql in (c["ratings"] or "").lower()]

    keymap = {
        "deadline": lambda c: (c["status"] == "已结束", c["days_dl"] is None,
                               c["days_dl"] or 0, -c["level"]),
        "level": lambda c: (-c["level"], -(TIER_WEIGHTS.get(c["tier"], 0))),
        "start": lambda c: (c["days_start"] is None, c["days_start"] or 0),
        "updated": lambda c: (str(c.get("last_checked") or ""),),
    }
    comps.sort(key=keymap.get(sort, keymap["deadline"]))

    categories = sorted({c["category"] for c in all_comps})

    # 时间轴：年度大赛与在线赛分开，避免周赛把轴挤满
    tl_range = max(range_days, 90)
    timeline = {"major": [], "online": []}
    for c in comps:
        ds = c["days_start"]
        if ds is None:
            continue
        if -7 <= ds <= tl_range:
            pos = max(0, min(100, (ds + 7) / (tl_range + 7) * 100))
            bucket = timeline["major" if c["source"] in ("builtin", "manual", "curated")
                              else "online"]
            stack = sum(1 for t in bucket if abs(t["pos"] - pos) < 4)
            bucket.append(dict(id=c["id"], name=c["name"], pos=pos, level=c["level"],
                               status=c["status"], lane=min(stack, 3),
                               when=c["when_text"]))
    for bucket in timeline.values():
        bucket.sort(key=lambda t: t["pos"])

    deadline_soon = sorted(
        [(c, c["days_dl"]) for c in all_comps
         if c["days_dl"] is not None and 0 <= c["days_dl"] <= 14],
        key=lambda x: x[1])[:8]

    counts = {}
    for c in all_comps:
        counts[c["source"]] = counts.get(c["source"], 0) + 1

    return render_template(
        "index.html", comps=comps, categories=categories,
        timeline=timeline, total_timeline=len(timeline["major"]) + len(timeline["online"]),
        STATUS_STYLE=STATUS_STYLE, STATUS_CHOICES=STATUS_CHOICES, DIMENSIONS=DIMENSIONS,
        TIER_WEIGHTS=TIER_WEIGHTS, groups=sources.describe_groups(),
        sync=sync.sync_status(db), SOURCE_LABELS=SOURCE_LABELS, counts=counts,
        source_count=len(sources.all_sources()),
        filters=dict(range=range_days, category=category, min_level=min_level,
                     tier=tier, status=status, q=q, fav=fav_only, sort=sort,
                     source=source, ended=0 if hide_ended else 1,
                     date_from=request.args.get("from", ""),
                     date_to=request.args.get("to", "")),
        deadline_soon=deadline_soon, all_total=len(all_comps))


@bp.get("/health")
def health():
    """数据源健康页：每个来源的最近同步结果 + 一键诊断。"""
    db = get_db()
    status = sync.sync_status(db)
    logs = [dict(r) for r in db.execute(
        "SELECT source,label,ok,added,updated,count,error,ran_at FROM sync_log "
        "ORDER BY id DESC LIMIT 40")]
    return render_template("health.html", sync=status, logs=logs,
                           groups=sources.describe_groups(),
                           SOURCE_LABELS=SOURCE_LABELS, STATUS_STYLE=STATUS_STYLE)


@bp.get("/api/probe")
def api_probe():
    """一键诊断：实时抓取一遍全部来源（不写库），用于排查某个来源是否失效。"""
    return jsonify(ok=True, results=sync.probe_sources())


@bp.post("/api/sync")
def api_sync():
    """异步触发同步（避免页面等 40 秒），立即返回，前端轮询 /api/sync/status。"""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        src = str(payload.get("src") or "all")
    else:
        src = request.form.get("src", "all")
    keys = None if src in ("all", "") else [src]
    if not _start_sync(keys):
        return jsonify(ok=False, busy=True, message="已有同步任务在进行中，请稍候")
    return jsonify(ok=True, message="同步已开始")


def _start_sync(keys):
    global _sync_thread
    with _sync_guard:
        if _sync_state["running"]:
            return False
        _sync_state.update(running=True, started=time.time(), finished=None, result=None)

    from flask import current_app

    db_path = current_app.config["DATABASE"]

    def worker():
        db = connect(db_path)
        try:
            results = sync.run_sync(db, keys, use_cache=False)
            _sync_state["result"] = [
                {k: r.get(k) for k in ("key", "label", "ok", "added", "updated",
                                       "count", "error", "note", "elapsed")}
                for r in results]
        except Exception as exc:  # pragma: no cover
            _sync_state["result"] = [{"key": "error", "label": "同步", "ok": False,
                                      "error": str(exc)[:200], "added": 0,
                                      "updated": 0, "count": 0}]
        finally:
            db.close()
            _sync_state.update(running=False, finished=time.time())

    _sync_thread = threading.Thread(target=worker, name="manual-sync", daemon=True)
    _sync_thread.start()
    return True


@bp.get("/api/sync/status")
def api_sync_status():
    db = get_db()
    status = sync.sync_status(db)
    return jsonify(ok=True, running=_sync_state["running"],
                   started=_sync_state["started"],
                   finished=_sync_state["finished"],
                   result=_sync_state["result"],
                   last_run=status["last_run"],
                   sources=status["sources"])


@bp.post("/crawl")
def crawl():
    """兼容旧链接：同步后重定向回首页。"""
    src = request.form.get("src", "all")
    keys = None if src in ("all", "") else [src]
    if _start_sync(keys):
        flash("🔄 已开始同步，稍后刷新或用下方「同步状态」查看结果")
    else:
        flash("⏳ 已有同步任务在进行中")
    return redirect(request.form.get("next") or url_for("main.index"))


@bp.post("/comp/add")
def add_comp():
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        flash("⚠️ 比赛名称不能为空，已取消添加")
        return redirect(url_for("main.index"))
    db = get_db()
    url = normalize_url(f.get("url")) or "#"
    db.execute(
        "INSERT INTO competitions(name,category,organizer,start_date,end_date,reg_deadline,"
        "url,desc,tags,source,tier,s_difficulty,s_history,s_policy,s_industry,verify_status,"
        "start_at,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,date('now','localtime'))",
        (name, (f.get("category") or "其他").strip(), (f.get("organizer") or "").strip() or None,
         f.get("start_date") or "", f.get("end_date") or "", f.get("reg_deadline") or "",
         url, (f.get("desc") or "").strip() or "暂无简介", "[]", "manual",
         f.get("tier", "B") if f.get("tier") in ("S", "A", "B", "C") else "B",
         _score(f.get("s_difficulty")), _score(f.get("s_history")),
         _score(f.get("s_policy")), _score(f.get("s_industry")), "manual",
         (f.get("start_at") or "").strip()[:16]))
    db.commit()
    flash(f"✅ 已手动添加比赛：{name}")
    return redirect(url_for("main.index"))


def _score(value, default=3):
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return default


@bp.route("/comp/<int:cid>", methods=["GET", "POST"])
def comp_detail(cid):
    db = get_db()
    row = db.execute("SELECT * FROM competitions WHERE id=?", (cid,)).fetchone()
    if not row:
        return redirect(url_for("main.index"))
    comp = enrich(dict(row))

    if request.method == "POST":
        content = request.form.get("note", "")
        auto = auto_keypoints(comp)
        existing = db.execute("SELECT id FROM notes WHERE comp_id=?", (cid,)).fetchone()
        if existing:
            db.execute("UPDATE notes SET content=?, auto_points=?, "
                       "updated_at=datetime('now','localtime') WHERE id=?",
                       (content, json.dumps(auto, ensure_ascii=False), existing["id"]))
        else:
            db.execute("INSERT INTO notes(comp_id,content,auto_points) VALUES(?,?,?)",
                       (cid, content, json.dumps(auto, ensure_ascii=False)))
        db.commit()

    note_row = db.execute("SELECT * FROM notes WHERE comp_id=?", (cid,)).fetchone()
    note = dict(note_row) if note_row else {"content": "", "auto_points": "[]", "updated_at": ""}
    note["auto_list"] = json.loads(note["auto_points"] or "[]")

    plans = []
    for p in db.execute("SELECT * FROM plans WHERE comp_id=? ORDER BY id DESC", (cid,)):
        p = dict(p)
        p["tasks"] = [dict(t) for t in db.execute(
            "SELECT * FROM tasks WHERE plan_id=? ORDER BY done,id", (p["id"],))]
        p["progress"] = (sum(t["done"] for t in p["tasks"]), len(p["tasks"]))
        plans.append(p)

    comp["fav"] = bool(db.execute("SELECT 1 FROM favorites WHERE comp_id=?", (cid,)).fetchone())
    comp["tags"] = json.loads(comp["tags"] or "[]")
    # 「同一场比赛」的其它来源记录（跨来源归并未完全合并时仍可互相跳转）
    siblings = [dict(r) for r in db.execute(
        "SELECT id,name,source,start_date FROM competitions WHERE url=? AND id<>?",
        (comp["url"], cid))]
    return render_template("detail.html", comp=comp, note=note, plans=plans,
                           STATUS_STYLE=STATUS_STYLE, DIMENSIONS=DIMENSIONS,
                           TIER_WEIGHTS=TIER_WEIGHTS, SOURCE_LABELS=SOURCE_LABELS,
                           siblings=siblings)


@bp.post("/plan/add/<int:cid>")
def add_plan(cid):
    title = request.form.get("title", "").strip() or "我的参赛计划"
    db = get_db()
    db.execute("INSERT INTO plans(comp_id,title) VALUES(?,?)", (cid, title))
    db.commit()
    return redirect(url_for("main.comp_detail", cid=cid))


@bp.post("/plan/delete/<int:pid>")
def del_plan(pid):
    cid = request.form.get("cid", type=int)
    db = get_db()
    db.execute("DELETE FROM plans WHERE id=?", (pid,))
    db.commit()
    return redirect(url_for("main.comp_detail", cid=cid))


@bp.post("/task/add/<int:pid>")
def add_task(pid):
    db = get_db()
    content = request.form.get("content", "").strip()
    due = request.form.get("due", "").strip() or None
    cid = request.form.get("cid", type=int)
    if cid is None:
        row = db.execute("SELECT comp_id FROM plans WHERE id=?", (pid,)).fetchone()
        cid = row["comp_id"] if row else None
    if content and cid:
        db.execute("INSERT INTO tasks(plan_id,content,due) VALUES(?,?,?)", (pid, content, due))
        db.commit()
    return redirect(url_for("main.comp_detail", cid=cid))


@bp.post("/task/toggle/<int:tid>")
def toggle_task(tid):
    cid = request.form.get("cid", type=int)
    db = get_db()
    db.execute("UPDATE tasks SET done=1-done WHERE id=?", (tid,))
    db.commit()
    return redirect(url_for("main.comp_detail", cid=cid))


@bp.post("/task/delete/<int:tid>")
def del_task(tid):
    cid = request.form.get("cid", type=int)
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    db.commit()
    return redirect(url_for("main.comp_detail", cid=cid))


@bp.get("/fav/<int:cid>")
def _fav_legacy(cid):  # pragma: no cover - 仅避免 405
    return redirect(url_for("main.comp_detail", cid=cid))


@bp.post("/fav/<int:cid>")
def toggle_fav(cid):
    db = get_db()
    if db.execute("SELECT 1 FROM favorites WHERE comp_id=?", (cid,)).fetchone():
        db.execute("DELETE FROM favorites WHERE comp_id=?", (cid,))
        fav = False
    else:
        db.execute("INSERT INTO favorites(comp_id) VALUES(?)", (cid,))
        fav = True
    db.commit()
    return jsonify(ok=True, fav=fav)


@bp.post("/verify/<int:cid>")
def verify(cid):
    db = get_db()
    mark_verified(db, cid)
    flash("✅ 已标记为「已核实」")
    return redirect(request.form.get("next") or url_for("main.index"))


# ---------------- 日历导出 ----------------
@bp.get("/calendar.ics")
def calendar_ics():
    db = get_db()
    comps = enrich_all(db)
    fav_only = request.args.get("fav", 0, type=int)
    if fav_only:
        fav_ids = {r["comp_id"] for r in db.execute("SELECT comp_id FROM favorites")}
        comps = [c for c in comps if c["id"] in fav_ids]
    body = build_calendar(comps)
    return Response(body, mimetype="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=contest-hub.ics"})


def _ics_escape(text):
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _ics_fold(line):
    """RFC 5545：每行不超过 75 字节，中文按字节折行（续行以单个空格开头）。"""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        # RFC 5545 的 75 字节包含续行开头的那个空格（共 75 个八位组）
        if len(current) + len(b) > 74:
            parts.append(current.decode("utf-8"))
            current = b" "
        current += b
    if current.strip():
        parts.append(current.decode("utf-8"))
    return "\r\n".join(parts)


def build_calendar(comps, now=None):
    """导出 ICS：有精确时间时用带时间的 VEVENT（默认北京时间），否则用全天事件。"""
    from .rules.rating import parse_datetime
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH",
             "PRODID:-//Contest Hub//比赛日程//CN",
             "X-WR-CALNAME:Contest Hub 比赛日程",
             "X-WR-TIMEZONE:Asia/Shanghai"]
    for c in comps:
        events = []
        if c.get("reg_deadline"):
            events.append(("报名截止", c.get("reg_deadline"), None))
        start_dt = parse_datetime(c.get("start_at")) if c.get("start_at") else None
        end_dt = parse_datetime(c.get("end_at")) if c.get("end_at") else None
        if c.get("start_date"):
            events.append(("开赛", c.get("start_date"), (start_dt, end_dt)))
        for kind, value, times in events:
            day = parse_date(value)
            if not day:
                continue
            dtstart = dtend = None
            if times:
                s, e = times
                if s and s.hour + s.minute:
                    dtstart = s.strftime("%Y%m%dT%H%M%S")
                    dtend = (e or (s + timedelta(hours=2))).strftime("%Y%m%dT%H%M%S")
            block = [
                "BEGIN:VEVENT",
                f"UID:comp{c['id']}-{kind}@contest-hub",
                f"DTSTAMP:{stamp}",
            ]
            if dtstart:
                block += [f"DTSTART;TZID=Asia/Shanghai:{dtstart}",
                          f"DTEND;TZID=Asia/Shanghai:{dtend}"]
            else:
                block += [f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                          f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}"]
            block += [
                f"SUMMARY:{_ics_escape('[' + kind + '] ' + c['name'])}",
                f"DESCRIPTION:{_ics_escape(c.get('desc') or '')}",
                f"CATEGORIES:{_ics_escape(c.get('category') or '')}",
            ]
            if c.get("status"):
                block.append(f"X-CONTEST-STATUS:{_ics_escape(c['status'])}")
            if c.get("url") and c["url"] != "#":
                block.append(f"URL:{_ics_escape(c['url'])}")
            block.append("END:VEVENT")
            lines.extend(block)
    lines.append("END:VCALENDAR")
    # 先按逻辑行折行，再用 CRLF 连接：折行本身就是 \r\n + 空格，不能再被拆开
    folded = []
    for line in lines:
        folded.extend(_ics_fold(line).split("\r\n"))
    return "\r\n".join(folded) + "\r\n"
