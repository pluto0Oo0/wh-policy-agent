"""爬取模块 —— 从武汉市政府网站抓政策列表。

════════════════════════════════════════════════════════════════
本模块的两个"防坑"设计（都是实测踩出来的，见 docs/抓取自检清单.md）
════════════════════════════════════════════════════════════════

【坑 1】列表数据不在 <a> 标签里，在 inline JavaScript 里
    实测 szfwj 列表页有 286 个 <a> 标签，只有 4 个含 .shtml（还都是框架链接）。
    真正的政策列表长这样：
        <script>
          var url = "./202609/t20260917_2849324.shtml"
          var title = "市人民政府关于印发……的通知"
        </script>
    → 所以必须用正则提取，不能用 find_all("a")。
    → 用 find_all("a") 的后果是"一条都抓不到，而且不报错"。

【坑 2】分页 URL 拼错不会报错
    index_1.shtml（正确）→ 15 条
    index1.shtml （少一个下划线）→ HTTP 200、188898 字符、但 0 条政策
    → 所以每一页都必须断言条数，抓到 0 条直接报错。

════════════════════════════════════════════════════════════════
"""

import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ── 两个主源（2026-09-24 实测确认可用）──────────────────────
# bgtwj（办公厅文件）排在前：实测它最新（15 条全是 2026），而政策多由办公厅印发
SOURCES = {
    "bgtwj": {
        "name": "办公厅文件",
        "url": "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/",
    },
    "szfwj": {
        "name": "市政府文件",
        "url": "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/",
    },
}

# 每页实测 15 条。设成 10 而不是 15，是留一点余量——
# 万一某页有 2-3 条是"占位空记录"被正则跳过，不至于误报。
MIN_RECORDS_PER_PAGE = 10

# 请求间隔（秒）。合规要求，也是自检清单的一部分：
# 不做高频抓取，避免给对方服务器压力。
REQUEST_DELAY = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── 列表记录正则 ────────────────────────────────────────────
# 为什么这么写：
#   1. url 和 title 之间隔着若干行 JS 代码，用 .{0,400}? 非贪婪跨过
#   2. re.DOTALL 让 . 能匹配换行符，否则跨行就失效
#   3. re.IGNORECASE 因为不知道站方哪天把 var 写成 VAR
#   4. 只匹配 ./YYYYMM/tYYYYMMDD_ID.shtml 这个形态，避免抓到别的链接
RECORD_PATTERN = re.compile(
    r'url\s*=\s*"(\./\d{6}/t\d{8}_\d+\.shtml)"'  # 链接
    r".{0,400}?"  # 中间的 JS 代码
    r'title\s*=\s*"([^"]{4,200})"',  # 标题
    re.DOTALL | re.IGNORECASE,
)


class CrawlError(Exception):
    """爬取过程中的可预期错误。

    为什么单独定义一个异常类：
        调用方可以明确区分"我知道会出这类错"和"出了意料之外的错"，
        前者可以针对性重试，后者应该让程序崩掉以暴露问题。
    """


def page_url(source_key: str, page: int) -> str:
    """拼出第 N 页的地址。

    实测规律：
        第 1 页  = {栏目}/
        第 N 页  = {栏目}/index_{N-1}.shtml      ← 注意下划线！

    参数：
        source_key: "bgtwj" 或 "szfwj"
        page:       页码，从 1 开始

    返回：
        完整的页面 URL
    """
    if source_key not in SOURCES:
        raise CrawlError(f"未知数据源：{source_key}，可选：{list(SOURCES)}")

    base = SOURCES[source_key]["url"]

    if page == 1:
        return base

    # 页码从 0 开始编号：第 2 页是 index_1.shtml
    return f"{base}index_{page - 1}.shtml"


def fetch_html(url: str, timeout: int = 30) -> str:
    """请求一个 URL，返回网页源码。

    参数：
        url:     要抓的地址
        timeout: 超时秒数

    返回：
        网页源码字符串

    抛出：
        CrawlError: 网络失败、HTTP 非 200、或返回内容异常
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.RequestException as e:
        raise CrawlError(f"请求失败：{url} → {type(e).__name__}: {e}") from e

    # 为什么必须 raise_for_status：
    # requests 对 404/500 默认不报错，会照常返回内容（内容是错误页面）。
    # 不检查的话，后面解析得到一堆莫名其妙的结果，很难定位问题。
    if resp.status_code != 200:
        raise CrawlError(f"HTTP {resp.status_code}：{url}")

    # 政府网站基本都是 UTF-8。不显式指定的话 requests 可能猜成
    # ISO-8859-1，导致中文全变乱码。
    resp.encoding = "utf-8"
    html = resp.text

    # ── 只拦"根本不像网页"的响应 ────────────────────────────
    # ⚠️ 这**不是**软 404 判据，别把它当成一个。
    #
    # 2026-10-04 实测修正：这条原来是 `len(html) < 1000`，注释写着"疑似软 404"——
    # 但它**一条都拦不住**：市级站的真实失效页有 **190,250 字符**
    # （站点首页/错误页的完整渲染，比正常页 115,672 还长）。
    # → **一个永远不会触发的检查，和没有这个检查是同一件事。**
    #
    # 保留它的唯一理由：拦 SPEC §2.5 记过的那种「82 字符 JS 跳转页」
    # （`zcqd/` 的失效方式）。阈值取 500，只拦"根本不像网页"的响应。
    # 真正的软 404 判据在 `is_soft_404()`，且**只适用于详情页**。
    if len(html) < 500:
        raise CrawlError(
            f"响应只有 {len(html)} 字符，不像正常网页：{url}\n"
            f"内容片段：{html.strip()[:150]}"
        )

    return html


def parse_list(html: str, url: str) -> list[dict]:
    """从列表页 HTML 里抽出所有政策记录。

    参数：
        html: 列表页源码
        url:  该页地址（用于报错时定位）

    返回：
        [{"url": 完整链接, "title": 标题, "path": 相对路径}, ...]

    抛出：
        CrawlError: 一条都没抽到（结构变了，不能继续）
    """
    records = []
    for path, title in RECORD_PATTERN.findall(html):
        records.append(
            {
                "path": path,  # "./202609/t20260917_2849324.shtml"
                "title": title.strip(),
                "url": _absolute_url(url, path),
            }
        )

    # ── 断言：抓到 0 条必须报错 ────────────────────────────
    # 为什么不能返回空列表：
    #   静默返回空 → 上层以为"这页没数据" → 继续抓下一页 →
    #   最后得到不完整的语料，而且完全不知道问题出在哪一页。
    #   报错的话，问题在发生的地方就暴露了。
    if not records:
        raise CrawlError(
            f"本页抽到 0 条记录，页面结构可能已改版：{url}\n"
            f"排查线索：源码里 'var url' 出现 {html.count('var url')} 次，"
            f"'var title' 出现 {html.count('var title')} 次"
        )

    return records


def _absolute_url(page_url: str, relative: str) -> str:
    """把 "./202609/xxx.shtml" 拼成完整 URL。

    为什么手写而不是用 urljoin：
        urljoin 对 "./202609/xxx.shtml" 的处理依赖当前页是否以 / 结尾，
        这里页面规律明确（都是目录形式），手写更直观可控。
    """
    # 去掉结尾的 index_N.shtml，只保留目录部分
    base = re.sub(r"index_\d+\.shtml$", "", page_url)
    base = base.rstrip("/")

    # 去掉相对路径开头的 ./
    rel = re.sub(r"^\./", "", relative)

    return f"{base}/{rel}"


def crawl_list(source_key: str, pages: int = 1) -> list[dict]:
    """抓取一个数据源的前 N 页列表。

    参数：
        source_key: "bgtwj" 或 "szfwj"
        pages:      抓几页，从 1 开始数

    返回：
        所有记录，每条含 source / page / url / title

    抛出：
        CrawlError: 任何一页失败
    """
    source_name = SOURCES[source_key]["name"]
    all_records = []

    for page in range(1, pages + 1):
        url = page_url(source_key, page)

        html = fetch_html(url)
        records = parse_list(html, url)

        # ── 断言：每页条数不能太少 ─────────────────────────
        if len(records) < MIN_RECORDS_PER_PAGE:
            raise CrawlError(
                f"{source_name} 第 {page} 页只抽到 {len(records)} 条"
                f"（预期 ≥{MIN_RECORDS_PER_PAGE} 条）：{url}\n"
                f"可能是分页地址拼错，或页面结构已变。"
            )

        for r in records:
            r["source"] = source_key
            r["page"] = page
        all_records.extend(records)

        # 进度打印（自检清单要求）
        print(f"  [{source_name}] 第 {page} 页 → {len(records)} 条")

        # 合规延迟：最后不 sleep，避免白等 1 秒
        if page < pages:
            time.sleep(REQUEST_DELAY)

    return all_records


# ══════════════════════════════════════════════════════════════
# 详情页 · 抓一条政策的完整内容（SPEC §2.1 契约）
# 全部判据都是 2026-10-04 对 78 号文实测标定的
# ══════════════════════════════════════════════════════════════

# 站点名。失效页的 <title> 就是它，不带任何后缀。
SITE_NAME = "武汉市人民政府门户网站"

# 正常详情页的 <title> 形如：
#   「市人民政府办公厅关于……的通知 - 武汉市人民政府门户网站」
# 失效页形如：「武汉市人民政府门户网站」
SITE_TITLE_SUFFIX = f" - {SITE_NAME}"

# 正文容器类名。⚠️ **只存在于市级站**，换站点必须重新标定。
DETAIL_CONTAINER = "TRS_Editor"

# 元数据块。先切出 articleInfo 再匹配，是因为整页有几百个 <li>
# （导航、相关链接），全局匹配会抓到无关条目。
INFO_BLOCK_PATTERN = re.compile(r'class="articleInfo">(.*?)</ul>', re.S)
INFO_ITEM_PATTERN = re.compile(r"<li>\s*([^：<]{2,12})：\s*([^<]*?)\s*</li>", re.S)

TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def _extract_title(html: str) -> str:
    """抽出 <title> 原文（**不**去后缀，判软 404 需要原始值）。"""
    m = TITLE_PATTERN.search(html)
    return m.group(1).strip() if m else ""


def _strip_site_suffix(title: str) -> str:
    """去掉标题尾部的「 - 武汉市人民政府门户网站」。

    为什么必须剥：实测所有正常详情页都带这个后缀，不剥的话写进
    `policies.jsonl` 的 title 会变成「……通知 - 武汉市人民政府门户网站」，
    和列表页抓到的标题对不上，后续按标题去重/比对全部失效。
    """
    if title.endswith(SITE_TITLE_SUFFIX):
        return title[: -len(SITE_TITLE_SUFFIX)].strip()
    return title.strip()


def is_soft_404(html: str, url: str) -> str | None:
    """判断详情页是不是「软 404」—— HTTP 200，但页面其实不存在。

    返回：
        None   正常页
        str    失效原因（可直接拿去报错）

    为什么必须专门判：失效地址返回 **HTTP 200 + 一整页内容**，
    requests 不报错、`raise_for_status()` 也不报错。不判就会静默拿到垃圾。

    ⚠️ 三条边界，全部是 2026-10-04 实测标定的，**换条件就会失效**：

    1. **只适用于详情页。** 列表页的容器计数天然是 0
       （实测 `zcwd` 列表页 `TRS_Editor` 0 次），拿这条判列表页
       会把正常页全判成失效 → 假警报。

    2. **只适用于市级站 `wuhan.gov.cn`。** 实测 `hanyang.gov.cn`
       的 `TRS_Editor` 是 0 次，且它的失效页返回**真 HTTP 404**；
       `rsj.wuhan.gov.cn` 用别的容器类名。**换站点必须重新标定。**

    3. **绝对不要用长度判断。** 实测失效页 **190,250 字符**，
       比正常页（115,672）**还长**——它是站点首页/错误页的完整渲染，
       页眉页脚导航一样不少。**所有长度阈值在这个站上都无效。**
    """
    title = _extract_title(html)

    # 判据 1（最硬，布尔无阈值）：title 退化成纯站点名
    if title.strip() == SITE_NAME:
        return f"页面不存在（title 退化成站点名）：{url}"

    # 判据 2：title 里没有「 - 」分隔符。
    # 留这条是为了容忍站点改名 —— 那时判据 1 会失效，这条还成立。
    if " - " not in title:
        return f"页面不存在（title 无站点后缀）：{url}"

    # 判据 3：没有正文容器（布尔，无阈值）
    if html.count(DETAIL_CONTAINER) == 0:
        return f"页面不存在（无正文容器 {DETAIL_CONTAINER}）：{url}"

    return None


def _extract_meta(html: str) -> dict[str, str]:
    """抽「索引号 / 发文机构 / 发文字号 / 成文日期」元数据块。

    返回**原始字符串**，不做格式转换、不编造；抽不到就是空串。
    """
    m = INFO_BLOCK_PATTERN.search(html)
    if not m:
        return {}
    return {k.strip(): v.strip() for k, v in INFO_ITEM_PATTERN.findall(m.group(1))}


def _to_iso_date(raw: str) -> str:
    """把「2022年06月07日」转成「2022-06-07」；转不了返回空串。

    为什么失败要返回空串而不是编一个日期：
        SPEC §2.1 明确写「缺失填 `""`」—— 实测约 1/4 页面无可靠日期。
        **不允许为了填满字段而编造日期。**
    """
    m = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw.strip())
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _extract_body_text(html: str) -> str:
    """抽出正文纯文本。

    ⚠️ **临时实现**。SPEC §4 把正式清洗放在 `src/ingest/clean.py`（模块 3），
    到那一轮会把本函数移过去，并补上页眉页脚剔除、模板族识别。
    现在必须先能拿到正文，因为 SPEC §2.1 要求 `content` 必填。

    为什么用 BeautifulSoup 而不是正则找 </div>：
        正文容器里面嵌了多层 div，正则配非贪婪会提前截断。
    """
    soup = BeautifulSoup(html, "lxml")
    box = soup.find("div", class_=DETAIL_CONTAINER)
    if box is None:
        return ""

    # TRS_Editor 的第一个子元素是 <style>，不去掉的话正文里会混进一大段 CSS
    for tag in box(["style", "script"]):
        tag.decompose()

    text = box.get_text(separator="\n")
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _doc_id_from_url(url: str) -> str:
    """从详情页 URL 末段取 doc_id。

    实测形态：`.../202206/t20220608_1983869.shtml` → `t20220608_1983869`
    """
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail[: -len(".shtml")] if tail.endswith(".shtml") else tail


def _detect_template_family(html: str) -> str:
    """识别模板族（SPEC §3.3）。

    ⚠️ **占位实现，恒返回 "G"**。SPEC §5 规定「无法判定返回 G」，
    所以这不是编造，是规范允许的降级值。

    为什么现在不做真实现：
        §3.3 的 A~G 是从 **33 个区级页面**归纳出来的，而本函数当前要处理的是
        **市级红头文件** —— 它不在这套分类里。
        （2026-10-04 wb 实测：78 号文的「受理 / 申报对象 / 申请材料」全部 0 次，
         它压根没有七段式。）
        真正该先决定的是「**这套分类要不要扩一类『市级红头文件』**」——
        那是 SPEC 层面的决定，不该由代码顺手定了。
    """
    return "G"


def crawl_detail(url: str) -> dict:
    """抓一个政策详情页，返回 SPEC §2.1 契约的全部字段。

    参数：
        url: 详情页完整地址

    返回：
        §2.1 契约 dict

    抛出：
        CrawlError: 网络失败 / HTTP 非 200 / 软 404 / 抽不到正文

    为什么失败要抛异常而不是返回空 dict：
        返回空 dict 的调用方会把它当成"这条政策没有内容"存进库，
        **错误就此静默固化**。宁可让程序崩掉。
    """
    html = fetch_html(url)

    # 软 404 只在详情页判 —— 边界见 is_soft_404 的说明
    reason = is_soft_404(html, url)
    if reason:
        raise CrawlError(reason)

    body = _extract_body_text(html)
    # 抽不到正文 = 页面结构变了。必须报错，不能存一条空 content 进库。
    if not body:
        raise CrawlError(
            f"抽不到正文（容器 {DETAIL_CONTAINER} 里是空的）：{url}\n"
            f"多半是页面改版了，请人工看一眼。"
        )

    meta = _extract_meta(html)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    return {
        "doc_id": _doc_id_from_url(url),
        "url": url,
        "title": _strip_site_suffix(_extract_title(html)),
        "doc_number": meta.get("发文字号", ""),
        "publish_date": _to_iso_date(meta.get("成文日期", "")),
        "region": "市级",
        "template_family": _detect_template_family(html),
        "content": body,
        "crawled_at": now,
        # ── 政策有效性（SPEC §2.1 / §3.5b）────────────────────
        # 默认填「未核实」，**不编造**。有效性核实是独立流程，
        # 不能由爬虫顺手填「现行」—— 那等于把"没查过"伪装成"查过了"。
        "policy_status": "未核实",
        "status_verified_at": now,
        "status_evidence": "",
        "superseded_by": None,
        "source_role": "content",
    }


if __name__ == "__main__":
    print("=" * 70)
    print("爬取测试：各抓 2 页，看能不能拿到数据")
    print("=" * 70)
    print()

    for key in SOURCES:
        print(f"── {SOURCES[key]['name']} ──")
        try:
            records = crawl_list(key, pages=2)
            print(f"  合计 {len(records)} 条")

            # ── 自检：抽 3 条打印出来人工看 ────────────────
            # 只看"跑了多少条"不算验证，必须看到内容对不对。
            print("  ── 抽样 3 条 ──")
            for r in records[:3]:
                title = r["title"]
                shown = title if len(title) <= 50 else title[:50] + "…"
                print(f"    {shown}")
        except CrawlError as e:
            print(f"  ❌ {e}")
        print()
