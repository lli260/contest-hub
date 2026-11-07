# -*- coding: utf-8 -*-
"""天池大赛（阿里云）：首页只有轮播图，列表接口带 CSRF，无法自动抓取。

实测（2026-10）：

* ``https://tianchi.aliyun.com/competition/activeList`` 服务端渲染出的只有
  9 个轮播图入口，``<a>`` 里是 ``<img>``，**没有比赛名称、没有日期**；
* ``/api/competition/listCompetitions`` POST 直接返回
  ``403 code: EBADCSRFTOKEN``。

旧实现从轮播图提取不到名称就返回空列表，日志却显示同步成功，
同样属于「假成功」。现在改为明确声明不可用，只保留官网入口。
"""
import re

from .base import Source, http_text

HOME_URL = "https://tianchi.aliyun.com/competition/activeList"


class SourceUnavailable(RuntimeError):
    """来源明确不可自动抓取（反爬 / 需登录），不是临时网络错误。"""


class TianchiSource(Source):
    key = "tianchi"
    label = "天池大赛（阿里云）"
    group = "官网入口（不可自动抓取）"
    homepage = "https://tianchi.aliyun.com/competition/activeList"
    experimental = True
    nature = "long"

    def fetch(self):
        raise SourceUnavailable(
            "天池赛程由前端异步加载，接口需 CSRF 校验，服务端页面无赛程数据；"
            "请在官网「赛事」页查看")

    def check(self):
        html = http_text(HOME_URL, timeout=15)
        entrances = sorted(set(re.findall(r"/competition/entrance/(\d+)", html or "")))
        if entrances:
            return {"ok": True,
                    "detail": f"官网可访问，首页轮播含 {len(entrances)} 个赛事入口（无名称/日期，需人工查看）"}
        return {"ok": True, "detail": "官网可访问，但未发现赛程数据"}
