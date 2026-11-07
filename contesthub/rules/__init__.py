# -*- coding: utf-8 -*-
"""领域规则层：与「数据怎么存」无关的纯逻辑。

* ``rating``     —— 五维含金量评级、比赛状态判定、展示字段
* ``dedup``      —— 归一化、字段校验、跨来源实体归并、来源归属保护
* ``moderation`` —— 过滤不是比赛的内容（题库/课程/题解）
"""
from .dedup import (find_existing, mark_verified, normalize_name,
                    normalize_url, upsert_items, validate_item)
from .rating import (DIMENSIONS, STATUS_CHOICES, STATUS_STYLE, TIER_WEIGHTS,
                     calc_level, compute_status, enrich, enrich_all, parse_date,
                     parse_datetime)

__all__ = [
    "find_existing", "mark_verified", "normalize_name", "normalize_url",
    "upsert_items", "validate_item",
    "DIMENSIONS", "STATUS_CHOICES", "STATUS_STYLE", "TIER_WEIGHTS",
    "calc_level", "compute_status", "enrich", "enrich_all", "parse_date",
    "parse_datetime",
]
