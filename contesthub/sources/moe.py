# -*- coding: utf-8 -*-
"""大学生竞赛白名单（84 项）。

说明：教育部并不面向大学生发布“白名单”，高校和学生口里的“教育部白名单”
通常指中国高等教育学会高校竞赛评估与管理体系研究专家工作组发布的
《全国普通高校大学生竞赛分析报告》**竞赛目录**（共 84 项，另有观察目录）。
本来源按该竞赛目录维护，用于回答“哪些比赛是学校/学院普遍认可的”。

目录内的赛事没有统一的公开 API，且各赛事赛程由主办方单独发布，因此这里
只维护**赛事名录与官网入口**，不编造日期；状态显示为「日期待定」，
报名时间与赛程以官网通知为准。若某场比赛同时被在线来源（Codeforces 等）
抓到，会按 URL/名称自动归并，不会重复。

数据版本：2024/2025 年竞赛目录（84 项）。名称与官网地址整理自
《全国普通高校大学生竞赛分析报告》竞赛目录及各校教务处转载版本。
"""
import hashlib

from .base import Source, make_item

HOME_URL = "https://www.cahe.edu.cn/"

#: 竞赛目录（名称，官网，类别）。顺序沿用竞赛目录序号。
COMPETITIONS = [
    ("中国国际大学生创新大赛", "https://cy.ncss.cn/", "创新创业"),
    ("“挑战杯”全国大学生课外学术科技作品竞赛", "http://www.tiaozhanbei.net/", "创新创业"),
    ("“挑战杯”中国大学生创业计划大赛", "http://www.chuangqingchun.net/", "创新创业"),
    ("ACM-ICPC国际大学生程序设计竞赛", "https://icpc.global/", "算法竞赛"),
    ("全国大学生数学建模竞赛", "http://www.mcm.edu.cn/", "数学建模"),
    ("全国大学生电子设计竞赛", "http://www.nuedcchina.com/", "嵌入式硬件"),
    ("中国大学生医学技术技能大赛",
     "https://medu.bjmu.edu.cn/cms/show.action?code=publish_4af037e16e264f60016eaa7dea950ef4&siteid=100001",
     "学科专业"),
    ("全国大学生机械创新设计大赛", "http://umic.ckcest.cn/", "嵌入式硬件"),
    ("全国大学生结构设计竞赛", "http://www.structurecontest.com/", "学科专业"),
    ("全国大学生广告艺术大赛", "http://www.sun-ada.net/", "设计艺术"),
    ("全国大学生智能汽车竞赛",
     "http://www.eepw.com.cn/event/action/freescale_car2012/", "嵌入式硬件"),
    ("全国大学生电子商务“创新、创意及创业”挑战赛", "http://www.3chuang.net/", "创新创业"),
    ("中国大学生工程实践与创新能力大赛", "http://www.gcxl.edu.cn/new/index.html", "嵌入式硬件"),
    ("全国大学生物流设计大赛", "http://www.clpp.org.cn/", "学科专业"),
    ("“外研社·国才杯”“理解当代中国”全国大学生外语能力大赛",
     "http://uchallenge.unipus.cn/", "外语人文"),
    ("两岸新锐设计竞赛·华灿奖", "http://www.huacanjiang.com/home", "设计艺术"),
    ("全国大学生创新创业训练计划年会展示", "http://gjcxcy.bjtu.edu.cn/Index.aspx", "创新创业"),
    ("全国大学生化工设计竞赛", "http://iche.zju.edu.cn/", "学科专业"),
    ("全国大学生机器人大赛(CURC)", "http://www.cnrobocon.net/", "嵌入式硬件"),
    ("全国大学生市场调查与分析大赛", "http://www.china-cssc.org/list-56-1.html", "学科专业"),
    ("全国大学生先进成图技术与产品信息建模创新大赛", "http://www.chengtudasai.com/", "学科专业"),
    ("全国三维数字化创新设计大赛", "https://3dds.3ddl.net/", "设计艺术"),
    ("“西门子杯”中国智能制造挑战赛", "http://www.siemenscup-cimc.org.cn/", "嵌入式硬件"),
    ("中国大学生服务外包创新创业大赛", "http://www.fwwb.org.cn/", "创新创业"),
    ("中国大学生计算机设计大赛", "http://jsjds.blcu.edu.cn/", "程序设计"),
    ("中国高校计算机大赛", "http://www.c4best.cn/", "程序设计"),
    ("蓝桥杯全国软件和信息技术专业人才大赛", "http://dasai.lanqiao.cn/", "程序设计"),
    ("米兰设计周--中国高校设计学科师生优秀作品展", "http://www.dandad.cn/", "设计艺术"),
    ("全国大学生地质技能竞赛", "https://yuanxi.cugb.edu.cn/competition/", "学科专业"),
    ("全国大学生光电设计竞赛", "http://gd.p.moocollege.com/", "嵌入式硬件"),
    ("全国大学生集成电路创新创业大赛", "http://univ.ciciec.com/", "嵌入式硬件"),
    ("全国大学生金相技能大赛", "http://www.cnzjjx.cn/", "学科专业"),
    ("全国大学生信息安全竞赛", "http://www.ciscn.cn/", "网络安全"),
    ("未来设计师·全国高校数字艺术设计大赛", "https://www.ncda.org.cn/", "设计艺术"),
    ("全国周培源大学生力学竞赛", "http://zpy.cstam.org.cn/", "学科专业"),
    ("中国大学生机械工程创新创意大赛", "http://www.gczbds.org/", "嵌入式硬件"),
    ("中国机器人大赛暨RoboCup机器人世界杯中国赛", "http://crc.drct-caa.org.cn/", "嵌入式硬件"),
    ("“中国软件杯”大学生软件设计大赛", "http://www.cnsoftbei.com/", "程序设计"),
    ("中美青年创客大赛", "https://chinaus-maker.cscse.edu.cn/", "创新创业"),
    ("睿抗机器人开发者大赛（RAICOM）", "https://www.robocom.com.cn/", "嵌入式硬件"),
    ("“大唐杯”全国大学生新一代信息通信技术大赛", "https://dtcup.dtxiaotangren.com/", "嵌入式硬件"),
    ("华为ICT大赛", "https://e.huawei.com/cn/talent/ict-academy/#/ict-contest?compId=85131973",
     "程序设计"),
    ("全国大学生嵌入式芯片与系统设计竞赛", "http://www.socchina.net/", "嵌入式硬件"),
    ("全国大学生生命科学竞赛（CULSC）", "https://www.culsc.cn/#/", "学科专业"),
    ("全国大学生物理实验竞赛", "http://wlsycx.moocollege.com/", "学科专业"),
    ("全国高校BIM毕业设计创新大赛", "http://gxbsxs.glodonedu.com/index", "学科专业"),
    ("全国高校商业精英挑战赛", "http://cubec.org.cn/", "创新创业"),
    ("“学创杯”全国大学生创业综合模拟大赛", "http://www.bster.cn/cyds/index", "创新创业"),
    ("中国高校智能机器人创意大赛", "http://www.robotcontest.cn/", "嵌入式硬件"),
    ("中国好创意暨全国数字艺术设计大赛", "https://www.cdec.org.cn/", "设计艺术"),
    ("中国机器人及人工智能大赛", "https://developer.apollo.auto/devcenter/gameOperations_cn.html?target=3",
     "嵌入式硬件"),
    ("全国大学生节能减排社会实践与科技竞赛", "http://www.jienengjianpai.org/", "综合创新"),
    ("“21世纪杯”全国英语演讲比赛", "https://contest.i21st.cn/", "外语人文"),
    ("iCAN大学生创新创业大赛", "http://www.g-ican.com/home/index", "创新创业"),
    ("“工行杯”全国大学生金融科技创新大赛",
     "https://www.gonghangbei.com/index/Lists/index.html?id=1", "创新创业"),
    ("中华经典诵写讲大赛", "https://www.jingdiansxj.cn/home", "外语人文"),
    ("“外教社杯”全国高校学生跨文化能力大赛",
     "https://ict.sflep.com/index.php?m=content&c=index&a=lists&catid=15", "外语人文"),
    ("百度之星·程序设计大赛", "https://star.baidu.com/#/", "程序设计"),
    ("全国大学生工业设计大赛", "https://www.cuidc.net/#/", "设计艺术"),
    ("全国大学生水利创新设计大赛",
     "https://sljzw.hhu.edu.cn/fenhui/2023/0411/c12009a259306/page.htm", "学科专业"),
    ("全国大学生化工实验大赛", "http://www.cteic.com/higherEducation-199.html", "学科专业"),
    ("全国大学生化学实验创新设计大赛", "https://cid.nju.edu.cn/", "学科专业"),
    ("全国大学生计算机系统能力大赛", "https://compiler.educg.net/#/", "程序设计"),
    ("全国大学生花园设计建造竞赛", "http://www.lalavision.com/hysjjzjs", "设计艺术"),
    ("全国大学生物联网设计竞赛", "https://developer.huaweicloud.com/college/wulianwang.html",
     "嵌入式硬件"),
    ("全国大学生信息安全与对抗技术竞赛", "http://www.isclab.org.cn/", "网络安全"),
    ("全国大学生测绘学科创新创业智能大赛", "http://smt.whu.edu.cn/index.htm", "学科专业"),
    ("全国大学生统计建模大赛", "http://tjjmds.ai-learning.net/", "数学建模"),
    ("全国大学生能源经济学术创意大赛",
     "http://energy.qibebt.ac.cn/eneco/contribution/index.html", "综合创新"),
    ("全国大学生基础医学创新研究暨实验设计论坛（大赛）", "http://www.jcyxds.com/", "学科专业"),
    ("全国大学生数字媒体科技作品及创意竞赛", "http://mit.caai.cn/", "设计艺术"),
    ("全国本科院校税收风险管控案例大赛", "http://ssfkds.moocollege.com/", "学科专业"),
    ("全国企业竞争模拟大赛", "http://www.ibizsim.cn/", "创新创业"),
    ("全国高等院校数智化企业经营沙盘大赛", "http://spbk.seentao.com/", "创新创业"),
    ("全国数字建筑创新应用大赛", "http://bisai.ccen.com.cn/", "学科专业"),
    ("全球校园人工智能算法精英大赛",
     "https://developer.huawei.com/consumer/cn/activity/digixActivity/digixdetail/101655281685926449",
     "数据科学"),
    ("国际大学生智能农业装备创新大赛", "http://uiaec.ujs.edu.cn/", "嵌入式硬件"),
    ("“科云杯”全国大学生财会职业能力大赛", "http://match.xmkeyun.com.cn/", "学科专业"),
    ("全国职业院校技能大赛", "https://chinaskills.icve.com.cn/", "职业技能"),
    ("全国大学生机器人大赛-RoboTac", "http://www.robotac.cn/", "嵌入式硬件"),
    # 两条“世界技能大赛”条目在目录中共用同一官网，这里补上英文名避免被同名归并
    ("世界技能大赛（WorldSkills Competition）", "https://worldskills.org/", "职业技能"),
    ("世界技能大赛中国选拔赛", "http://worldskillschina.mohrss.gov.cn/", "职业技能"),
    ("一带一路暨金砖国家技能发展与技术创新大赛", "http://www.brskills.com/", "职业技能"),
    ("码蹄杯全国职业院校程序设计大赛", "https://matiji.net/matibei", "程序设计"),
]

TOTAL = len(COMPETITIONS)


def _source_id(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"uni-{digest}"


def build_items():
    """把静态名录转换成平台条目（不编造比赛日期）。"""
    items = []
    for index, (name, url, category) in enumerate(COMPETITIONS, 1):
        desc = (f"中国高等教育学会《全国普通高校大学生竞赛分析报告》竞赛目录"
                f"第 {index} 项（共 {TOTAL} 项，常被称为“教育部认可的大学生竞赛白名单”）。"
                "本平台只收录赛事名录与官网入口，具体报名时间、赛程与参赛要求以主办方官网"
                "通知为准；若该赛事同时有在线平台赛程，会显示对应场次。")
        items.append(make_item(
            name,
            url,
            category=category,
            desc=desc,
            tags=["大学生竞赛白名单", "竞赛目录", category],
            tier="A",
            difficulty=3,
            source_id=_source_id(name),
        ))
    return items


class MoeWhitelistSource(Source):
    key = "moe"
    label = "大学生竞赛白名单（84 项）"
    group = "教育部白名单"
    homepage = HOME_URL
    nature = "long"

    def fetch(self):
        return build_items()
