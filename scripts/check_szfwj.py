"""核查：市政府政策文件栏目里，有没有"大学生政策"。

上一步已确认 jzwh 专题页是死数据（停在 2023），
现在检查活的数据源（szfwj / bgtwj，最新到 2026）里有没有我们要的内容。

用法：python scripts/check_szfwj.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 调研报告给过的两个活源
SOURCES = [
    ("市政府文件 szfwj", "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/"),
    ("办公厅文件 bgtwj", "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/"),
]

# 判断"这条政策跟大学生有关"的关键词
KEYWORDS = ["毕业生", "大学生", "高校", "人才", "就业", "创业", "租赁房", "社保补贴"]

for name, url in SOURCES:
    print("=" * 78)
    print(name, "→", url)
    print("=" * 78)

    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    html = r.text

    # 列表页里的每条记录一般是 <a href="...">
    # 用正则粗暴抓出所有链接文字 + 链接
    items = re.findall(r'<a[^>]+href="([^"]+\.shtml)"[^>]*>([^<]{6,120})</a>', html)

    print(f"列表页共 {len(items)} 条记录")
    print()

    hits = []
    for href, text in items:
        text = text.strip()
        if any(kw in text for kw in KEYWORDS):
            hits.append((text, href))

    print(f"其中疑似大学生相关：{len(hits)} 条")
    print("-" * 78)
    for text, href in hits[:20]:
        year = ""
        m = re.search(r"t(20\d{2})\d{4}_", href)
        if m:
            year = m.group(1)
        shown = text if len(text) <= 50 else text[:50] + "…"
        print(f"[{year}] {shown}")
    print()
