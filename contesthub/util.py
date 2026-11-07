# -*- coding: utf-8 -*-
"""通用工具：日期差、自动重点生成。"""
from datetime import datetime

from .rules.rating import calc_level, parse_date


def days_until(date_str):
    d = parse_date(date_str)
    return (d - datetime.now().date()).days if d else None


def auto_keypoints(comp):
    """根据比赛信息自动生成备赛重点（用于笔记页）。"""
    pts = []
    dl = days_until(comp.get("reg_deadline"))
    st = days_until(comp.get("start_date"))
    has_dates = bool(comp.get("start_date") or comp.get("reg_deadline"))
    if dl is not None:
        pts.append(f"⏰ 距报名截止还有 {dl} 天（{comp['reg_deadline']}），务必提前注册！"
                   if dl >= 0 else "❌ 本届报名已截止，请关注下一届通知。")
    elif has_dates:
        pts.append("ℹ️ 官网未公布明确的报名截止日期，建议每周查看一次官网通知，或校内教务/协会公告。")
    else:
        pts.append("ℹ️ 官网尚未公布本年度赛程，本平台已记录入口；建议关注官网公告或校内通知，"
                   "公布后可回本页「标记为已核实」。")
    if st is not None and st >= 0:
        when = comp.get("when_text") or comp.get("start_date")
        pts.append(f"🏁 距开赛约 {st} 天（{when}），建议倒推制定训练计划。")
    if comp.get("duration_text"):
        pts.append(f"⏱️ 单场时长约 {comp['duration_text']}。")
    if comp.get("ratings"):
        pts.append(f"📈 来源给出的难度/规模：{comp['ratings']}。")
    lv = calc_level(comp["tier"], comp["s_difficulty"], comp["s_history"],
                    comp["s_policy"], comp["s_industry"])
    pts.append(f"⭐ 综合含金量 {'★' * lv}{'☆' * (5 - lv)}（主办方级别 {comp['tier']} 级）")
    pts.append(f"🏛️ 主办方：{comp['organizer'] or '未知'}")
    if comp.get("verify_status") == "verified":
        pts.append("✅ 该赛事信息已人工核实。")
    elif comp.get("verify_status") == "manual":
        pts.append("⚠️ 该赛事日期为人工整理的参考值，请以官网通知为准（可在本页标记「已核实」）。")
    elif comp.get("stale"):
        age = comp.get("data_age_days")
        pts.append(f"⚠️ 信息已 {age} 天未核实，日期可能有变，请以官网为准。")
    tips = {
        "算法竞赛": ["刷 Codeforces/AtCoder 保持手感与 rating", "组队磨合分工", "整理常用模板库"],
        "程序设计": ["刷历年真题", "熟悉比赛语言与环境", "掌握常见数据结构模板"],
        "数学建模": ["准备常用模型库", "练习 LaTeX 排版", "明确建模/编程/写作分工"],
        "网络安全": ["搭建靶场环境", "刷历史 CTF 题（BUUCTF / 攻防世界）", "整理 CTF 工具箱"],
        "数据科学": ["复现往届 Top 方案", "积累特征工程技巧", "尽早组队并熟悉平台提交流程"],
        "创新创业": ["打磨商业计划书 BP", "准备路演 PPT", "补充专利/软著支撑"],
        "综合创新": ["确定赛道选题尽早启动", "完善文档与演示视频"],
        "嵌入式硬件": ["备好器件与开发板", "练习历年真题", "强化 PCB 与调试"],
    }
    for t in tips.get(comp["category"], ["研读官方规则", "制定每日备赛表"]):
        pts.append("💡 " + t)
    pts.append("🔗 官方入口：" + (comp.get("url") or "暂无"))
    return pts
