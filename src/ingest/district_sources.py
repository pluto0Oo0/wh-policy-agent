"""区级政策源的站点配置与正文抽取。

════════════════════════════════════════════════════════════════
为什么不用通用的"最大文字块"规则
════════════════════════════════════════════════════════════════
2026-11-08 实测：通用规则（取 <p> 段落的最近公共祖先）会把导航栏、页脚、
"您访问的链接即将离开"提示一起抓进正文，`content` 会被污染。
所以每个站点都要有**明确的标题锚点和正文结束标记**，并且每个锚点都是
实测得出的，不靠猜测。

════════════════════════════════════════════════════════════════
字段语义
════════════════════════════════════════════════════════════════
- `is_policy_text`：正文是否为政策原文或配租公告。新闻稿为 False，
  不进判定用的语料，只留作候选记录，审查时可筛。
- `publish_date`：来自页面里的发布日期字符串；取不到就留空，不编造。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# 页脚/链接区起点：只对"行首"匹配（startswith），并且都是页脚专有词。
# 为什么不再用子串匹配：审核（code-review 2026-11-08）演示了正文里出现
# "二、相关内容"这类普通文档语言会把后半截条款静默截断——子串匹配对
# 正文不安全，页脚特征词几乎只出现在行首。
FOOTER_STARTSWITH = (
    "主办单位", "网站标识码", "网站技术支持", "版权所有", "鄂公网安备",
    "鄂ICP备", "备案编号", "网站地图", "站点地图", "上级政府网站",
    "其他网站", "友情链接", "相关内容", "相关解读", "相关链接", "关联链接",
    "关联解读",
    "关联政策", "相关文章", "上一篇", "下一篇",
    "中央人民政府", "湖北省人民政府", "武汉市人民政府门户网站",
)

# 正文开头若是这些形态，说明锚点匹配到了页面小部件而不是文章标题 → 报错。
# 导航页脚里的"孤立短行"（面包屑箭头、关闭符号、访问计数）——仅整行相等时删除
EXACT_NOISE_LINES = ("»", "×", "|", "—", "·")

# 正文中的导航整行（12 页实测出现过的菜单/面包屑词）——仅整行相等时删除，
# 不做子串匹配："政策"这类词做子串会误删真正文行
NAV_NOISE = (
    "首 页", "首页", "登录", "注册", "搜索", "搜 索", "检索", "智能问答",
    "智能助手", "无障碍", "长者专区", "繁体", "登录/ 注册", "English",
    "分享到微信朋友圈", "CurrentPosition",
    "政府信息公开", "政府信息公开指南", "政务新媒体", "互动交流",
    "走进经开区", "经彩纷呈", "经开概况", "经智园区", "新闻中心", "区内要闻",
    "视频新闻", "法定主动公开内容", "网站工作年度报表", "地方和部门平台链接",
    "网站首页", "公众服务", "魅力江夏", "亲清江夏", "微博", "微信", "APP",
    "网站技术支持", "承办单位", "邮编加班", "会计师事务所", "我知道了",
)


DATE_PATTERN = re.compile(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})")


@dataclass(frozen=True)
class DistrictSource:
    """一个区级源的配置。

    字段：
        key:            唯一键，用于文件名和候选记录
        region:         区名，写入 `region` 字段
        url:            官网详情页地址
        title_anchor:   正文第一行的标题文字（用于定位正文起点）。
                        必须与页面中的真实标题一致，实测确认。
        is_policy_text: 该页是否为政策原文或配租公告
        anchor_pos:     标题在页面里重复出现时取哪一处。
                        "last" = 信息公开页（标题先出现在页首部件/尾部面包屑）；
                        "first" = 新闻/公告页（正文标题在前、尾部还有计数块标题）。
                        两类页面里"取哪次出现"语义相反——2026-11-08 审核
                        实锤：单一规则无法兼顾，必须页级标注。
        note:           人工备注（例如"新闻稿"、"2019 年旧政"）
    """

    key: str
    region: str
    url: str
    title_anchor: str
    is_policy_text: bool
    anchor_pos: str
    note: str


SOURCES: tuple[DistrictSource, ...] = (
    DistrictSource(
        key="jingkai_chunsun",
        region="经开区",
        url="https://www.whkfq.gov.cn/xwzx/yw/kfqyw/qnxw/202208/t20220802_2016587.html",
        title_anchor="@车谷青年：“春笋行动”人才购车、购房、租房补贴，线下申报开始啦！",
        is_policy_text=False,        anchor_pos="last",

        note="新闻通稿，讲补贴但不是政策文本",
    ),
    DistrictSource(
        key="qiaokou_14",
        region="硚口",
        url="https://www.qiaokou.gov.cn/qkxw/tzgg/202510/t20251011_2658454.shtml",
        title_anchor="硚口区第十四批大学毕业生租赁房配租公告",
        is_policy_text=True,        anchor_pos="last",

        note="配租公告，含叠加条款",
    ),
    DistrictSource(
        key="jiangan_rencai",
        region="江岸",
        url="https://www.jiangan.gov.cn/bmzl/qfgj/xxgk_8593/202401/t20240105_2337618.shtml",
        title_anchor="江岸区人才租赁房配租公告",
        is_policy_text=True,        anchor_pos="first",

        note="配租公告",
    ),
    DistrictSource(
        key="jianghan_zhenghui",
        region="江汉",
        url="https://www.jianghan.gov.cn/zfxxgk/fdzdgknr/ggzypz/shbz/bzxzfzc/202604/t20260424_2757109.shtml",
        title_anchor="春来“才”知暖，江汉区人才租赁房项目 “春日大集结”",
        is_policy_text=False,        anchor_pos="first",

        note="房源汇总推文，含房源与租金，政策条件较少",
    ),
    DistrictSource(
        key="qingshan_zhinan",
        region="青山",
        url="https://www.qingshan.gov.cn/ztdh/qsrc/rczc/202402/t20240221_2361801.shtml",
        title_anchor="高校毕业生租住人才租赁房租金减免办理指南",
        is_policy_text=True,        anchor_pos="first",

        note="办理指南，含申请对象与条件",
    ),
    DistrictSource(
        key="qingshan_peizu",
        region="青山",
        url="https://www.qingshan.gov.cn/zfxxgk/fdzdgknr/ggzypz/bzxzf/bzxzfzc/202403/t20240326_2379071.shtml",
        title_anchor="青山区大学毕业生租赁房配租公告",
        is_policy_text=True,        anchor_pos="first",

        note="配租公告",
    ),
    DistrictSource(
        key="hongshan_peizu",
        region="洪山",
        url="https://www.hongshan.gov.cn/xxgk/jbxxgk/ggzypz/zfbz/bzxzffp_82508/202609/t20260917_2848978.shtml",
        title_anchor="洪山区人才租赁房配租公告",
        is_policy_text=True,        anchor_pos="first",

        note="配租公告",
    ),
    DistrictSource(
        key="hongshan_jiuzheng",
        region="洪山",
        url="https://www.hongshan.gov.cn/xxgk/zc/zcwd/202111/t20211125_1859832.shtml",
        title_anchor="大学毕业生租赁房申请过程中常见问题解答",
        is_policy_text=True,        anchor_pos="last",

        note="2021 年旧政问答，与 2022 新政并行，需标注时效",
    ),
    DistrictSource(
        key="jiangxia_yaogu",
        region="江夏",
        url="https://www.jiangxia.gov.cn/xxgk_22343/xxgkml_22349/ggzypz_71067/zfbz/bzxzffp/202609/t20260904_2843303.shtml",
        title_anchor="荟寓·药谷之星人才公寓项目配租公告",
        is_policy_text=True,        anchor_pos="last",

        note="配租公告",
    ),
    DistrictSource(
        key="xinzhou_xinzhou",
        region="新洲",
        url="https://www.whxinzhou.gov.cn/xxgk_29/xxgkml/ggzy/zfbz/bzxzfzc/202606/t20260623_2780693.shtml",
        title_anchor="新洲区新舟花园人才租赁房配租公告",
        is_policy_text=True,        anchor_pos="last",

        note="配租公告",
    ),
    DistrictSource(
        key="dongxihu_news",
        region="东西湖",
        url="https://www.dxh.gov.cn/XWZX/LKGYW/202406/t20240607_2413679.shtml",
        title_anchor="快来，租金最低7折，拎包入住",
        is_policy_text=False,        anchor_pos="last",

        note="新闻稿，租金描述，无政策条件",
    ),
    DistrictSource(
        key="caidian_peizu",
        region="蔡甸",
        url="https://www.caidian.gov.cn/zwgk/zwdt/gsgg/202001/t20200103_485775.shtml",
        title_anchor="蔡甸区大学毕业生租赁房配租登记公告",
        is_policy_text=True,        anchor_pos="last",

        note="2020 年发布的登记公告，配租口径为 2019 年旧政",
    ),
)


def extract_body(html: str, title_anchor: str, anchor_pos: str = "last") -> str:
    """从整页 HTML 中抽出正文文本。

    做法：标题锚点可能在页面里出现 2-3 次（页首部件/正文/页尾计数块），
    逐处打分选"合格的"出现（标题后紧跟元信息，跳过工具条行），
    再按 `anchor_pos`（页级配置，见 DistrictSource docstring）取 first
    或 last。之后从正文起点走到页脚起始行为止。

    为什么找不到锚点/无合格锚点要报错：
        这是"程序不报错但结果是垃圾"的典型入口，必须直接抛异常，
        绝不能带病写出一条被 check_deliver 放行的污染记录。

    抛出：
        ValueError: 锚点 0 次匹配，或无任何一处带元信息窗口。
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    lines = [ln.strip() for ln in soup.get_text("\n").split("\n")]
    lines = [ln for ln in lines if ln]

    matches = [i for i, ln in enumerate(lines) if ln == title_anchor]
    if not matches:
        raise ValueError(f"找不到标题锚点：{title_anchor!r}")

    # ── 合格锚点判定（对每处出现打分，工具条行不算窗口）──────────
    # 标题在页面里会出现 2-3 次：页首部件、正文标题、页尾面包屑/计数块。
    # 真文章的标志：标题后紧跟元信息（发布时间/来源），中间可能隔着
    # "分享/打印/下载"工具条（江岸实测隔了 10 行工具条才见"来源："）。
    SHORT_DATE = re.compile(r"20\d{2}[-年]\d{1,2}[-月]\d{1,2}")
    META_PREFIX = ("发布", "更新", "日期", "来源", "索引", "文号", "字号")
    TOOLBAR = ("分享到", "【打印", "【下载", "【\xa0字体", "字号 :", "字号：", "【中", "【大", "【小")
    # 工具条伴生的孤立字号行（江岸实测：'大','中','小' 独占一行）
    TOOLBAR_EXACT = ("大", "中", "小", "】")

    def qualifies(i: int) -> bool:
        # 跳过工具条行后的 2 行为窗口
        window: list[str] = []
        for ln in lines[i + 1 : i + 14]:
            if (
                any(t in ln for t in TOOLBAR)
                or ln in TOOLBAR_EXACT
                or ln in EXACT_NOISE_LINES
            ):
                continue
            window.append(ln)
            if len(window) == 2:
                break
        if not window:
            return False
        has_date = any(SHORT_DATE.search(ln) for ln in window)
        has_meta = any(ln.startswith(META_PREFIX) or any(mp in ln[:12] for mp in ("来源", "日期")) for ln in window)
        # 新洲形态（第三审抓出）：信息公开元数据表**插在两次标题之间**——
        # 页首部件（35）带元信息、真文章（51）标题后**直接是长正文行**，
        # 若只认"元信息"判据会把真文章否决、选中部件（库里的 t20260623 正是受害记录）。
        # 所以窗口内出现 ≥30 字的长正文行同样算合格锚点：
        #   部件后 2 行永远是短行（'20'、栏目名、字段名），正文段落不可能那么短。
        has_body = any(len(ln) >= 30 for ln in window)
        return has_date or has_meta or has_body

    candidates = [i for i in matches if qualifies(i)]
    if not candidates:
        raise ValueError(
            f"标题锚点 {len(matches)} 处均无元信息/正文窗口，疑似页面改版或选错锚点：{title_anchor!r}"
        )
    # anchor_pos 由页级配置决定：信息公开页取 last，新闻页取 first。
    # 单一规则必然选错——这是 2026-11-08 审核后重放的实测结论。
    # 新洲形态修复（第三审）只改 qualifies（真文章"标题→直承长正文"也合格），
    # 不做"长正文优先"——实测它会破坏纠结区的 last 语义（经开区回退事故）。
    start = candidates[-1] if anchor_pos == "last" else candidates[0]

    body: list[str] = []
    for ln in lines[start + 1:]:
        if any(ln.startswith(p) for p in FOOTER_STARTSWITH):
            break
        # 工具条（分享/打印/字号切换）既出现在窗口判定，也出现在正文循环——
        # 洪山/江汉实测：'字号 :' 单行混进正文开头
        if (
            any(t in ln for t in TOOLBAR)
            or ln in TOOLBAR_EXACT
            or ln in NAV_NOISE
            or ln in EXACT_NOISE_LINES
        ):
            continue
        # 新洲/蔡甸式页脚：连续的"××人民政府门户网/××局"链接行——
        # 正文段落不可能整行都是一个机构名或以"人民政府"结尾的行
        if (
            len(ln) <= 30
            and (ln.endswith(("人民政府", "门户网站", "人民政府网站", "委员会", "办公室", "管理局"))
                 or ln.startswith(("中国城市网", "央视网", "共产党员", "国家信息中心", "信用")))
        ):
            continue
        body.append(ln)

    text = "\n".join(body).strip()
    if not text:
        raise ValueError("正文抽取结果为空")
    return text


def extract_date(html: str) -> str:
    """从页面中找发布日期，返回 `YYYY-MM-DD`，找不到返回空串。

    与 extract_body 一样先剥 script/style——审核（2026-11-08）指出 JS 代码里
    的字面日期会被当成发布日。为什么取第一个匹配：页面头部的"发布时间"
    在正文之前，取第一个匹配可以避开正文里提到的其他日期。找不到就返回
    空串，不编造。
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ")
    m = DATE_PATTERN.search(text)
    if not m:
        return ""
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def doc_id_from_url(url: str) -> str:
    """取详情页 URL 末段作为 doc_id（SPEC §2.1 口径：URL 末段或 uuid）。

    为什么不用自造键（如 qiaokou_14）：自造键让同一张 corpus 表里出现
    两套 doc_id 规格，凡是按 doc_id 分组/对账的环节都会看到异构记录。
    URL 末段 （t20251011_2658454） 全局唯一且天然可溯源。
    """
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    for ext in (".shtml", ".html"):
        if tail.endswith(ext):
            return tail[: -len(ext)]
    return tail
