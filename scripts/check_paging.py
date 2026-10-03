"""验证分页规律 + 摸清 zcwd 的结构。

自检清单第 1 条：**先验证，不假设。**

两件事：
  1. szfwj / bgtwj 的第 2、3 页怎么翻？每页几条？会不会翻到重复内容？
  2. zcwd（政策问答）为什么抽不到？它的结构是什么？

用法：python scripts/check_paging.py
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

RECORD_PATTERN = re.compile(
    r'url\s*=\s*"(\./\d{6}/t\d{8}_\d+\.shtml)"'
    r".{0,400}?"
    r'title\s*=\s*"([^"]{4,200})"',
    re.DOTALL,
)


def get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = "utf-8"
    r.raise_for_status()
    return r.text


# ══════════════════════════════════════════════════════════════
# 一、分页验证
# ══════════════════════════════════════════════════════════════
print("=" * 78)
print("一、分页规律验证（以 szfwj 为例）")
print("=" * 78)
print()

BASE = "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/"

# 政府网站常见的两种分页：index_1.shtml 或 index1.shtml
PAGE_URLS = [
    ("第1页（目录）", BASE),
    ("index_1.shtml", BASE + "index_1.shtml"),
    ("index1.shtml", BASE + "index1.shtml"),
    ("index_2.shtml", BASE + "index_2.shtml"),
]

collected = {}
for label, url in PAGE_URLS:
    try:
        html = get(url)
        records = RECORD_PATTERN.findall(html)
        collected[label] = records

        years = [re.search(r"t(20\d{2})\d{4}_", p).group(1) for p, _ in records]
        dist = dict(sorted(Counter(years).items(), reverse=True)) if years else {}

        print(f"  {label:<18} {len(html):>7} 字符  抽到 {len(records):>3} 条  年份 {dist}")

        if records:
            # 打印首尾各一条，看排序和是否重复
            print(f"      首条: {records[0][1][:44]}")
            print(f"      末条: {records[-1][1][:44]}")
    except Exception as e:
        print(f"  {label:<18} ❌ {type(e).__name__}: {e}")
    print()

# 判断是否重复
if len(collected) >= 2:
    print("  分页是否重复检查：")
    keys = list(collected.keys())
    for i in range(len(keys) - 1):
        a = set(p for p, _ in collected[keys[i]])
        b = set(p for p, _ in collected[keys[i + 1]])
        overlap = len(a & b)
        print(f"    {keys[i]} ∩ {keys[i+1]}: 重复 {overlap} 条")
    print()

# ══════════════════════════════════════════════════════════════
# 二、zcwd 结构
# ══════════════════════════════════════════════════════════════
print("=" * 78)
print("二、政策问答 zcwd 的结构（为什么抽不到）")
print("=" * 78)
print()

ZCWD = "https://www.wuhan.gov.cn/zwgk/xxgk/zcwd/"
html = get(ZCWD)
soup = BeautifulSoup(html, "lxml")

# 它有多少个 .shtml 的 <a>？这些是什么？
a_shtml = soup.find_all("a", href=re.compile(r"\.shtml"))
print(f"  含 .shtml 的 <a> 标签：{len(a_shtml)} 个")
print()
print("  前 12 个：")
for a in a_shtml[:12]:
    text = a.get_text(strip=True)
    print(f"    [{text[:40] or '(无文字)'}]")
    print(f"      {a['href']}")
print()

# 找找它的记录容器 —— 常见 class 名
print("  搜可能的列表容器 class：")
for cls in ["list", "news", "item", "content", "main"]:
    found = soup.find_all(class_=re.compile(cls, re.I))
    if found:
        print(f"    class 含 '{cls}': {len(found)} 个")
print()

# 直接看页面上有没有"问答"式内容
text = soup.get_text(separator="\n", strip=True)
print(f"  页面纯文本长度：{len(text)} 字符")
print()
print("  ── 纯文本前 800 字 ──")
print(text[:800])
