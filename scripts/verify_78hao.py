"""验证 wb 的纠正：78 号文到底在不在 bgtwj 里。

wb 实测：武政办〔2022〕78号 在 bgtwj 第 10 页。
CC 此前结论：硬指标 0 命中 → 源不对。

本脚本复核 wb 的实测，并检验那个逻辑漏洞：
    "硬指标 0 命中" 有两种原因：(a) 源不对 (b) 翻页不够

方法：直接把 bgtwj 翻到第 15 页，看目标文件在哪一页。

用法：python scripts/verify_78hao.py
"""

import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

BASE = "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/"

# 每页的标题列表（复用 crawl.py 的正则）
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from ingest.crawl import RECORD_PATTERN  # noqa: E402

# 两个关键文号 / 关键词
TARGETS = {
    "武政办〔2022〕78": "新政策（人才租赁房）",
    "武房规〔2018〕2": "老政策（大学毕业生保障性住房）",
    "高校毕业生": "宽泛关键词",
    "人才租赁房": "宽泛关键词",
}


def get_page(page: int, max_retry: int = 3) -> tuple[str, str]:
    """取第 page 页的 html 和 url。

    为什么要重试：
        实测遇到过 SSLError（SSL: UNEXPECTED_EOF）——**网络瞬时抖动，不是源的问题**。
        这类错误应该自动重试，否则一次抖动就让整个抓取中断。
        （这正是自检清单里"网络层必须捕获 + 重试"的实践）
    """
    url = BASE if page == 1 else f"{BASE}index_{page - 1}.shtml"

    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.encoding = "utf-8"
            r.raise_for_status()
            return r.text, url
        except requests.RequestException as e:
            last_err = e
            if attempt < max_retry:
                wait = 2 ** attempt  # 2, 4 秒退避
                print(f"      (第 {attempt} 次失败：{type(e).__name__}，{wait}s 后重试)")
                time.sleep(wait)

    raise last_err  # 重试用尽才抛


print("=" * 74)
print("复核：武政办〔2022〕78号 在 bgtwj 第几页？")
print("=" * 74)
print()

found_page = None
all_records = []

# 翻到第 15 页（wb 说第 10 页，多翻几页留余量）
for page in range(1, 16):
    try:
        html, url = get_page(page)
    except Exception as e:
        print(f"  第 {page:>2} 页 ❌ {type(e).__name__}: {e}")
        break

    records = RECORD_PATTERN.findall(html)
    if not records:
        print(f"  第 {page:>2} 页 ⚠️  抽到 0 条，停止")
        break

    # 该页最早的日期（判断翻到哪里了）
    dates = [re.search(r"t(\d{8})_", p).group(1) for p, _ in records]
    earliest = min(dates)

    # 本页命中情况
    page_text = " ".join(t for _, t in records)
    hits = [k for k in TARGETS if k in page_text]

    marker = ""
    if "武政办〔2022〕78" in page_text:
        marker = "  ★★ 目标文件在本页！"
        found_page = page
    elif hits:
        marker = f"  命中: {hits}"

    print(f"  第 {page:>2} 页 | {len(records):>3} 条 | 最早 {earliest} |{marker}")

    for p, t in records:
        all_records.append({"page": page, "path": p, "title": t})

    if found_page:
        # 找到后多抓一页即可停
        break

    time.sleep(0.5)

print()
print("=" * 74)
print("结论")
print("=" * 74)
print()

if found_page:
    print(f"✅ 复核结果与 wb 一致：目标文件在【第 {found_page} 页】")
    print()
    print("命中该页的条目：")
    for r in all_records:
        if r["page"] == found_page and "武政办〔2022〕78" in r["title"]:
            print(f"  {r['title']}")
            print(f"  {BASE}{r['path'].lstrip('./')}")
else:
    print("❌ 前 15 页未找到目标文件 —— 需继续往后翻")

print()
print(f"本次共翻 {len(set(r['page'] for r in all_records))} 页，累计 {len(all_records)} 条")
print()

# ── 复核那个逻辑漏洞 ────────────────────────────────────
print("=" * 74)
print("逻辑漏洞复核：硬指标 0 命中 ≠ 源不对")
print("=" * 74)
print()
print("之前我只爬了 3 页（90 条），硬指标 0 命中，就判定'源不对'。")
print("实际原因是：目标文件在更靠后的页。")
print()
print("→ 两种原因，应对完全相反：")
print("   (a) 源不对     → 换源")
print("   (b) 翻页不够   → 继续翻")
print()
print("教训：布尔判断能告诉你'不在'，但不能告诉你'为什么不在'。")
print("      硬指标失败时，必须再查一次失败原因，否则会误杀合格源。")
