"""看清 szfwj 列表页的数据是怎么组织的。

已确认：.shtml 链接存在于 HTML 源码中（19 个），但不在 <a> 标签里，
说明数据放在 JavaScript 变量里。本脚本定位这个结构，为正式解析做准备。

用法：python scripts/inspect_jsdata.py
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

URL = "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/"

r = requests.get(URL, headers=HEADERS, timeout=30)
r.encoding = "utf-8"
html = r.text

# 找到每个 .shtml 路径周围 400 字符的上下文，看数据结构
print("=" * 78)
print("第一个政策链接周围的源码上下文：")
print("=" * 78)

m = re.search(r'\./202609/t20260917_2849324\.shtml', html)
if m:
    start = max(0, m.start() - 500)
    end = min(len(html), m.end() + 300)
    print(html[start:end])
else:
    print("没找到目标链接")

print()
print("=" * 78)
print("搜可能的 JS 变量名（存放列表数据的容器）：")
print("=" * 78)

# 政府网站常见的存放方式：var 变量名 = "[{...}]"
for pattern in [
    r"var\s+(\w+)\s*=\s*[\"']?\[",
    r"var\s+(\w+)\s*=",
    r"(\w+)\s*:\s*[\"']\./20\d{2}",
]:
    found = re.findall(pattern, html)
    if found:
        print(f"  模式 {pattern!r} → {list(dict.fromkeys(found))[:15]}")
