# -*- coding: utf-8 -*-
"""比赛查询与备赛管理平台 Contest Hub（含自动爬取、时间轴、五维含金量评级）"""
import sqlite3
import json
import os
import re
from datetime import datetime, timedelta

import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "contest.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "contest-hub-secret-dev")

# ---------------- 数据库 ----------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()


BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    organizer TEXT,
    start_date TEXT DEFAULT '',
    end_date TEXT DEFAULT '',
    reg_deadline TEXT DEFAULT '',
    url TEXT,
    desc TEXT,
    tags TEXT DEFAULT '[]',
    source TEXT DEFAULT 'builtin',       -- builtin / codeforces / atcoder / manual
    info_updated TEXT DEFAULT (date('now','localtime')),  -- 信息最后核实日期
    -- 五维含金量评分（各 1~5 分）
    tier TEXT DEFAULT 'B',               -- 主办方级别 S/A/B/C
    s_difficulty INTEGER DEFAULT 3,      -- 获奖难度与淘汰率
    s_history INTEGER DEFAULT 3,         -- 历史积淀与规模
    s_policy INTEGER DEFAULT 3,          -- 政策挂钩（保研/综测/落户）
    s_industry INTEGER DEFAULT 3         -- 行业认可度
);
CREATE TABLE IF NOT EXISTS favorites (
    comp_id INTEGER PRIMARY KEY REFERENCES competitions(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comp_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    due TEXT,
    done INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comp_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    content TEXT,
    auto_points TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
"""


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(BASE_SCHEMA)
    # 旧库迁移：补充新列
    cols = {r[1] for r in db.execute("PRAGMA table_info(competitions)")}
    migrations = {
        "source": "TEXT DEFAULT 'builtin'", "tier": "TEXT DEFAULT 'B'",
        "s_difficulty": "INTEGER DEFAULT 3", "s_history": "INTEGER DEFAULT 3",
        "s_policy": "INTEGER DEFAULT 3", "s_industry": "INTEGER DEFAULT 3",
        "info_updated": "TEXT",
    }
    for col, decl in migrations.items():
        if col not in cols:
            db.execute(f"ALTER TABLE competitions ADD COLUMN {col} {decl}")
    if "info_updated" not in cols:
        db.execute("UPDATE competitions SET info_updated=date('now','localtime')")
    if not db.execute("SELECT COUNT(*) FROM competitions WHERE source='builtin'").fetchone()[0]:
        seed(db)
    db.commit()
    db.close()


# ---------------- 含金量综合评级 ----------------
TIER_WEIGHTS = dict(S=5, A=4, B=3, C=2)

def calc_level(tier, d, h, p, i):
    """加权：主办方级别权重最高(35%)，获奖难度25%，政策挂钩15%，行业认可度15%，历史积淀10%"""
    base = TIER_WEIGHTS.get(tier, 3)
    score = base * .35 + d * .25 + p * .15 + i * .15 + h * .10
    return max(1, min(5, round(score)))


def enrich(c):
    """给比赛字典补充分数/状态等展示字段"""
    c["level"] = calc_level(c["tier"], c["s_difficulty"], c["s_history"],
                            c["s_policy"], c["s_industry"])
    today = datetime.now().date()
    d2 = lambda s: datetime.strptime(s, "%Y-%m-%d").date() if s else None
    st, en, dl = d2(c["start_date"]), d2(c["end_date"]), d2(c["reg_deadline"])
    # 状态判定（优先级从高到低，避免“已结束却显示报名中”）
    if not st and not dl:
        status = "长期开放"
    elif en and en < today:                      # 结束日期已过 → 一定已结束
        status = "已结束"
    elif st and st < today and not en:           # 已开赛且无结束日期 → 视为进行中
        status = "进行中"
    elif st and st <= today and (not en or en >= today):
        status = "进行中"
    elif dl and dl >= today:
        status = "即将截止" if (dl - today).days <= 14 else "报名中"
    elif dl and dl < today and st and st > today:
        status = "报名已截止·待开赛"
    else:
        status = "已结束"
    c["status"] = status
    c["days_dl"] = (dl - today).days if dl else None
    c["days_start"] = (st - today).days if st else None
    # 信息新鲜度：超过 60 天未核实标记可能过期
    try:
        upd = datetime.strptime(c.get("info_updated") or "", "%Y-%m-%d").date()
        c["stale"] = (today - upd).days > 60
    except ValueError:
        c["stale"] = False
    return c


STATUS_STYLE = {"报名中": "ok", "即将截止": "warn", "报名已截止·待开赛": "gray",
                "进行中": "live", "已结束": "over", "长期开放": "ok"}

# ---------------- 种子数据 ----------------
def seed(db):
    # name, category, organizer, start, end, reg_deadline, url, desc, tags,
    # tier, 难度, 历史, 政策, 行业
    comps = [
        ("ACM-ICPC 亚洲区域赛", "算法竞赛", "ACM 国际大学生程序设计竞赛委员会",
         "2026-10-17", "2026-10-19", "2026-09-01", "https://icpc.global/",
         "全球最具影响力的大学生算法赛事，金牌是算法能力的顶级背书，大厂面试直通车。",
         '["团队赛","算法","内推直通车"]', "B", 5, 5, 5, 5),
        ("CCPC 中国大学生程序设计竞赛（总决赛）", "算法竞赛", "中国大学生程序设计竞赛协会",
         "2026-04-25", "2026-04-26", "2026-03-31", "https://ccpc.io/",
         "国内最高水平大学生程序设计赛事。第11届总决赛已于 2026年4月25-26日在南阳理工学院举行（已结束）；网络预选赛通常每年9月线上举行，请关注官网通知。",
         '["团队赛","算法","保研加分"]', "A", 5, 4, 5, 5),
        ("蓝桥杯大赛（省赛→国赛）", "程序设计", "工业和信息化部人才交流中心",
         "2026-04-12", "2026-06-05", "2026-03-10", "https://dasai.lanqiao.cn/",
         "国内规模最大IT学科竞赛之一，校赛-省赛-国赛三级选拔，综测加分覆盖面极广。",
         '["算法","个人赛","综测加分"]', "A", 3, 4, 4, 4),
        ("全国大学生数学建模竞赛 CUMCM", "数学建模", "中国工业与应用数学学会 + 教育部认可",
         "2026-09-11", "2026-09-14", "2026-08-20", "https://www.mcm.edu.cn/",
         "高教社杯，全国超1500所高校参赛，国一获奖率<0.5%，保研加分硬通货。",
         '["团队赛","建模","保研硬通货"]', "S", 5, 5, 5, 5),
        ("美国大学生数学建模竞赛 MCM/ICM", "数学建模", "美国数学及其应用联合会 COMAP",
         "2027-02-06", "2027-02-10", "2027-01-25", "https://www.comap.com/contests/mcm-icm",
         "全球最著名国际数学建模赛，M/O 奖对留学申请极具分量，获奖率约 6%。",
         '["团队赛","英文论文","留学"]', "B", 4, 5, 4, 4),
        ("Codeforces Round 系列周赛", "算法竞赛", "Codeforces（Telegram 创始人赞助运营）",
         "", "", "", "https://codeforces.com/contests",
         "每周多场在线赛，rating 是程序员算法能力国际通行证，Div1 高排名可获大厂关注。",
         '["个人赛","每周举办","免费"]', "B", 4, 5, 2, 5),
        ("AtCoder 周赛（ABC/ARC/AGC）", "算法竞赛", "AtCoder Inc.（日本）",
         "", "", "", "https://atcoder.jp/contests/",
         "日本顶级 OJ，AGC 高难度赛制受国际认可，每周六晚固定举办。",
         '["个人赛","每周举办","免费"]', "B", 4, 4, 1, 4),
        ("LeetCode 周赛 / 双周赛", "算法竞赛", "力扣",
         "", "", "", "https://leetcode.cn/contest/",
         "每周日周赛、周六双周赛，国内大厂面试参考度高，前50名有荣誉认证。",
         '["个人赛","每周举办","免费"]', "C", 3, 4, 2, 4),
        ("全国大学生信息安全竞赛 CISCN", "网络安全", "教育部网络空间安全专业教指委",
         "2026-05-16", "2026-05-18", "2026-04-30", "https://www.ciscn.cn/",
         "网安领域国家级最高赛事（CTF），入选全国普通高校竞赛排行榜，保研利器。",
         '["CTF","团队赛","保研加分"]', "S", 4, 4, 5, 5),
        ("强网杯全国网络安全挑战赛", "网络安全", "信息工程大学 + 河南省",
         "2026-06-13", "2026-06-15", "2026-05-31", "https://www.qiangwangbei.com/",
         "高规格国家级 CTF，线上初选+线下总决赛，业内公认的高水平赛事。",
         '["CTF","团队赛"]', "S", 4, 3, 4, 5),
        ("Kaggle 竞赛 (Featured)", "数据科学", "Google Kaggle",
         "", "", "", "https://www.kaggle.com/competitions",
         "全球最大数据科学平台，金牌率约前0.2%，业界简历认可度极高。",
         '["机器学习","金银牌体系","求职"]', "A", 5, 5, 2, 5),
        ("天池大赛（阿里云）", "数据科学", "阿里巴巴集团",
         "", "", "", "https://tianchi.aliyun.com/competition/activeList",
         "国内最大数据竞赛平台，奖金池常达百万级，冠军方案被业界广泛引用。",
         '["机器学习","高奖金","实习绿色通道"]', "A", 4, 4, 3, 5),
        ("华为软件精英挑战赛", "程序设计", "华为技术有限公司",
         "2026-03-01", "2026-05-31", "2026-04-15", "https://competition.huaweicloud.com/codecraft/",
         "华为旗舰软件赛事，总奖金超百万，优秀者直通天才少年/SP offer 通道。",
         '["算法","高奖金","offer直通车"]', "A", 4, 3, 3, 5),
        ("中国大学生计算机设计大赛", "综合创新", "教育部高校计算机类教指委联合主办",
         "2026-07-15", "2026-08-21", "2026-05-31", "https://jsjds.blcu.edu.cn/",
         "入选教育部竞赛排行榜，校-省-国三级选拔，覆盖软件开发/AI/数媒多赛道。",
         '["作品赛","软件","AI"]', "S", 3, 4, 5, 4),
        ('"挑战杯"课外学术科技作品竞赛', "创新创业", "共青团中央 / 中国科协 / 教育部",
         "2026-10-01", "2026-10-31", "2026-07-31", "https://www.tiaozhanbei.net/",
         "大学生科技创新奥林匹克，两年一届，特等奖保研力度极大，全国2000+高校参与。",
         '["科创","作品赛","保研王牌"]', "S", 5, 5, 5, 5),
        ('"互联网+"中国国际大学生创新大赛', "创新创业", "教育部 + 中央统战部等部委",
         "2026-10-15", "2026-11-05", "2026-08-31", "https://cy.ncss.cn/",
         "规格最高的双创赛事，金奖项目受资本与媒体广泛关注，国赛金奖可直接保研。",
         '["创业","路演","风投关注"]', "S", 4, 4, 5, 4),
        ("百度之星程序设计大赛", "程序设计", "百度公司",
         "2026-06-01", "2026-08-31", "2026-07-31", "https://star.baidu.com/",
         "老牌企业算法赛事（20届+），决赛选手可获百度实习绿色通道。",
         '["算法","企业赛","实习机会"]', "A", 3, 4, 2, 4),
        ("全国大学生电子设计竞赛", "嵌入式硬件", "教育部 + 工信部联合主办",
         "2027-07-28", "2027-07-31", "2026-06-30", "https://nuedc.xjtu.edu.cn/",
         "电子信息类最权威赛事（瑞萨杯），单届参赛超4万队，国一对保研极有帮助。",
         '["单片机","硬件","保研硬通货"]', "S", 4, 5, 5, 5),
        ("蓝桥杯青少年组 / NOIP 系列", "算法竞赛", "中国计算机学会 CCF",
         "2026-07-20", "2026-07-26", "2026-05-15", "https://www.noi.cn/",
         "NOI 系列面向中学生，金牌保送清北级别；由 CCF 主办，规则成熟口碑极佳。",
         '["中学生","算法","保送"]', "B", 5, 5, 4, 5),
        ("服务外包创新创业大赛", "创新创业", "商务部 + 教育部等",
         "2026-05-20", "2026-08-15", "2026-04-30", "http://www.fwwb.org/",
         "国家级 A 类赛事，校企合作导向强，获奖对评奖评优和就业均有帮助。",
         '["创新","校企","综测加分"]', "S", 3, 3, 4, 3),
    ]
    for c in comps:
        db.execute(
            "INSERT INTO competitions(name,category,organizer,start_date,end_date,"
            "reg_deadline,url,desc,tags,source,tier,s_difficulty,s_history,s_policy,s_industry)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*c[:9], "builtin", *c[9:]))


# ---------------- 工具 ----------------
def days_until(date_str):
    if not date_str:
        return None
    try:
        return (datetime.strptime(date_str, "%Y-%m-%d").date()
                - datetime.now().date()).days
    except ValueError:
        return None


def auto_keypoints(comp):
    pts = []
    dl = days_until(comp["reg_deadline"])
    st = days_until(comp["start_date"])
    if dl is not None:
        pts.append(f"⏰ 距报名截止还有 {dl} 天（{comp['reg_deadline']}），务必提前注册！"
                   if dl >= 0 else "❌ 本届报名已截止，请关注下一届通知。")
    else:
        pts.append("ℹ️ 该赛事常年开放/按场次报名，请到官网查看最新场次。")
    if st is not None and st >= 0:
        pts.append(f"🏁 距开赛约 {st} 天（{comp['start_date']}），建议倒推制定训练计划。")
    lv = calc_level(comp["tier"], comp["s_difficulty"], comp["s_history"],
                    comp["s_policy"], comp["s_industry"])
    pts.append(f"⭐ 综合含金量 {'★'*lv}{'☆'*(5-lv)}（主办方级别 {comp['tier']} 级）")
    pts.append(f"🏛️ 主办方：{comp['organizer']}")
    tips = {
        "算法竞赛": ["刷 Codeforces/AtCoder 保持 rating", "组队磨合分工", "整理模板库"],
        "程序设计": ["刷历年真题", "熟悉比赛语言与环境", "掌握常见数据结构模板"],
        "数学建模": ["准备常用模型库", "练习 LaTeX 排版", "明确建模/编程/写作分工"],
        "网络安全": ["搭建靶场环境", "刷 BUUCTF、攻防世界历史题", "整理 CTF 工具箱"],
        "数据科学": ["复现往届 Top 方案", "积累特征工程技巧", "尽早组队"],
        "创新创业": ["打磨商业计划书 BP", "准备路演 PPT", "补充专利/软著支撑"],
        "综合创新": ["确定赛道选题尽早启动", "完善文档与演示视频"],
        "嵌入式硬件": ["备好器件与开发板", "练习历年真题", "强化 PCB 与调试"],
    }
    for t in tips.get(comp["category"], ["研读官方规则", "制定每日备赛表"]):
        pts.append("💡 " + t)
    pts.append("🔗 官方入口：" + comp["url"])
    return pts


DIMENSIONS = [("tier", "主办方级别"), ("s_difficulty", "获奖难度"),
              ("s_history", "历史积淀"), ("s_policy", "政策挂钩"),
              ("s_industry", "行业认可")]


# ---------------- 爬虫模块 ----------------
def crawl_codeforces():
    """通过官方 API 抓取未来 Codeforces 比赛"""
    r = requests.get("https://codeforces.com/api/contest.list", timeout=15,
                     headers={"User-Agent": "ContestHub/1.0"})
    data = r.json()
    if data.get("status") != "OK":
        raise RuntimeError("CF API 返回异常")
    out = []
    for c in data["result"]:
        if c["phase"] != "BEFORE" or len(out) >= 12:
            continue
        start = datetime.fromtimestamp(c["startTimeSeconds"]).strftime("%Y-%m-%d %H:%M")
        out.append(dict(
            name=f"Codeforces {c['name']}",
            category="算法竞赛",
            organizer="Codeforces",
            start_date=start[:10], end_date="", reg_deadline="",
            url=f"https://codeforces.com/contests/{c['id']}",
            desc=f"Div.{c.get('diff','?')} 在线赛，开始于 {start}（北京时间以官网为准），时长约 {round((c['durationSeconds'] or 7200)/3600,1)} 小时。",
            tags=json.dumps(["个人赛", "免费", "rating 赛"], ensure_ascii=False),
            tier="B", difficulty=4))
    return out


def crawl_atcoder():
    """解析 AtCoder 比赛列表页（无官方API，用正则提取）"""
    r = requests.get("https://atcoder.jp/contests/?lang=zh", timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 ContestHub/1.0"})
    r.encoding = "utf-8"
    html = r.text
    out, seen = [], set()
    # 页面结构：每行 <tr> 中先出现 <time>，再出现 <a href="/contests/xxx">名称</a>
    for m in re.finditer(
            r'<time[^>]*>([\d\-]+ [\d:]+)(?:\+0900)?</time>.*?<a href="/contests/([\w-]+)">([^<]*)</a>',
            html, re.S):
        tm, cid, title = m.group(1), m.group(2), m.group(3).strip()
        if cid in seen:
            continue
        seen.add(cid)
        start = tm.split("+")[0]
        prefix = cid[:3].lower()
        rate = {"abc": ("ABC", 2), "arc": ("ARC", 3), "agc": ("AGC", 4)}.get(prefix, (prefix.upper(), 2))
        out.append(dict(
            name=f"AtCoder {title or rate[0]}",
            category="算法竞赛",
            organizer="AtCoder",
            start_date=start.split(" ")[0], end_date="", reg_deadline="",
            url=f"https://atcoder.jp/contests/{cid}",
            desc=f"{rate[0]} 场次，开始于 {start}（日本时间）。ABC 适合入门，AGC 为最高难度巡回赛。",
            tags=json.dumps(["个人赛", "免费"], ensure_ascii=False),
            tier="B", difficulty=rate[1]))
        if len(out) >= 8:
            break
    return out


def upsert_crawled(db, items):
    added = updated = 0
    for it in items:
        row = db.execute("SELECT id FROM competitions WHERE url=?", (it["url"],)).fetchone()
        if row:
            db.execute("UPDATE competitions SET name=?, start_date=?, end_date=?, "
                       "info_updated=date('now','localtime') WHERE id=?",
                       (it["name"], it["start_date"], it["end_date"], row["id"]))
            updated += 1
        else:
            db.execute(
                "INSERT INTO competitions(name,category,organizer,start_date,end_date,"
                "reg_deadline,url,desc,tags,source,tier,s_difficulty,s_history,s_policy,s_industry)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (it["name"], it["category"], it["organizer"], it["start_date"],
                 it["end_date"], it["reg_deadline"], it["url"], it["desc"], it["tags"],
                 it.get("source", "crawl"), it["tier"], it["difficulty"],
                 4, 1, 4))  # 爬取的在线赛：政策挂钩低、历史积淀默认4
            added += 1
    return added, updated


# ---------------- 路由 ----------------
@app.route("/")
def index():
    range_days = request.args.get("range", 60, type=int)
    category = request.args.get("category", "").strip()
    min_level = request.args.get("min_level", 0, type=int)
    tier = request.args.get("tier", "").strip()
    status = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()
    fav_only = request.args.get("fav", 0, type=int)
    sort = request.args.get("sort", "deadline").strip()

    db = get_db()
    comps = [enrich(dict(r)) for r in db.execute("SELECT * FROM competitions")]

    if range_days > 0:  # 未来N天内开赛 或 长期开放
        comps = [c for c in comps
                 if (c["days_start"] is not None and 0 <= c["days_start"] <= range_days)
                 or c["status"] == "长期开放"]
    if fav_only:
        fav_ids = {r["comp_id"] for r in db.execute("SELECT comp_id FROM favorites")}
        comps = [c for c in comps if c["id"] in fav_ids]
    if category:
        comps = [c for c in comps if c["category"] == category]
    if tier:
        comps = [c for c in comps if c["tier"] == tier]
    if status:
        comps = [c for c in comps if c["status"] == status]
    if min_level:
        comps = [c for c in comps if c["level"] >= min_level]
    if q:
        ql = q.lower()
        comps = [c for c in comps if ql in c["name"].lower()
                 or ql in (c["tags"] or "").lower() or ql in (c["desc"] or "").lower()]

    keymap = {
        "deadline": lambda c: (c["status"] == "已结束", c["days_dl"] is None,
                               c["days_dl"] or 0, -c["level"]),
        "level": lambda c: (-c["level"], -(TIER_WEIGHTS.get(c["tier"], 0))),
        "start": lambda c: (c["days_start"] is None, c["days_start"] or 0),
    }
    comps.sort(key=keymap.get(sort, keymap["deadline"]))

    categories = sorted({c["category"] for c in db.execute("SELECT DISTINCT category FROM competitions")})

    # 时间轴：有确定日期且在窗口内的比赛
    tl_range = max(range_days, 60)
    timeline = []
    for c in comps:
        ds = c["days_start"]
        if ds is None:
            continue
        if -7 <= ds <= tl_range:  # 允许最近一周内开始的仍显示在轴上
            pos = max(0, min(100, (ds + 7) / (tl_range + 7) * 100))
            stack = sum(1 for t in timeline if abs(t["pos"] - pos) < 4)
            timeline.append(dict(id=c["id"], name=c["name"], pos=pos, level=c["level"],
                                 status=c["status"], lane=min(stack, 3)))
    timeline.sort(key=lambda t: t["pos"])

    deadline_soon = sorted(
        [(c, c["days_dl"]) for c in enrich_all(db) if c["days_dl"] is not None and 0 <= c["days_dl"] <= 14],
        key=lambda x: x[1])[:8]

    return render_template("index.html", comps=comps, categories=categories,
                           timeline=timeline, STATUS_STYLE=STATUS_STYLE,
                           DIMENSIONS=DIMENSIONS, TIER_WEIGHTS=TIER_WEIGHTS,
                           filters=dict(range=range_days, category=category, min_level=min_level,
                                        tier=tier, status=status, q=q, fav=fav_only, sort=sort),
                           deadline_soon=deadline_soon)


def enrich_all(db):
    return [enrich(dict(r)) for r in db.execute("SELECT * FROM competitions")]


@app.post("/fav/<int:cid>")
def toggle_fav(cid):
    db = get_db()
    if db.execute("SELECT 1 FROM favorites WHERE comp_id=?", (cid,)).fetchone():
        db.execute("DELETE FROM favorites WHERE comp_id=?", (cid,))
    else:
        db.execute("INSERT INTO favorites(comp_id) VALUES(?)", (cid,))
    db.commit()
    return jsonify(ok=True)


@app.post("/crawl")
def crawl():
    src = request.form.get("src", "all")
    items, errors = [], []
    try:
        if src in ("all", "codeforces"):
            items += crawl_codeforces()
    except Exception as e:
        errors.append("Codeforces: " + str(e)[:80])
    try:
        if src in ("all", "atcoder"):
            items += crawl_atcoder()
    except Exception as e:
        errors.append("AtCoder: " + str(e)[:80])
    if items:
        db = get_db()
        added, updated = upsert_crawled(db, items)
        db.commit()
        msg = f"✅ 同步完成：新增 {added} 场，更新 {updated} 场"
    else:
        msg = "⚠️ 本次没有抓到新比赛"
    for e in errors:
        msg += f"｜{e}"
    flash(msg)
    return redirect(url_for("index"))


@app.post("/comp/add")
def add_comp():
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        flash("⚠️ 比赛名称不能为空，已取消添加")
        return redirect(url_for("index"))
    db = get_db()
    db.execute(
        "INSERT INTO competitions(name,category,organizer,start_date,end_date,reg_deadline,"
        "url,desc,tags,source,tier,s_difficulty,s_history,s_policy,s_industry)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, (f.get("category") or "其他").strip(), (f.get("organizer") or "").strip() or None,
         f.get("start_date") or "", f.get("end_date") or "", f.get("reg_deadline") or "",
         (f.get("url") or "").strip() or "#", (f.get("desc") or "").strip() or "暂无简介",
         "[]", "manual",
         f.get("tier", "B"), int(f.get("s_difficulty", 3) or 3), int(f.get("s_history", 3) or 3),
         int(f.get("s_policy", 3) or 3), int(f.get("s_industry", 3) or 3)))
    db.commit()
    flash(f"✅ 已手动添加比赛：{name}")
    return redirect(url_for("index"))


@app.route("/comp/<int:cid>", methods=["GET", "POST"])
def comp_detail(cid):
    db = get_db()
    row = db.execute("SELECT * FROM competitions WHERE id=?", (cid,)).fetchone()
    if not row:
        return redirect(url_for("index"))
    comp = enrich(dict(row))

    if request.method == "POST":
        content = request.form.get("note", "")
        r2 = db.execute("SELECT id FROM notes WHERE comp_id=?", (cid,)).fetchone()
        auto = auto_keypoints(comp)
        if r2:
            db.execute("UPDATE notes SET content=?, auto_points=?, updated_at=datetime('now','localtime') WHERE id=?",
                       (content, json.dumps(auto, ensure_ascii=False), r2["id"]))
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
    return render_template("detail.html", comp=comp, note=note, plans=plans,
                           STATUS_STYLE=STATUS_STYLE, DIMENSIONS=DIMENSIONS,
                           TIER_WEIGHTS=TIER_WEIGHTS)


@app.post("/plan/add/<int:cid>")
def add_plan(cid):
    title = request.form.get("title", "").strip() or "我的参赛计划"
    db = get_db()
    db.execute("INSERT INTO plans(comp_id,title) VALUES(?,?)", (cid, title))
    db.commit()
    return redirect(url_for("comp_detail", cid=cid))


@app.post("/plan/delete/<int:pid>")
def del_plan(pid):
    cid = request.form.get("cid", type=int)
    get_db().execute("DELETE FROM plans WHERE id=?", (pid,))
    get_db().commit()
    return redirect(url_for("comp_detail", cid=cid))


@app.post("/task/add/<int:pid>")
def add_task(pid):
    db = get_db()
    content = request.form.get("content", "").strip()
    due = request.form.get("due", "").strip() or None
    cid = request.form.get("cid", type=int) or (db.execute(
        "SELECT comp_id FROM plans WHERE id=?", (pid,)).fetchone() or [None])[0]
    if content and cid:
        db.execute("INSERT INTO tasks(plan_id,content,due) VALUES(?,?,?)", (pid, content, due))
        db.commit()
    return redirect(url_for("comp_detail", cid=cid))


@app.post("/task/toggle/<int:tid>")
def toggle_task(tid):
    cid = request.form.get("cid", type=int)
    db = get_db()
    db.execute("UPDATE tasks SET done=1-done WHERE id=?", (tid,))
    db.commit()
    return redirect(url_for("comp_detail", cid=cid))


@app.post("/task/delete/<int:tid>")
def del_task(tid):
    cid = request.form.get("cid", type=int)
    get_db().execute("DELETE FROM tasks WHERE id=?", (tid,))
    get_db().commit()
    return redirect(url_for("comp_detail", cid=cid))


if __name__ == "__main__":
    init_db()
    print("[OK] Contest Hub 已启动: http://127.0.0.1:5000")
    app.run(debug=False, port=5000)
