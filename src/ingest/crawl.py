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

import requests

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

    # ── 软 404 检查 ────────────────────────────────────────
    # 实测踩过的坑：失效地址返回的不是 404，而是一段 JS 跳转代码（82 字符）。
    # 程序不报错，静默拿到无意义内容。所以这里主动检查。
    if len(html) < 1000:
        raise CrawlError(
            f"内容过短（{len(html)} 字符），疑似软 404 或跳转页：{url}\n"
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
