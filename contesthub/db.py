# -*- coding: utf-8 -*-
"""数据库访问与初始化（含增量迁移）。"""
import sqlite3

from flask import current_app, g

from .config import DEFAULT_DB_PATH
from .seed import (backfill_curated, remove_obsolete_builtin, seed,
                   upgrade_builtin)

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
    source TEXT DEFAULT 'builtin',       -- builtin / manual / curated / 各数据源 key
    source_id TEXT DEFAULT '',           -- 数据源内部 ID（用于稳定去重）
    info_updated TEXT DEFAULT (date('now','localtime')),  -- 信息最后核实日期
    first_seen TEXT DEFAULT (date('now','localtime')),
    last_checked TEXT DEFAULT (date('now','localtime')),
    last_seen TEXT,                      -- 来源最近一次给出这条记录的日期
    missing_since TEXT,                  -- 来源里消失的起始日期（过期隐藏用）
    verify_status TEXT DEFAULT 'auto',   -- auto 自动抓取 / manual 手动录入 / verified 已人工核实
    start_at TEXT DEFAULT '',            -- 精确开赛时间，如 2026-10-18 16:05
    end_at TEXT DEFAULT '',              -- 精确结束时间
    ratings TEXT,                        -- 来源给出的难度/参赛规模描述
    phase TEXT,                          -- 来源给出的比赛阶段（CF BEFORE/CODING/FINISHED）
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
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    label TEXT,
    ok INTEGER DEFAULT 0,
    added INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    count INTEGER DEFAULT 0,
    error TEXT DEFAULT '',
    ran_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_comp_source ON competitions(source);
CREATE INDEX IF NOT EXISTS idx_comp_start ON competitions(start_date);
"""

# 老库增量迁移：列名 -> 声明
MIGRATIONS = {
    "source": "TEXT DEFAULT 'builtin'",
    "source_id": "TEXT DEFAULT ''",
    "tier": "TEXT DEFAULT 'B'",
    "s_difficulty": "INTEGER DEFAULT 3",
    "s_history": "INTEGER DEFAULT 3",
    "s_policy": "INTEGER DEFAULT 3",
    "s_industry": "INTEGER DEFAULT 3",
    "info_updated": "TEXT",
    "first_seen": "TEXT",
    "last_checked": "TEXT",
    "verify_status": "TEXT DEFAULT 'auto'",
    "last_seen": "TEXT",
    "missing_since": "TEXT",
    "start_at": "TEXT DEFAULT ''",
    "end_at": "TEXT DEFAULT ''",
    "ratings": "TEXT",
    "phase": "TEXT",
}


def get_db():
    """获取当前请求上下文内的数据库连接。"""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def connect(db_path=DEFAULT_DB_PATH):
    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    # WAL 让「后台同步写 + 页面读」不再互相阻塞（旧实现用默认 journal，
    # 同步时页面会偶发 database is locked）
    try:
        db.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    return db


def repair_legacy_rows(db):
    """一次性修复老版本留下的脏数据（幂等，每次启动执行都很便宜）。

    旧版本的已知问题：
    * 标题出现「Codeforces Codeforces Round …」「AtCoder AtCoder …」重复前缀；
    * 按 /contests/N 链接的 Codeforces 记录 source_id 为空，无法被新同步认领；
    * 来源标记为 ``crawl`` 的历史记录没有 ``last_seen``，永远不会被过期隐藏；
    * 内置数据里「CCPC 第 11 届总决赛已于 2026-04-25 在南阳理工学院举行」
      属于无依据的表述，已在新版 seed 中更正；
    * 内置记录若还停留在「长期开放」，按新规则应显示为「日期待定」。
    """
    import re

    fixed = {"name": 0, "source_id": 0, "last_seen": 0}
    for row in db.execute("SELECT id,name,url,source,source_id,last_seen FROM competitions"):
        updates = {}
        name = row["name"] or ""
        # 「Codeforces Codeforces Round …」-> 「Codeforces Round …」
        cleaned = re.sub(r"^(Codeforces|AtCoder|LeetCode|CodeChef|Kaggle)\s+\1\s*",
                         r"\1 ", name, flags=re.I)
        if cleaned != name:
            updates["name"] = cleaned
            fixed["name"] += 1
        url = row["url"] or ""
        if not (row["source_id"] or "").strip():
            m = re.search(r"codeforces\.com/contests?/(\d+)", url)
            if m:
                updates["source_id"] = f"cf-{m.group(1)}"
                fixed["source_id"] += 1
            else:
                m = re.search(r"atcoder\.jp/contests/([\w\-]+)", url)
                if m:
                    updates["source_id"] = f"atcoder-{m.group(1)}"
                    fixed["source_id"] += 1
        if row["source"] == "crawl" and not (row["last_seen"] or "").strip():
            # 历史抓取记录：按最后核实日期回填 last_seen
            updates["last_seen"] = row["last_seen"] or "1970-01-01"
            fixed["last_seen"] += 1
        if updates:
            sets = ", ".join(f"{k}=?" for k in updates)
            db.execute(f"UPDATE competitions SET {sets} WHERE id=?",
                       (*updates.values(), row["id"]))
    db.execute("UPDATE competitions SET last_seen=last_checked "
               "WHERE (last_seen IS NULL OR last_seen='') AND last_checked IS NOT NULL")
    db.commit()
    return fixed


def init_db(db_path=DEFAULT_DB_PATH):
    """建表 + 迁移老库 + 首次写入内置数据。"""
    db = connect(db_path)
    try:
        db.executescript(BASE_SCHEMA)
        cols = {r[1] for r in db.execute("PRAGMA table_info(competitions)")}
        for col, decl in MIGRATIONS.items():
            if col not in cols:
                db.execute(f"ALTER TABLE competitions ADD COLUMN {col} {decl}")
        # 回填新列，避免历史数据为空
        db.execute("UPDATE competitions SET info_updated=date('now','localtime') "
                   "WHERE info_updated IS NULL OR info_updated=''")
        db.execute("UPDATE competitions SET first_seen=info_updated "
                   "WHERE first_seen IS NULL OR first_seen=''")
        db.execute("UPDATE competitions SET last_checked=info_updated "
                   "WHERE last_checked IS NULL OR last_checked=''")
        db.execute("UPDATE competitions SET last_seen=last_checked "
                   "WHERE last_seen IS NULL OR last_seen=''")
        db.execute("UPDATE competitions SET verify_status='manual' "
                   "WHERE source='manual' AND (verify_status IS NULL OR verify_status='auto')")
        if not db.execute(
                "SELECT COUNT(*) FROM competitions WHERE source='builtin'").fetchone()[0]:
            seed(db)
        else:
            backfill_curated(db)
            upgrade_builtin(db)
            remove_obsolete_builtin(db)
        repair_legacy_rows(db)
        db.commit()
    finally:
        db.close()
