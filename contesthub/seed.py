# -*- coding: utf-8 -*-
"""内置赛事数据。

设计原则（针对「信息不准确」）：

* **凡没把握的日期一律留空**，并在描述里写明「官网未公布 / 以官网通知为准」，
  由状态判定显示为「日期待定」，而不是随便编一个日期造成误导；
* **可算准的日期直接写死**：例如全国大学生数学建模竞赛固定在每年 9 月中上旬
  的周四到周日（2026 年为 9 月 10–13 日，2027 年为 9 月 9–12 日），
  美赛固定在每年 2 月上旬；
* 每条都带 `verified=False`（日期为推算）或 `verified=True`（日期已确认），
  页面会显示「日期待核实」提示，用户也可以在详情页一键标记「已核实」。

同时维护一批**精选入口**（curated）：无法自动抓取赛程的官网（牛客、天池、
CCPC、挑战杯等）仍收录为常驻入口，官网链接可用，备注里提示去官网看最新通知；
这些入口若被自动来源抓到了真实场次，会被自动并入同一条记录，不再重复。
"""
import datetime
import json

BUILTIN = [
    # ---------------- 顶级团队算法赛 ----------------
    dict(name="ICPC 国际大学生程序设计竞赛（区域赛）", category="算法竞赛",
         organizer="ICPC 基金会 / 各赛区承办高校", url="https://icpc.global/",
         start_date="", end_date="", reg_deadline="",
         desc="全球影响力最大的大学生团队算法赛事（三人一队、一台机器），区域赛金牌是算法能力的顶级背书。"
              "亚洲区各赛区由承办高校轮流举办，每年 9–12 月为区域赛期，赛程与报名入口以 ICPC 官网和各赛区通知为准。",
         tags=["团队赛", "算法", "内推直通车"], tier="S",
         scores=(5, 5, 5, 5), verified=False),
    dict(name="CCPC 中国大学生程序设计竞赛（分站赛 & 总决赛）", category="算法竞赛",
         organizer="中国大学生程序设计竞赛组委会（CCPC）", url="https://ccpc.io/",
         start_date="", end_date="", reg_deadline="",
         desc="国内最高水平的大学生程序设计团队赛事，由 CCPC 组委会主办，各高校轮流承办分站赛（常含网络预选赛）"
              "与年度总决赛。赛程、网络赛报名时间每个赛季单独发布，请以 CCPC 官网公告为准。"
              "（旧版本内置数据曾误写「第 11 届总决赛已于 2026 年 4 月举办」，该届次与日期均无依据，已更正。）",
         tags=["团队赛", "算法", "保研加分"], tier="S",
         scores=(5, 4, 5, 5), verified=False),
    dict(name="蓝桥杯全国软件和信息技术专业人才大赛（省赛 → 国赛）", category="程序设计",
         organizer="工业和信息化部人才交流中心", url="https://dasai.lanqiao.cn/",
         start_date="", end_date="", reg_deadline="",
         desc="国内参赛规模最大的 IT 学科竞赛之一，分研究生组/大学 A 组/大学 B 组等赛道，校内选拔 → 省赛 → 国赛三级晋级，"
              "含软件、电子、AI、Web 等多个科目。每年下半年启动报名、次年春季省赛、夏季国赛，具体时间见官网赛程通知。",
         tags=["算法", "个人赛", "综测加分"], tier="A",
         scores=(3, 4, 4, 4), verified=False),
    # ---------------- 数学建模 ----------------
    dict(name="全国大学生数学建模竞赛 CUMCM", category="数学建模",
         organizer="中国工业与应用数学学会（CSIAM）", url="https://www.mcm.edu.cn/",
         start_date="2026-09-10", end_date="2026-09-13", reg_deadline="",
         desc="高教社杯，全国规模最大的学科竞赛之一，三人一队、连续 72 小时完成建模与论文，国奖在保研/综测中权重很高。"
              "比赛固定在每年 9 月中上旬的周四晚至周日晚（2026 年为 9 月 10 日 18:00 至 9 月 13 日 20:00）；"
              "报名由各校教务/数模协会统一组织，校内截止日期通常早于开赛 2–4 周。2026 届已于 9 月 13 日结束，"
              "2027 届预计在 2027 年 9 月中旬举办，具体日期以官网通知为准。",
         tags=["团队赛", "建模", "保研硬通货"], tier="S",
         scores=(5, 5, 5, 5), verified=True),
    dict(name="美国大学生数学建模竞赛 MCM/ICM（美赛）", category="数学建模",
         organizer="COMAP（美国数学及其应用联合会）", url="https://www.comap.com/contests/mcm-icm",
         start_date="2027-02-05", end_date="2027-02-09", reg_deadline="2027-01-29",
         desc="全球最著名的国际数学建模赛事，英文论文，O 奖/F 奖对留学申请极具分量。"
              "每年 2 月上旬固定开赛（2026 年为 1 月 30 日–2 月 3 日，2027 年按惯例推至 2 月 5 日前后），"
              "报名通常在开赛前 1–2 周截止，具体以 COMAP 官网倒计时为准。",
         tags=["团队赛", "英文论文", "留学"], tier="B",
         scores=(4, 5, 4, 4), verified=False),
    # ---------------- 网络安全 ----------------
    dict(name="全国大学生信息安全竞赛 CISCN（创新实践能力赛）", category="网络安全",
         organizer="教育部高等学校网络空间安全专业教学指导委员会", url="https://www.ciscn.cn/",
         start_date="", end_date="", reg_deadline="",
         desc="网安领域国家级最高赛事（CTF 方向），分初赛、半决赛、总决赛三级，入选全国普通高校大学生竞赛排行榜，保研加分力度大。"
              "每年报名与赛程由官网通知发布，通常在 4–8 月间进行。",
         tags=["CTF", "团队赛", "保研加分"], tier="S",
         scores=(4, 4, 5, 5), verified=False),
    dict(name="强网杯全国网络安全挑战赛", category="网络安全",
         organizer="网络空间安全人才发展基金 / 信息工程大学等", url="https://www.qiangwangbei.com/",
         start_date="", end_date="", reg_deadline="",
         desc="高规格国家级 CTF，线上初赛 + 线下总决赛，业内公认的高水平赛事，优秀选手有机会获得推荐资格。"
              "赛程每年由官网发布，请以通知为准。",
         tags=["CTF", "团队赛"], tier="S",
         scores=(4, 3, 4, 5), verified=False),
    # ---------------- 数据科学 ----------------
    dict(name="Kaggle 数据科学竞赛（Featured / Research / Playground）", category="数据科学",
         organizer="Kaggle（Google 旗下）", url="https://www.kaggle.com/competitions",
         start_date="", end_date="", reg_deadline="",
         desc="全球最大的数据科学竞赛平台，赛季常年滚动，Featured/Research 竞赛竞争激烈（金牌率约前 0.2%），"
              "业界简历认可度极高。本平台会自动同步全部进行中的 Kaggle 竞赛，无需再手查。",
         tags=["机器学习", "金银牌体系", "求职"], tier="A",
         scores=(5, 5, 2, 5), verified=True),
    dict(name="天池大赛（阿里云天池）", category="数据科学",
         organizer="阿里巴巴集团（阿里云天池）", url="https://tianchi.aliyun.com/competition/activeList",
         start_date="", end_date="", reg_deadline="",
         desc="阿里云主办的数据科学竞赛平台，赛事冠军方案常被业界引用，优秀选手有机会获得实习/内推机会。"
              "天池的赛事日程由前端异步加载、接口带 CSRF 校验，无法稳定自动抓取，请以官网「赛事」列表为准。",
         tags=["机器学习", "实习绿色通道"], tier="A",
         scores=(4, 4, 3, 5), verified=False),
    # ---------------- 企业赛 ----------------
    dict(name="华为软件精英挑战赛", category="程序设计",
         organizer="华为技术有限公司", url="https://competition.huaweicloud.com/codecraft/",
         start_date="", end_date="", reg_deadline="",
         desc="华为旗舰软件赛事，赛题贴近真实业务（性能优化 / 分布式 / AI），历年优秀选手可获实习与 offer 通道。"
              "通常在春季启动报名、暑期决赛，具体赛程见华为云赛事官网。",
         tags=["算法", "高奖金", "offer直通车"], tier="A",
         scores=(4, 3, 3, 5), verified=False),
    dict(name="百度之星程序设计大赛", category="程序设计",
         organizer="百度公司", url="https://star.baidu.com/",
         start_date="", end_date="", reg_deadline="",
         desc="历史悠久的企业算法赛事，初赛线上、决赛现场，优胜者有机会进入百度实习。"
              "年度赛程（通常 5–9 月）以百度之星官网通知为准。",
         tags=["算法", "企业赛", "实习机会"], tier="A",
         scores=(3, 4, 2, 4), verified=False),
    # ---------------- 综合创新 / 作品赛 ----------------
    dict(name="中国大学生计算机设计大赛", category="综合创新",
         organizer="中国大学生计算机设计大赛组织委员会（教育部相关教指委指导）",
         url="https://jsjds.blcu.edu.cn/",
         start_date="", end_date="", reg_deadline="",
         desc="入选全国普通高校大学生竞赛排行榜的作品类赛事，校内赛 → 省级赛 → 国赛三级选拔，"
              "覆盖软件应用与开发、AI 应用、数媒设计等多个赛道。赛程每年 11 月前后发布，春季省赛、暑期国赛。",
         tags=["作品赛", "软件", "AI"], tier="S",
         scores=(3, 4, 5, 4), verified=False),
    dict(name="“挑战杯”全国大学生课外学术科技作品竞赛", category="创新创业",
         organizer="共青团中央 / 中国科协 / 教育部 / 全国学联", url="https://www.tiaozhanbei.net/",
         start_date="", end_date="", reg_deadline="",
         desc="大学生科技创新领域最具影响力的赛事（俗称「大挑」，两年一届，双数年举办），"
              "与「创青春」「挑战杯创业计划竞赛」共同构成挑战杯系列，特等奖在保研中权重极高。",
         tags=["科创", "作品赛", "保研王牌"], tier="S",
         scores=(5, 5, 5, 5), verified=False),
    dict(name="中国国际大学生创新大赛（原“互联网+”大赛）", category="创新创业",
         organizer="教育部等部委联合主办", url="https://cy.ncss.cn/",
         start_date="", end_date="", reg_deadline="",
         desc="国内规格最高的双创赛事，分高教主赛道、青年红色筑梦之旅赛道、职教赛道等，校赛 → 省赛 → 国赛三级推进，"
              "金奖项目在升学、孵化、融资方面均有加持。每年 3–4 月启动、10 月前后全国总决赛。",
         tags=["创业", "路演", "风投关注"], tier="S",
         scores=(4, 4, 5, 4), verified=False),
    dict(name="全国大学生电子设计竞赛（NUEDC）", category="嵌入式硬件",
         organizer="教育部高等教育司 / 工业和信息化部人事教育司", url="https://nuedc.xjtu.edu.cn/",
         start_date="", end_date="", reg_deadline="",
         desc="电子信息类最具权威性的学科竞赛（奇数年举办全国赛、偶数年多为省赛/专题赛），"
              "四天三夜封闭式设计制作，国一对保研帮助极大。具体赛期由全国竞赛组委会在官网公布。",
         tags=["单片机", "硬件", "保研硬通货"], tier="S",
         scores=(4, 5, 5, 5), verified=False),
    dict(name="中国大学生服务外包创新创业大赛", category="创新创业",
         organizer="教育部 / 商务部 / 无锡市人民政府", url="http://www.fwwb.org.cn/",
         start_date="", end_date="", reg_deadline="",
         desc="国家级 A 类学科竞赛，分企业命题赛道与自由命题赛道，校企合作导向强，获奖对评奖评优与就业均有帮助。",
         tags=["创新", "校企", "综测加分"], tier="A",
         scores=(3, 3, 4, 3), verified=False),
]

#: 精选入口：无法稳定自动抓取赛程，但仍然值得留一个「直达官网」的常驻入口。
#: 这些记录不会参与「未来 N 天」筛选（显示为长期开放），只作为入口与资讯参考。
CURATED = [
    dict(name="牛客网 · 竞赛中心", category="算法竞赛",
         organizer="牛客网", url="https://ac.nowcoder.com/acm/contest/vip",
         desc="牛客是校招笔试与算法竞赛的重要平台，常年举办企业命题赛、周赛与模拟笔试。"
              "牛客竞赛列表由前端渲染且需登录态，本平台无法稳定抓取实时赛程，点「直达官网」查看最新场次。",
         tags=["校招", "企业赛", "入口"], tier="B", scores=(3, 3, 2, 4)),
    dict(name="ICPC 官网 · 赛事日历", category="算法竞赛",
         organizer="ICPC 基金会", url="https://icpc.global/regionals/finder",
         desc="ICPC 各赛区（Asia 等）的区域赛日历与报名入口。",
         tags=["团队赛", "入口"], tier="S", scores=(5, 5, 5, 5)),
]


def _scores(row):
    """兼容 (d, h, p, i) 顺序：难度 / 历史 / 政策 / 行业。"""
    return row["scores"]


def seed(db):
    """首次运行写入内置数据（日期字段可为空 —— 表示官网未公布）。"""
    _insert_rows(db, BUILTIN, "builtin")
    _insert_rows(db, CURATED, "curated")


def backfill_curated(db):
    """老库升级：补写精选入口（幂等）。"""
    missing = []
    have = {r[0] for r in db.execute("SELECT url FROM competitions")}
    for row in CURATED:
        if row["url"] not in have:
            missing.append(row)
    if missing:
        _insert_rows(db, missing, "curated")


#: 旧版内置赛事名称 -> 新版名称（用于把老库里过时/错误的记录换成新数据）
_LEGACY_NAMES = {
    "ACM-ICPC 亚洲区域赛": "ICPC 国际大学生程序设计竞赛（区域赛）",
    "CCPC 中国大学生程序设计竞赛（总决赛）": "CCPC 中国大学生程序设计竞赛（分站赛 & 总决赛）",
    "蓝桥杯大赛（省赛→国赛）": "蓝桥杯全国软件和信息技术专业人才大赛（省赛 → 国赛）",
    "全国大学生信息安全竞赛 CISCN": "全国大学生信息安全竞赛 CISCN（创新实践能力赛）",
    "Kaggle 竞赛 (Featured)": "Kaggle 数据科学竞赛（Featured / Research / Playground）",
    "天池大赛（阿里云）": "天池大赛（阿里云天池）",
    '"挑战杯"课外学术科技作品竞赛': "“挑战杯”全国大学生课外学术科技作品竞赛",
    '"互联网+"中国国际大学生创新大赛': "中国国际大学生创新大赛（原“互联网+”大赛）",
    "全国大学生电子设计竞赛": "全国大学生电子设计竞赛（NUEDC）",
    "服务外包创新创业大赛": "中国大学生服务外包创新创业大赛",
}


#: 旧版本内置、但新版已删除的条目（不再提供：由实时来源覆盖，或信息不准确）
#: 匹配名称前缀；这些记录在升级时会被移除，避免和实时同步的赛程重复。
_OBSOLETE_BUILTIN = (
    "蓝桥杯青少年组 / NOIP 系列",     # 属于 NOI 系列（面向中学生），与蓝桥杯混淆
    "Codeforces Round 系列周赛",      # 已由 Codeforces 数据源实时同步具体场次
    "AtCoder 周赛（ABC/ARC/AGC）",    # 已由 AtCoder 数据源实时同步具体场次
    "LeetCode 周赛 / 双周赛",         # 已由 LeetCode 数据源实时同步具体场次
    "Kaggle 竞赛 (Featured)",        # 已由 Kaggle 数据源实时同步进行中的竞赛
)


def remove_obsolete_builtin(db):
    """移除旧版本里由实时来源覆盖、或信息不准确的占位条目（幂等）。"""
    removed = 0
    for prefix in _OBSOLETE_BUILTIN:
        rows = db.execute(
            "SELECT id FROM competitions WHERE source='builtin' AND (name=? OR name LIKE ?)",
            (prefix, prefix + "%")).fetchall()
        for row in rows:
            if db.execute("SELECT 1 FROM favorites WHERE comp_id=?", (row["id"],)).fetchone():
                continue  # 用户收藏过的保留，不做破坏性删除
            db.execute("DELETE FROM plans WHERE comp_id=?", (row["id"],))
            db.execute("DELETE FROM notes WHERE comp_id=?", (row["id"],))
            db.execute("DELETE FROM competitions WHERE id=?", (row["id"],))
            removed += 1
    return removed


def upgrade_builtin(db):
    """把老库里的旧版内置数据升级为新版（日期不编造、已更正错误表述）。

    旧版本内置的 20 场赛事里大量日期是无依据的（例如「CCPC 第 11 届总决赛
    已于 2026-04-25 在南阳理工学院举行」），新版采用「没把握就留空」的策略。
    这里按 URL 匹配已有记录并就地更新，保留用户自己加的收藏/计划（它们按 id 关联）。
    """
    updated = 0
    rows = {r["url"]: dict(r) for r in db.execute(
        "SELECT * FROM competitions WHERE source='builtin'")}
    for spec in BUILTIN:
        row = rows.get(spec["url"])
        if row is None:
            # 按旧名称匹配（URL 变过的情况）
            legacy = [old for old, new in _LEGACY_NAMES.items()
                      if new == spec["name"] and old in
                      {r["name"] for r in db.execute(
                          "SELECT name FROM competitions WHERE source='builtin'")}]
            if legacy:
                row = dict(db.execute(
                    "SELECT * FROM competitions WHERE source='builtin' AND name=?",
                    (legacy[0],)).fetchone() or {})
            if not row:
                _insert_rows(db, [spec], "builtin")
                updated += 1
                continue
        d, h, p, i = _scores(spec)
        db.execute(
            "UPDATE competitions SET name=?, category=?, organizer=?, start_date=?, "
            "end_date=?, reg_deadline=?, url=?, desc=?, tags=?, tier=?, "
            "s_difficulty=?, s_history=?, s_policy=?, s_industry=?, verify_status=? "
            "WHERE id=? AND source='builtin'",
            (spec["name"], spec["category"], spec["organizer"],
             spec.get("start_date", ""), spec.get("end_date", ""),
             spec.get("reg_deadline", ""), spec["url"], spec["desc"],
             json.dumps(spec["tags"], ensure_ascii=False), spec["tier"],
             d, h, p, i, "verified" if spec.get("verified") else "manual", row["id"]))
        updated += 1
    return updated


def _insert_rows(db, rows, source):
    for row in rows:
        d, h, p, i = _scores(row)
        verify = "verified" if row.get("verified") else "manual"
        db.execute(
            "INSERT INTO competitions(name,category,organizer,start_date,end_date,"
            "reg_deadline,url,desc,tags,source,source_id,tier,s_difficulty,s_history,"
            "s_policy,s_industry,verify_status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["name"], row["category"], row["organizer"],
             row.get("start_date", ""), row.get("end_date", ""),
             row.get("reg_deadline", ""), row["url"], row["desc"],
             json.dumps(row["tags"], ensure_ascii=False),
             source, "", row["tier"], d, h, p, i, verify))


def next_cumcm_window(year):
    """给定年份的全国大学生数学建模竞赛窗口（9 月中旬的周四 → 周日）。"""
    d = datetime.date(year, 9, 10)
    while d.weekday() != 3:  # 周四
        d += datetime.timedelta(days=1)
    return d, d + datetime.timedelta(days=3)
