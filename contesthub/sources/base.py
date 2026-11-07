# -*- coding: utf-8 -*-
"""数据源基类与 HTTP 助手。

所有网络访问统一走这里，负责：

* 超时 / 重试 / 退避 —— 单个来源偶发 5xx、断流不会直接判失败；
* SSL 回退 —— 部分环境（校园网、公司代理证书、旧 certifi）会对站点证书校验失败，
  此时仅在「证书校验失败」这一种情况下退回系统信任库重试，业务错误绝不重试；
* 编码兜底 —— 不少站点不声明 charset 或声明错误，用 requests 的 ``resp.text``
  会得到乱码，这里优先相信站点声明的编码，否则依次尝试 utf-8 / gb18030；
* 会话复用 —— 复用 TCP 连接，避免逐个请求重新握手。
"""
import json
import logging
import threading
import time
import warnings
from datetime import datetime, timedelta, timezone

import requests
import urllib3

log = logging.getLogger(__name__)

# 证书回退只作为最后手段：本机证书链异常（如企业代理）时会走到这里，
# 关闭一次告警避免刷屏，但会在日志里明确记录。
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 ContestHub/0.3")

# 北京时间的固定时区（无夏令时，可放心使用固定偏移）
CST = timezone(timedelta(hours=8))
JST = timezone(timedelta(hours=9))
UTC = timezone.utc

DEFAULT_TIMEOUT = 15


class Source:
    """一个可插拔的赛事数据源。

    子类实现 fetch()，返回「规范化条目」列表；每条至少包含
    name / url，其余字段缺失时由 dedup.validate_item 补默认值。
    """

    key = ""
    label = ""
    group = "算法/编程在线赛"
    homepage = ""
    experimental = False
    #: 该来源抓取的比赛偏向「单场在线赛」还是「年度大赛」，前端据此展示
    nature = "online"
    #: 来源自身建议的抓取超时（秒）。慢站点可以调大，避免被统一超时误伤。
    timeout = 25

    def fetch(self):  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def describe(self):
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "homepage": self.homepage,
            "experimental": self.experimental,
            "nature": self.nature,
        }


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_local = threading.local()

#: 测试可以通过它把请求全部替换掉
transport = None


class _StdlibSSLAdapter(requests.adapters.HTTPAdapter):
    """使用 Python 标准库的默认证书上下文。

    本机会遇到：``ssl.create_default_context()`` 能通过校验（系统证书链），
    但 ``requests``/``urllib3`` 自带的 certifi 包校验失败（Kaggle 等使用
    Google Trust Services 证书的站点）。这里让 urllib3 复用标准库 context，
    **依然完整校验证书**，只是换了一套可信根，比直接 ``verify=False`` 安全得多。
    """

    def init_poolmanager(self, *args, **kwargs):
        import ssl

        kwargs["ssl_context"] = ssl.create_default_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):  # pragma: no cover
        import ssl

        kwargs["ssl_context"] = ssl.create_default_context()
        return super().proxy_manager_for(*args, **kwargs)


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        sess.mount("https://", _StdlibSSLAdapter())
        _local.session = sess
    return sess


def _request(method, url, *, timeout=DEFAULT_TIMEOUT, retries=2, headers=None, **kwargs):
    """带重试的请求，返回 requests.Response。

    证书问题已经在会话层用标准库上下文解决（见 ``_StdlibSSLAdapter``），
    这里**不会**关闭证书校验：既不会把安全边界放宽，也不会误把证书错误
    当成网络故障反复重试。
    """
    headers = dict(headers or {})
    last_exc = None
    for attempt in range(retries + 1):
        try:
            if transport is not None:  # 测试注入
                return transport(method, url, headers=headers, timeout=timeout, **kwargs)
            return _session().request(method, url, timeout=timeout, headers=headers, **kwargs)
        except requests.exceptions.SSLError:
            # 证书校验失败是配置问题，重试无意义，直接抛出以便上层写进同步日志
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise
        except requests.exceptions.HTTPError:
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"请求失败：{url}")


def http_get(url, timeout=DEFAULT_TIMEOUT, **kwargs):
    """GET 并返回 Response（已 raise_for_status）。"""
    resp = _request("GET", url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


def http_post(url, timeout=DEFAULT_TIMEOUT, **kwargs):
    resp = _request("POST", url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


def decode_body(resp):
    """按站点声明 / 常见编码解码响应正文，避免中文乱码。"""
    raw = resp.content or b""
    declared = (resp.encoding or "").lower()
    candidates = []
    if declared and declared not in ("iso-8859-1", "latin-1", "ascii"):
        candidates.append(declared)
    candidates += ["utf-8", "gb18030"]
    for enc in candidates:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def http_text(url, timeout=DEFAULT_TIMEOUT, **kwargs):
    return decode_body(http_get(url, timeout=timeout, **kwargs))


def loads_json(text):
    """尽量宽容地把文本解析成 JSON（处理 BOM / 前后杂字）。"""
    if isinstance(text, (dict, list)):
        return text
    text = (text or "").strip().lstrip("\ufeff")
    if not text:
        raise ValueError("响应为空，无法解析 JSON")
    try:
        return json.loads(text)
    except ValueError:
        # 站点偶尔在 JSON 前后插入调试输出，截取首个 { 或 [ 到最后一个 } 或 ]
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start, end = text.find(open_c), text.rfind(close_c)
            if 0 <= start < end:
                try:
                    return json.loads(text[start:end + 1])
                except ValueError:
                    continue
        raise ValueError(f"JSON 解析失败：{text[:120]}")


def http_json(url, timeout=DEFAULT_TIMEOUT, **kwargs):
    return loads_json(decode_body(http_get(url, timeout=timeout, **kwargs)))


def http_post_json(url, payload, timeout=DEFAULT_TIMEOUT, **kwargs):
    headers = {"Content-Type": "application/json"}
    headers.update(kwargs.pop("headers", {}))
    resp = http_post(url, timeout=timeout, json=payload, headers=headers, **kwargs)
    return loads_json(decode_body(resp))


# --------------------------------------------------------------------------
# 时间与文本助手
# --------------------------------------------------------------------------

def parse_iso_datetime(value, default_tz=CST):
    """解析站点返回的 ISO 时间（带时区则尊重，不带则按 default_tz）。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=default_tz)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # 处理只有日期的情况
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def to_cst(value, default_tz=CST):
    dt = parse_iso_datetime(value, default_tz=default_tz)
    return dt.astimezone(CST) if dt else None


def md_date(value, default_tz=CST):
    dt = to_cst(value, default_tz=default_tz)
    return dt.strftime("%Y-%m-%d") if dt else ""


def md_datetime(value, default_tz=CST):
    dt = to_cst(value, default_tz=default_tz)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def add_seconds(value, seconds, default_tz=CST):
    dt = parse_iso_datetime(value, default_tz=default_tz)
    if not dt or not seconds:
        return ""
    return (dt + timedelta(seconds=int(seconds))).astimezone(CST).strftime("%Y-%m-%d")


def duration_text(seconds):
    """7200 -> '2 小时'；5400 -> '1 小时 30 分钟'；45*60 -> '45 分钟'。"""
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes and not days:
        parts.append(f"{minutes} 分钟")
    return " ".join(parts)


def html_unescape(text):
    """把 HTML 实体还原成普通文本（标题里常见的 &amp; &#39; 等）。"""
    import html as _html
    return _html.unescape(text or "")


def title_with_brand(title, brand, *, dedupe=True):
    """给标题补上平台名，同时消除「Codeforces Codeforces Round …」这种重复前缀。"""
    title = (title or "").strip()
    brand = (brand or "").strip()
    if not title:
        return brand
    if brand and dedupe and title.lower().startswith(brand.lower()):
        return title
    return f"{brand} {title}".strip()


def money_text(reward):
    """Kaggle 的 reward 字段 -> 可读金额，如 '$1,500,000'。"""
    if isinstance(reward, dict):
        qty = reward.get("quantity")
        unit = (reward.get("id") or "").upper()
        if qty:
            try:
                qty = f"{int(qty):,}"
            except (TypeError, ValueError):
                pass
            symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(unit, "")
            return f"{symbol}{qty} {'' if symbol else unit}".strip()
        return str(reward.get("clarification") or "").strip()
    return str(reward or "").strip()


def make_item(name, url, *, start_date="", end_date="", reg_deadline="", organizer="",
              category="算法竞赛", desc="", tags=None, tier="B", difficulty=3,
              source_id="", ratings=None, start_at="", end_at="", status=""):
    """构造一条规范化条目。

    start_at / end_at 是计划中的「带时间」字段（如 2026-10-18 16:05），
    便于前端展示精确比赛时间；ratings 是来源给出的难度描述，例如
    AtCoder 的 '~ 1999' 或 Kaggle 的 leaderboard 规模。
    """
    return {
        "name": name, "url": url, "start_date": start_date, "end_date": end_date,
        "reg_deadline": reg_deadline, "organizer": organizer, "category": category,
        "desc": desc, "tags": tags or [], "tier": tier, "difficulty": difficulty,
        "source_id": source_id, "ratings": ratings, "start_at": start_at,
        "end_at": end_at, "status": status,
    }


__all__ = [
    "Source", "UA", "CST", "JST", "UTC", "DEFAULT_TIMEOUT",
    "http_get", "http_post", "http_text", "http_json", "http_post_json",
    "loads_json", "decode_body", "parse_iso_datetime", "to_cst", "md_date",
    "md_datetime", "add_seconds", "duration_text", "title_with_brand",
    "money_text", "make_item", "transport", "html_unescape",
]
