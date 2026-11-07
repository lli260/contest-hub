# -*- coding: utf-8 -*-
"""内容过滤：剔除「不是比赛」的条目。

在线题库（洛谷 / 牛客 / 蓝桥云课 / LeetCode 等）的列表页里混着题目集、
课程、题解、练习赛模板等内容。旧实现只按「有没有名称和链接」判断，
于是会把这些内容也当成比赛写进库，造成信息噪声。这里按标题与 URL
规则做黑名单过滤，同时保留明显的比赛关键词。
"""
import re

# 标题里出现这些词，基本可以判定不是一场可报名的比赛
_DENY_WORDS = (
    "题解", "题库", "课程", "教程", "学习路径", "面经", "面试题", "笔试题",
    "oj 练习", "oj练习", "题单", "训练营", "系列课", "视频课", "作业",
    "习题", "选择题", "填空题", "答案", "解析", "文档", "公告", "通知",
    "帮助中心", "用户协议", "隐私政策",
)

# URL 特征：题目详情、题解、课程、文章等
_DENY_URL = (
    r"/problem/", r"/problems/", r"/solution", r"/course/", r"/courses/",
    r"/article/", r"/post/", r"/discuss", r"/question/", r"/training/",
    r"/learn/", r"/tutorial", r"/practice/", r"/challenge(s)?/\d+/",
    r"/wiki/", r"/help", r"/faq", r"/about", r"/login", r"/register",
)

# 带这些词的标题一定保留（避免误杀「第二届…比赛」被 deny 规则命中）
_ALLOW_WORDS = ("比赛", "竞赛", "大赛", "contest", "round", "开始", "challenge")

_DENY_TITLE_RE = re.compile("|".join(re.escape(w) for w in _DENY_WORDS), re.I)
_DENY_URL_RE = re.compile("|".join(_DENY_URL), re.I)


def hidden_reason(name, url):
    """返回被过滤的原因；None 表示保留。

    判定顺序很重要：先看「明确是比赛」的标题（例如「…比赛题解合集」仍属于题库
    内容，需要拦下），再用黑名单规则，最后才用「含比赛关键词则放行」兜底。
    """
    name = (name or "").strip()
    url = (url or "").strip()
    if not name or len(name) < 2:
        return "名称过短"
    lowered = name.lower()
    # 先排除「本身就是一场比赛」的标题：在线赛名称里常带「题解已发布」「赛后题解」等后缀
    is_contest_title = (bool(re.search(r"round\s*\d|第\s*\d+\s*场|contest\s*\d", lowered))
                        or "比赛" in lowered and "合集" not in lowered
                        or "竞赛" in lowered or "大赛" in lowered)
    # 「比赛」「contest」本身不足以证明是比赛通知：带题库/题解/课程字样优先拦下
    strong_deny = ("题解", "题库", "题单", "课程", "教程", "讲解", "面经",
                   "面试题", "笔试题", "答案解析")
    if any(word in lowered for word in strong_deny):
        if is_contest_title and not re.search(r"合集|库|课程|教程", lowered):
            return None
        return "非比赛内容（题库/课程/题解等）"
    if url and _DENY_URL_RE.search(url):
        return "非比赛页面（题目/课程/文章）"
    if any(word in lowered for word in _ALLOW_WORDS):
        return None
    if _DENY_TITLE_RE.search(name):
        return "非比赛内容（题库/课程/题解等）"
    return None
