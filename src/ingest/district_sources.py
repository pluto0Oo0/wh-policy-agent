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

# 页脚/版权等"正文已结束"的标记，遇到即截断，防止把导航和页脚当正文
# 每条都是 2026-11-08 在 12 个页面里实测出现过的，不是猜的。
FOOTER_MARKERS = (
    "网站标识码",
    "网站技术支持",
    "版权所有",
    "鄂公网安备",
    "您访问的链接即将离开",
    "是否继续",
    "网站地图",
    "站点地图",
    "相关解读",
    "关联政策",
    "分享到微信朋友圈",
    "中国经济网",
    "相关内容",
    "友情链接",
    "上一篇",
)

# 正文中间夹着的导航噪声（实测于经开区、江夏页面），逐行剔除
NAV_NOISE = (
    "智能问答", "长者专区", "无障碍", "登录", "注册", "首页", "搜索", "检索",
    "繁体", "中国政府网", "湖北省政府", "当前位置", "政府信息公开",
    "Language", "English", "日本语", "Français", "Deutsch",
    "走进经开区", "经彩纷呈", "经开概况", "经智园区", "新闻中心",
    "区内要闻", "视频新闻", "政策", "政府信息公开指南", "政府信息公开制度",
    "法定主动公开内容", "网站工作年度报表", "政府信息公开年度报告",
    "地方和部门平台链接", "互动交流", "我要留言", "征集调查", "民生关切",
    "专题集合", "长者专区", "网站首页", "公众服务", "魅力江夏", "亲清江夏",
    "中央人民政府", "湖北省人民政府", "武汉市人民政府", "微博", "|",
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
        note:           人工备注（例如"新闻稿"、"2019 年旧政"）
    """

    key: str
    region: str
    url: str
    title_anchor: str
    is_policy_text: bool
    note: str


SOURCES: tuple[DistrictSource, ...] = (
    DistrictSource(
        key="jingkai_chunsun",
        region="经开区",
        url="https://www.whkfq.gov.cn/xwzx/yw/kfqyw/qnxw/202208/t20220802_2016587.html",
        title_anchor="@车谷青年：“春笋行动”人才购车、购房、租房补贴，线下申报开始啦！",
        is_policy_text=False,
        note="新闻通稿，讲补贴但不是政策文本",
    ),
    DistrictSource(
        key="qiaokou_14",
        region="硚口",
        url="https://www.qiaokou.gov.cn/qkxw/tzgg/202510/t20251011_2658454.shtml",
        title_anchor="硚口区第十四批大学毕业生租赁房配租公告",
        is_policy_text=True,
        note="配租公告，含叠加条款",
    ),
    DistrictSource(
        key="jiangan_rencai",
        region="江岸",
        url="https://www.jiangan.gov.cn/bmzl/qfgj/xxgk_8593/202401/t20240105_2337618.shtml",
        title_anchor="江岸区人才租赁房配租公告",
        is_policy_text=True,
        note="配租公告",
    ),
    DistrictSource(
        key="jianghan_zhenghui",
        region="江汉",
        url="https://www.jianghan.gov.cn/zfxxgk/fdzdgknr/ggzypz/shbz/bzxzfzc/202604/t20260424_2757109.shtml",
        title_anchor="春来“才”知暖，江汉区人才租赁房项目 “春日大集结”",
        is_policy_text=False,
        note="房源汇总推文，含房源与租金，政策条件较少",
    ),
    DistrictSource(
        key="qingshan_zhinan",
        region="青山",
        url="https://www.qingshan.gov.cn/ztdh/qsrc/rczc/202402/t20240221_2361801.shtml",
        title_anchor="高校毕业生租住人才租赁房租金减免办理指南",
        is_policy_text=True,
        note="办理指南，含申请对象与条件",
    ),
    DistrictSource(
        key="qingshan_peizu",
        region="青山",
        url="https://www.qingshan.gov.cn/zfxxgk/fdzdgknr/ggzypz/bzxzf/bzxzfzc/202403/t20240326_2379071.shtml",
        title_anchor="青山区大学毕业生租赁房配租公告",
        is_policy_text=True,
        note="配租公告",
    ),
    DistrictSource(
        key="hongshan_peizu",
        region="洪山",
        url="https://www.hongshan.gov.cn/xxgk/jbxxgk/ggzypz/zfbz/bzxzffp_82508/202609/t20260917_2848978.shtml",
        title_anchor="洪山区人才租赁房配租公告",
        is_policy_text=True,
        note="配租公告",
    ),
    DistrictSource(
        key="hongshan_jiuzheng",
        region="洪山",
        url="https://www.hongshan.gov.cn/xxgk/zc/zcwd/202111/t20211125_1859832.shtml",
        title_anchor="大学毕业生租赁房申请过程中常见问题解答",
        is_policy_text=True,
        note="2021 年旧政问答，与 2022 新政并行，需标注时效",
    ),
    DistrictSource(
        key="jiangxia_yaogu",
        region="江夏",
        url="https://www.jiangxia.gov.cn/xxgk_22343/xxgkml_22349/ggzypz_71067/zfbz/bzxzffp/202609/t20260904_2843303.shtml",
        title_anchor="荟寓·药谷之星人才公寓项目配租公告",
        is_policy_text=True,
        note="配租公告",
    ),
    DistrictSource(
        key="xinzhou_xinzhou",
        region="新洲",
        url="https://www.whxinzhou.gov.cn/xxgk_29/xxgkml/ggzy/zfbz/bzxzfzc/202606/t20260623_2780693.shtml",
        title_anchor="新洲区新舟花园人才租赁房配租公告",
        is_policy_text=True,
        note="配租公告",
    ),
    DistrictSource(
        key="dongxihu_news",
        region="东西湖",
        url="https://www.dxh.gov.cn/XWZX/LKGYW/202406/t20240607_2413679.shtml",
        title_anchor="快来，租金最低7折，拎包入住",
        is_policy_text=False,
        note="新闻稿，租金描述，无政策条件",
    ),
    DistrictSource(
        key="caidian_peizu",
        region="蔡甸",
        url="https://www.caidian.gov.cn/zwgk/zwdt/gsgg/202001/t20200103_485775.shtml",
        title_anchor="蔡甸区大学毕业生租赁房配租登记公告",
        is_policy_text=True,
        note="2020 年发布的登记公告，配租口径为 2019 年旧政",
    ),
)


def extract_body(html: str, title_anchor: str) -> str:
    """从整页 HTML 中抽出正文文本。

    做法：找到第一个与 `title_anchor` 完全相等的段落或标题作为正文起点，
    到第一个页脚标记为止。之后按行清洗，去掉导航和空行。

    为什么找不到锚点要报错：
        锚点找不到说明页面改版或抓错了页，继续抽取只会得到导航栏。
        这是"程序不报错但结果是垃圾"的典型，必须直接抛异常。

    抛出：
        ValueError: 找不到标题锚点，或正文为空。
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    lines = [ln.strip() for ln in soup.get_text("\n").split("\n")]
    lines = [ln for ln in lines if ln]

    start = None
    for i, ln in enumerate(lines):
        if ln == title_anchor:
            start = i
            break
    if start is None:
        raise ValueError(f"找不到标题锚点：{title_anchor!r}")

    body: list[str] = []
    for ln in lines[start:]:
        if any(marker in ln for marker in FOOTER_MARKERS):
            break
        if ln in NAV_NOISE:
            continue
        body.append(ln)

    text = "\n".join(body).strip()
    if not text:
        raise ValueError("正文抽取结果为空")
    return text


def extract_date(html: str) -> str:
    """从页面中找发布日期，返回 `YYYY-MM-DD`，找不到返回空串。

    为什么取第一个匹配：页面头部的"发布时间"在正文之前，
    取第一个匹配可以避开正文里提到的其他日期（如"2022年6月7日"的旧政）。
    找不到就返回空串，不编造。
    """
    text = BeautifulSoup(html, "lxml").get_text(" ")
    m = DATE_PATTERN.search(text)
    if not m:
        return ""
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"
