# -*- coding: utf-8 -*-
"""牛客 NowCoder：反爬拦截，只能保证「官网入口可用」+ 可达性检测。

实测（2026-10）：``https://ac.nowcoder.com/acm/contest/vip`` 对非登录用户
返回 10 KB 的通用登录壳页面，``/api/...`` 接口同样被重定向到该页面，
所以**没有任何服务端渲染的赛程数据**可解析。旧实现假装抓取成功
（同步日志显示「✅ 成功 0 条」），会让人误以为同步正常。

现在的行为：

* ``fetch()`` 直接抛 ``SourceUnavailable``，同步日志里明确写「该站反爬，
  无法自动抓取，请在官网查看」，不再伪装成功；
* ``check()`` 至少探测官网可达性，给出「入口可用 / 打不开」的真实结论。
"""
import re

from .base import Source, http_text

LIST_URL = "https://ac.nowcoder.com/acm/contest/vip"
HOME_URL = "https://www.nowcoder.com/"

# 典型拦截页特征（登录壳 / 滑块 / 空壳 SPA）
_BLOCK_MARKERS = ("isLogin = false", "请登录", "登录后查看", "验证码", "滑动验证")


class SourceUnavailable(RuntimeError):
    """来源明确不可自动抓取（反爬 / 需登录），不是临时网络错误。"""


class NowCoderSource(Source):
    key = "nowcoder"
    label = "牛客 NowCoder"
    group = "官网入口（不可自动抓取）"
    homepage = "https://ac.nowcoder.com/acm/contest/vip"
    experimental = True
    nature = "online"

    def fetch(self):
        raise SourceUnavailable(
            "牛客竞赛列表为前端渲染 + 登录态校验，服务端无赛程数据可抓取；"
            "请在官网/App 查看最新场次")

    def check(self):
        """只做可达性检测，不产出数据。"""
        html = http_text(LIST_URL, timeout=15)
        blocked = any(marker in html for marker in _BLOCK_MARKERS)
        has_links = bool(re.search(r"/acm/contest/\d+", html))
        if has_links:
            return {"ok": True, "detail": f"页面含 {len(re.findall(r'/acm/contest/\\d+', html))} 个比赛链接"}
        if blocked:
            return {"ok": True, "detail": "官网可访问，但列表由前端渲染/需登录（反爬），无法自动抓取"}
        return {"ok": True, "detail": "官网可访问，未发现服务端赛程数据"}
