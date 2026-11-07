# -*- coding: utf-8 -*-
"""集中配置：路径、同步周期、缓存、过期阈值。均可用环境变量覆盖。"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 包内目录：templates / static 随包一起走，部署时不用额外指定路径
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(PACKAGE_DIR, "templates")
STATIC_DIR = os.path.join(PACKAGE_DIR, "static")
DEFAULT_DB_PATH = os.environ.get("CONTESTHUB_DB", os.path.join(BASE_DIR, "contest.db"))

# 后台自动同步周期（小时）
SYNC_INTERVAL_HOURS = float(os.environ.get("CONTESTHUB_SYNC_HOURS", "3"))
# 首次启动后延迟多少秒执行第一次后台同步（避免启动瞬间打满）
SYNC_INITIAL_DELAY = float(os.environ.get("CONTESTHUB_SYNC_DELAY", "8"))
# 抓取结果内存缓存时长（秒），避免频繁请求同一数据源
CACHE_TTL_SECONDS = int(os.environ.get("CONTESTHUB_CACHE_TTL", str(30 * 60)))
# 超过多少天未核实标记「可能过期」
STALE_DAYS = int(os.environ.get("CONTESTHUB_STALE_DAYS", "60"))
# 来源里消失多少天后隐藏该比赛（在线赛会自然消失）
VANISH_HIDE_DAYS = int(os.environ.get("CONTESTHUB_VANISH_DAYS", "3"))
# 整轮同步的硬超时（秒）：某个来源卡死也不会拖住整次同步
SOURCE_TIMEOUT_SECONDS = float(os.environ.get("CONTESTHUB_TIMEOUT", "60"))
# 并行抓取的并发数
MAX_PARALLEL = int(os.environ.get("CONTESTHUB_PARALLEL", "6"))
# 关闭后台自动同步（测试/调试用）
DISABLE_BG_SYNC = os.environ.get("CONTESTHUB_DISABLE_BG") == "1"
