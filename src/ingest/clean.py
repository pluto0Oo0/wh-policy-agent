"""清洗模块 —— 把详情页 HTML 变成可判定的正文文本 + 识别模板族。

SPEC §5 定了两个函数签名，不得改名：
    clean_text(html) -> str
    detect_template_family(html) -> str

════════════════════════════════════════════════════════════════
为什么单独一个模块（而不是塞在 crawl.py 里）
════════════════════════════════════════════════════════════════
抓取和清洗的**失效原因完全不同**，混在一起排查时会互相掩盖：

  抓取失败   → 网络 / HTTP / 软 404      → 症状是"没拿到页面"
  清洗失败   → 页面改版 / 容器类名变了   → 症状是"拿到了页面但正文是空的"

第二种更危险：**HTTP 200、页面完整、程序不报错，只是正文抽出来是 0 字。**
2026-10-13 实测就是这个形态 —— 人社局的 78 号文页 `TRS_Editor` 出现 0 次，
按市级站的判据它会"正常抓取"，然后正文为空。

════════════════════════════════════════════════════════════════
容器类名不跨站点（这是本模块最需要记住的一条）
════════════════════════════════════════════════════════════════
2026-10-04/13 实测：

  | 站点                | 正文容器       |
  |---------------------|----------------|
  | www.wuhan.gov.cn    | TRS_Editor ×13 |
  | rsj.wuhan.gov.cn    | 无 TRS_Editor  |
  | hanyang.gov.cn      | 无 TRS_Editor  |

→ 所以**不能写死一个类名**。这里用"按优先级依次试"的方式，
  将来加了区级源就往 CONTENT_CONTAINERS 里追加。
"""

import re

from bs4 import BeautifulSoup

# ── 已知正文容器，按优先级排 ────────────────────────────────
# ⚠️ 追加新站点前必须**先实测它到底用哪个类名**，不要猜。
#    猜错的后果是"正常抓取 + 正文为空"，不报错。
CONTENT_CONTAINERS = ("TRS_Editor",)

# ── 七段式关键词（SPEC §3.3 模板族 A 的特征）─────────────────
# 用途：detect_template_family 靠数这些词的出现来判断"有没有七段式结构"。
SEVEN_SECTION_KEYWORDS = (
    "政策内容",
    "申报对象",
    "申报条件",
    "补贴标准",
    "文件依据",
    "申请材料",
    "业务流程",
    "受理部门",
    "支持标准",
    "办理流程",
)

TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def _find_content_box(html: str):
    """依次试已知容器，返回第一个找到的 BeautifulSoup 节点；都没有返回 None。

    为什么返回节点而不是文本：
        调用方（detect_template_family）需要看**结构**，不只是文本。
    """
    soup = BeautifulSoup(html, "lxml")
    for class_name in CONTENT_CONTAINERS:
        box = soup.find("div", class_=class_name)
        if box is not None:
            return box
    return None


def clean_text(html: str) -> str:
    """从详情页 HTML 里抽出正文纯文本。

    参数：
        html: 详情页完整源码

    返回：
        正文纯文本（逐行 strip、丢空行、单换行拼接）；
        **找不到正文容器时返回空串**。

    为什么找不到时返回空串、而不是在这里抛异常：
        本函数只负责"抽"，不负责"决定抽不到算不算失败"。
        那个决定属于调用方 —— `crawl_detail` 收到空串会抛 `CrawlError`，
        因为存一条空 content 进语料库会把错误静默固化。
        **把判断留在调用方，是为了让"抽不到"这件事只有一个处置点。**
    """
    box = _find_content_box(html)
    if box is None:
        return ""

    # 正文容器里第一个子元素通常是 <style>（实测市级站如此）。
    # 不去掉的话，抽出来的"正文"开头会是一大段 CSS —— 而且它看起来像正文。
    for tag in box(["style", "script"]):
        tag.decompose()

    text = box.get_text(separator="\n")
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def detect_template_family(html: str) -> str:
    """识别模板族，返回 "A"~"G"；无法判定返回 "G"（SPEC §5 规定的降级值）。

    ⚠️ **当前只实现了 A 和 G 两族**，B~F 未实现。这不是偷懒，是**没有可编码的依据**：

        SPEC §3.3 给了 B~F 的**结构特征**（如"九段式，支持标准排在申报条件之前"），
        但没有给**判定规则** —— 数到几个关键词算 B？顺序差多少算不同族？
        真要做，得先拿那 33 个区级页面重新标定一遍，那是 SPEC 层面的工作。

    **能做的、也已经验证过的部分**：
        区分「有七段式结构」(A) 和「没有」(G)。
        2026-10-04/13 实测支持这条：汉阳区 15 条 **0/10 命中**；
        78 号文（红头文件）「受理/申报对象/申请材料」**全部 0 次**。

    判定规则（刻意简单，因为简单才可验证）：
        正文里命中 ≥3 个七段式关键词 → "A"
        否则 → "G"

    为什么阈值取 3 而不是 1：
        单个词可能是巧合（正文里恰好提到"申请材料"四个字）。
        3 个不同关键词同时出现，才说明是**按段落的模板结构**。
    """
    text = clean_text(html)
    if not text:
        # 抽不到正文 → 无法判定。返回 G（规范允许的降级值），不猜一个族。
        return "G"

    hits = sum(1 for kw in SEVEN_SECTION_KEYWORDS if kw in text)
    return "A" if hits >= 3 else "G"
