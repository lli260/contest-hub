# -*- coding: utf-8 -*-
"""联网冒烟测试（默认跳过）。

验证「真实站点现在还能抓到数据」——每次来源改版都可能导致解析器失效，
这类问题离线 fixture 测不出来。运行方式：

    set CONTESTHUB_LIVE=1 && uv run pytest tests/test_live.py -v

注意：需要能访问 Codeforces / AtCoder / LeetCode / 洛谷 / Kaggle 等站点。
"""
import os
import time

import pytest

from contesthub.sources import (atcoder, codechef, codeforces, kaggle, lanqiao,
                                leetcode, luogu)

pytestmark = pytest.mark.skipif(
    os.environ.get("CONTESTHUB_LIVE") != "1",
    reason="联网测试默认跳过，设置 CONTESTHUB_LIVE=1 开启")

LIVE_SOURCES = [
    (codeforces.CodeforcesSource, 1),
    (atcoder.AtCoderSource, 1),
    (leetcode.LeetCodeSource, 1),
    (codechef.CodeChefSource, 1),
    (luogu.LuoguSource, 1),
    (kaggle.KaggleSource, 1),
    (lanqiao.LanqiaoSource, 0),   # 可能确实没有进行中的赛事
]


@pytest.mark.parametrize("source_cls,min_items", LIVE_SOURCES,
                         ids=[s.__name__ for s, _ in LIVE_SOURCES])
def test_live_source_returns_usable_items(source_cls, min_items):
    items = source_cls().fetch()
    assert len(items) >= min_items, f"{source_cls.__name__} 抓取到 {len(items)} 条"
    now = time.time()
    for item in items:
        assert item["name"].strip()
        assert item["url"].startswith("http")
        # 同一来源内部不应出现重复 URL（曾经出过全部指向同一个链接的 bug）
    urls = [i["url"] for i in items]
    assert len(urls) == len(set(urls)), f"{source_cls.__name__} 出现重复 URL"
    # 未来的比赛时间要合理（不要出现 1970 或 2100 这种）
    for item in items:
        if item["start_at"]:
            year = int(item["start_at"][:4])
            assert 2020 <= year <= 2100


def test_live_full_sync_isolates_failures(tmp_path):
    """整轮同步：任何单个来源失败都不应影响其它来源。"""
    from contesthub import sync
    from contesthub.db import connect, init_db

    path = str(tmp_path / "live.db")
    init_db(path)
    db = connect(path)
    try:
        results = sync.run_sync(db, None, use_cache=False)
    finally:
        db.close()
    assert len(results) >= 5
    ok = [r for r in results if r["ok"]]
    assert len(ok) >= 4, "多数来源应能成功抓取"
    total = sum(r["added"] for r in ok)
    assert total > 0, "同步结果不应为空"
