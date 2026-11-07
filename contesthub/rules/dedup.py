# -*- coding: utf-8 -*-
"""数据清洗与去重：URL/名称归一化、字段校验、跨来源实体归并、来源归属保护。

与旧实现相比的关键修复：

1. **跨来源归并**：旧实现只按 source_id / URL / 名称精确匹配，于是
   「Codeforces Round 900」被各来源各存一条；而且 sync 时会给**别的来源**
   的记录打上自己的 source_id，造成数据转手。现在按「URL 精确 → 来源内
   source_id → 名称归一化 + 日期容错」匹配，并且只有**同来源**才写 source_id。
2. **字段不互相覆盖**：旧实现同步时无条件覆盖 name/desc，导致内置的人工描述
   被机器翻译的短句冲掉，并出现「Codeforces Codeforces Round …」重复前缀。
   现在名称/描述/主办方只在「本来源占位记录」或「同步结果更完整」时更新。
3. **脏日期拦截**：明显不合法的日期（过去太久的开赛日、距今 3 年以上的
   开赛日、结束早于开始）一律丢弃，避免卡片显示错误年份。
4. **持久化字段**：每行记录最后见到该比赛的日期（last_seen / missing_since），
   供同步时自动隐藏「来源里已经消失」的过期记录。
"""
import json
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .moderation import hidden_reason
from .rating import parse_date

# 需要剔除的跟踪参数
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "spm", "from", "share_token", "ref", "_t"}

# 各来源展示用分组
SOURCE_GROUPS = {
    "builtin": "预置",
    "manual": "手动添加",
    "curated": "精选入口",
}

# 名称归一化时需要去掉的「品牌/平台」前后缀，便于跨来源匹配同一场比赛
_BRAND_PREFIXES = ("codeforces", "atcoder", "leetcode", "力扣", "codechef",
                   "kaggle", "牛客", "洛谷", "蓝桥杯", "天池", "nowcoder")

# 名称里出现的「年度」是绝大多数比赛都有的通用词（Kaggle 竞赛名里尤其常见），
# 不能当作「场次号」参与同一场比赛的判定，否则会把不同竞赛误合并。
_COMMON_NUMBERS = {"2024", "2025", "2026", "2027", "2028", "2023"}
_CN_NUM = str.maketrans("０１２３４５６７８９", "0123456789")


def normalize_url(url):
    """归一化 URL：统一 host 大小写、去跟踪参数/片段/尾部斜杠。"""
    if not url:
        return ""
    url = str(url).strip()
    if not url or url == "#":
        return ""
    if not re.match(r"^https?://", url, re.I):
        return url.lower()
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if k.lower() not in _TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def normalize_name(name):
    """归一化名称用于模糊比较：去空白/标点，统一大小写。

    刻意保留数字（场次号），避免把「Round 900」与「Round 901」误判为同一场。
    """
    if not name:
        return ""
    text = str(name).lower().translate(_CN_NUM)
    text = re.sub(r"[\s\-_·:：,，.。/\\()（）\[\]【】「」\"'’“”]+", "", text)
    return text


def name_tokens(name):
    """把名称拆成「去品牌前缀后的归一化文本 + 场次号集合」，用于跨来源匹配。

    场次号只取 3 位以上、且不是通用年份的数字：``Div. 1 / Div. 2`` 这类分区号
    不代表「哪一场」，``2026`` 这类年份几乎所有比赛名里都有，两者都不能用来判定
    「是不是同一场比赛」，否则不同竞赛会被错误合并。
    """
    key = normalize_name(name)
    for prefix in _BRAND_PREFIXES:
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    numbers = tuple(sorted(n for n in re.findall(r"\d+", key)
                           if len(n) >= 3 and n not in _COMMON_NUMBERS))
    return key, numbers


def clamp_score(value, default=3):
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return default


def iso_date(value):
    d = parse_date(value)
    return d.strftime("%Y-%m-%d") if d else ""


def is_reasonable_date(value, *, kind="start", today=None, ref=None):
    """日期合理性校验：拦截明显的脏数据。"""
    d = parse_date(value)
    if not d:
        return False
    today = today or datetime.now().date()
    if kind == "start":
        # 开赛：允许最多早 60 天（刚结束的比赛），最晚不超过 3 年
        return (today - timedelta(days=400)) <= d <= (today + timedelta(days=3 * 365))
    if kind == "end":
        return (today - timedelta(days=400)) <= d <= (today + timedelta(days=3 * 365))
    if kind == "deadline":
        return (today - timedelta(days=365)) <= d <= (today + timedelta(days=2 * 365))
    return True


def clean_dates(item, today=None):
    """清洗日期字段，返回 (start, end, deadline, warnings)。"""
    warnings = []
    start = iso_date(item.get("start_date"))
    end = iso_date(item.get("end_date"))
    deadline = iso_date(item.get("reg_deadline"))
    if start and not is_reasonable_date(start, kind="start", today=today):
        warnings.append(f"开赛日期异常已忽略：{start}")
        start = ""
    if end and not is_reasonable_date(end, kind="end", today=today):
        warnings.append(f"结束日期异常已忽略：{end}")
        end = ""
    if deadline and not is_reasonable_date(deadline, kind="deadline", today=today):
        warnings.append(f"报名截止日期异常已忽略：{deadline}")
        deadline = ""
    if start and end and parse_date(end) < parse_date(start):
        # 结束早于开始：大概率是数据错误，只保留开赛日
        warnings.append(f"结束日期早于开赛日期，已忽略：{end}")
        end = ""
    return start, end, deadline, warnings


def validate_item(item, source_key="crawl"):
    """校验并补全单条抓取数据；不合法返回 None。"""
    name = (item.get("name") or "").strip()
    url = normalize_url(item.get("url"))
    if not name or not url:
        return None
    if hidden_reason(name, url):
        return None  # 非比赛内容（题目集、教程、OJ 练习等）
    tags = item.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (ValueError, TypeError):
            tags = [tags]
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:8]

    start, end, deadline, _warnings = clean_dates(item)
    start_at = (item.get("start_at") or "").strip()[:16]
    end_at = (item.get("end_at") or "").strip()[:16]
    if not start and start_at:  # 只有时间没有日期时从时间串里取日期
        start = start_at[:10]

    desc = (item.get("desc") or "").strip()
    return {
        "name": name[:200],
        "category": (item.get("category") or "其他").strip()[:40],
        "organizer": (item.get("organizer") or "").strip()[:120] or None,
        "start_date": start,
        "end_date": end,
        "reg_deadline": deadline,
        "url": url,
        "desc": desc[:800] or "暂无简介",
        "tags": json.dumps(tags, ensure_ascii=False),
        "source": item.get("source") or source_key,
        "source_id": str(item.get("source_id") or "")[:120],
        "tier": item.get("tier") if item.get("tier") in ("S", "A", "B", "C") else "B",
        "difficulty": clamp_score(item.get("difficulty", 3)),
        "start_at": start_at if start_at[:10] == start else "",
        "end_at": end_at,
        "ratings": (str(item.get("ratings") or "").strip())[:40] or None,
        "phase": (str(item.get("status") or "").strip())[:24] or None,
    }


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------
def _same_event(a_name, a_start, b_name, b_start):
    """名称相差不超过一个「难度/分区」后缀，且开赛日相差不超过 1 天。

    例如「Codeforces Round 900」与「Codeforces Round 900 (Div. 2)」是同一场，
    而「… Round 900」与「… Round 901」不是。

    空名称必须在这里被拒绝：否则两个都取不到场次号的不同比赛会被当成同一场。
    """
    key_a, nums_a = name_tokens(a_name)
    key_b, nums_b = name_tokens(b_name)
    if not key_a or not key_b or nums_a != nums_b:
        return False
    similar = key_a == key_b or key_b.startswith(key_a) or key_a.startswith(key_b)
    if not similar:
        return False
    da, dbb = parse_date(a_start), parse_date(b_start)
    if da and dbb:
        return abs((da - dbb).days) <= 1
    return True


def find_existing(db, item):
    """依次按「来源内 source_id → 归一化 URL → 跨来源同名同日期」找到已有记录。"""
    # 1) source_id：必须限定在**同一来源**内。
    #    不同来源的 ID 空间互相独立（cf-900 与某个站点的 900 是两回事），
    #    不限定来源会把别人的记录误当成自己这条。
    if item.get("source_id"):
        row = db.execute(
            "SELECT * FROM competitions WHERE source_id=? AND source_id<>'' "
            "AND (source=? OR source='crawl' OR source='') LIMIT 1",
            (item["source_id"], item.get("source") or "")).fetchone()
        if row:
            return row
    # 2) 归一化 URL（去掉协议差异/跟踪参数/尾斜杠后精确比较）
    target = item["url"]
    for row in db.execute("SELECT * FROM competitions WHERE url IS NOT NULL AND url<>''"):
        if normalize_url(row["url"]) == target:
            return row
    # 3) 跨来源同名同日期：先粗筛（名称去掉品牌前缀后互为前缀），再精判
    key, numbers = name_tokens(item["name"])
    if not key:
        return None
    candidates = []
    for row in db.execute(
            "SELECT * FROM competitions WHERE name IS NOT NULL AND name<>''"):
        other_key, other_numbers = name_tokens(row["name"])
        # 场次号必须完全一致；两边都没有场次号时也不能跳过这一步判断
        if other_numbers != numbers:
            continue
        if other_key == key or other_key.startswith(key) or key.startswith(other_key):
            candidates.append(row)
    for row in candidates:
        if _same_event(item["name"], item["start_date"], row["name"], row["start_date"]):
            return row
    return None


def _name_quality(name):
    """名称信息量打分：是否带场次号、是否带赞助商/全称、长度。"""
    if not name:
        return 0
    has_number = 1 if re.search(r"\d{3,}", name) else 0
    return has_number * 2 + min(len(name), 120) / 60


def _is_placeholder_source(row, source_key):
    """该行是否是「这个来源自己抓来的占位记录」（没有人工编辑过）。"""
    return (row["source"] == source_key
            and (row["verify_status"] or "auto") == "auto")


def upsert_items(db, items, source=None, today=None):
    """写入抓取结果：跨来源归并、保护人工与内置描述、记录 last_seen。"""
    source_key = getattr(source, "key", None) or "crawl"
    stamp = (today or datetime.now().date()).strftime("%Y-%m-%d")
    added = updated = skipped = merged = 0
    for raw in items:
        item = validate_item(raw, source_key)
        if item is None:
            skipped += 1
            continue
        row = find_existing(db, item)
        if row:
            merged += 1 if row["source"] not in (source_key, "builtin", "manual") else 0
            _update_row(db, row, item, source_key, stamp)
            updated += 1
        else:
            _insert_row(db, item, source_key, stamp)
            added += 1
    return added, updated, skipped


def _update_row(db, row, item, source_key, stamp):
    """更新已有记录：人工/内置内容优先，机器内容只在更完整时才覆盖。"""
    same_source = row["source"] == source_key
    manual_like = (row["source"] in ("manual", "builtin")
                   or (row["verify_status"] or "") == "verified")
    # 名称：同来源或占位记录可更新；跨来源只在「信息量明显更高」时更新
    name = row["name"]
    if same_source or _is_placeholder_source(row, source_key):
        name = item["name"]
    elif _name_quality(item["name"]) > _name_quality(row["name"]) + 0.5:
        name = item["name"]
    # 描述：人工/内置描述永不被机器覆盖；机器描述只允许同来源刷新
    desc = row["desc"]
    if same_source and not manual_like:
        desc = item["desc"]
    elif not (row["desc"] or "").strip():
        desc = item["desc"]
    # 日期：有值的机器数据可以覆盖（赛程变化需要及时更新），但不允许清空
    start = item["start_date"] or row["start_date"] or ""
    end = item["end_date"] or row["end_date"] or ""
    deadline = item["reg_deadline"] or row["reg_deadline"] or ""
    organizer = item["organizer"] or row["organizer"]
    url = item["url"] or row["url"]
    # tags：合并双方，人工标签保留
    tags = _merge_tags(row["tags"], item["tags"])
    # 来源归属：
    #   * 人工 / 内置行的来源标记从不被机器改写；
    #   * 同来源 → 刷新；
    #   * 无来源 / 历史遗留的 'crawl' → 由已知来源认领（这样它才能被后续同步更新、
    #     也才会参与「消失后自动隐藏」）；
    #   * 其它已知来源的记录（跨来源归并命中）→ 保留原归属，不抢夺。
    if row["source"] in ("manual", "builtin"):
        source = row["source"]
    elif same_source or not row["source"] or row["source"] == "crawl":
        source = source_key
    else:
        source = row["source"]
    claims_source_id = source == source_key and item["source_id"] and (
        same_source or not row["source_id"] or row["source"] == "crawl")
    source_id = item["source_id"] if claims_source_id else row["source_id"]
    db.execute(
        "UPDATE competitions SET name=?, start_date=?, end_date=?, reg_deadline=?, "
        "url=?, desc=?, tags=?, organizer=?, source_id=?, source=?, "
        "start_at=?, end_at=?, ratings=?, phase=?, "
        "last_seen=?, last_checked=?, info_updated=?, missing_since=NULL "
        "WHERE id=?",
        (name, start, end, deadline, url, desc, tags, organizer, source_id, source,
         item["start_at"], item["end_at"], item["ratings"], item["phase"],
         stamp, stamp, stamp, row["id"]))
    if not manual_like:
        db.execute(
            "UPDATE competitions SET tier=?, s_difficulty=? WHERE id=?",
            (item["tier"], item["difficulty"], row["id"]))


def _insert_row(db, item, source_key, stamp):
    db.execute(
        "INSERT INTO competitions(name,category,organizer,start_date,end_date,"
        "reg_deadline,url,desc,tags,source,source_id,tier,s_difficulty,s_history,"
        "s_policy,s_industry,verify_status,start_at,end_at,ratings,phase,"
        "last_checked,info_updated,first_seen,last_seen) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item["name"], item["category"], item["organizer"], item["start_date"],
         item["end_date"], item["reg_deadline"], item["url"], item["desc"],
         item["tags"], item["source"], item["source_id"], item["tier"],
         item["difficulty"], 4, 1, 4, "auto", item["start_at"], item["end_at"],
         item["ratings"], item["phase"], stamp, stamp, stamp, stamp))


def _merge_tags(existing, incoming):
    try:
        old = json.loads(existing or "[]")
        if not isinstance(old, list):
            old = []
    except (ValueError, TypeError):
        old = []
    if isinstance(incoming, str):
        try:
            new = json.loads(incoming)
        except (ValueError, TypeError):
            new = []
    else:
        new = list(incoming or [])
    merged = []
    for tag in list(old) + list(new):
        tag = str(tag).strip()
        if tag and tag not in merged:
            merged.append(tag)
    return json.dumps(merged[:8], ensure_ascii=False)


def mark_verified(db, comp_id):
    db.execute("UPDATE competitions SET verify_status='verified', "
               "info_updated=date('now','localtime'), last_checked=date('now','localtime') "
               "WHERE id=?", (comp_id,))
    db.commit()


def staleness_days(info_updated):
    d = parse_date(info_updated)
    return (datetime.now().date() - d).days if d else None
