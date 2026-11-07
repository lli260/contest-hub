# -*- coding: utf-8 -*-
"""数据源注册表。新增来源只需在 _SOURCES 中登记即可。"""
from .atcoder import AtCoderSource
from .base import Source
from .codechef import CodeChefSource
from .codeforces import CodeforcesSource
from .kaggle import KaggleSource
from .lanqiao import LanqiaoSource
from .leetcode import LeetCodeSource
from .luogu import LuoguSource
from .moe import MoeWhitelistSource
from .nowcoder import NowCoderSource
from .tianchi import TianchiSource

_SOURCES = [
    # 算法/编程在线赛：官方 JSON 接口或可稳定解析的列表页
    CodeforcesSource(),
    AtCoderSource(),
    LeetCodeSource(),
    CodeChefSource(),
    LuoguSource(),
    # 数据科学平台
    KaggleSource(),
    # 蓝桥杯 / 校赛平台
    LanqiaoSource(),
    # 教育部白名单（大学生竞赛目录 84 项）
    MoeWhitelistSource(),
    # 反爬 / 前端渲染，只能做官网入口 + 自动可达性检测
    NowCoderSource(),
    TianchiSource(),
]

BY_KEY = {s.key: s for s in _SOURCES}

#: 分组展示顺序
GROUP_ORDER = ["算法/编程在线赛", "数据科学平台", "蓝桥杯 & 校赛平台",
               "教育部白名单", "官网入口（不可自动抓取）"]


def all_sources():
    return list(_SOURCES)


def live_sources():
    """能真正产出赛程的来源（排除只做入口的来源）。"""
    return [s for s in _SOURCES if not s.experimental]


def get_source(key):
    return BY_KEY.get(key)


def describe_all():
    return [s.describe() for s in _SOURCES]


def describe_groups():
    """按分组整理来源，模板直接遍历即可。"""
    groups = {g: [] for g in GROUP_ORDER}
    for s in _SOURCES:
        groups.setdefault(s.group, []).append(s.describe())
    return [(g, items) for g, items in groups.items() if items]
