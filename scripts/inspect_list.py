"""看看 szfwj 列表页到底是什么结构（为什么正则抓不到链接）。

用法：python scripts/inspect_list.py
"""

import re
import sys
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

URL = "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/"

r = requests.get(URL, headers=HEADERS, timeout=30)
r.encoding = "utf-8"
html = r.text

print(f"页面长度：{len(html)} 字符")
print()

soup = BeautifulSoup(html, "lxml")

# 1. 所有 <a> 标签，看 href 都长什么样
links = soup.find_all("a", href=True)
print(f"<a> 标签共 {len(links)} 个")
print()

# 按 href 特征归类
shtml = [a for a in links if ".shtml" in a["href"]]
js = [a for a in links if a["href"].startswith("javascript")]
other = [a for a in links if a not in shtml and a not in js]

print(f"  含 .shtml 的：{len(shtml)} 个")
print(f"  javascript: 的：{len(js)} 个")
print(f"  其他的：{len(other)} 个")
print()

print("=" * 78)
print("前 25 个 .shtml 链接（文字 + href）：")
print("=" * 78)
for a in shtml[:25]:
    text = a.get_text(strip=True)
    print(f"· [{text[:44] or '(无文字)'}]")
    print(f"  {a['href']}")
print()

print("=" * 78)
print("前 10 个 javascript 链接（可能是分页/异步加载）：")
print("=" * 78)
for a in js[:10]:
    text = a.get_text(strip=True)
    print(f"· [{text[:40]}] {a['href'][:100]}")
print()

# 2. 页面里有没有 iframe / 明显的 JS 数据源
print("=" * 78)
print("页面里的 iframe：")
print("=" * 78)
for f in soup.find_all("iframe"):
    print(" ", f.get("src"))

# 3. 搜一下页面里有没有 ".shtml" 的字符串（可能在 JS 变量里）
print()
print("=" * 78)
print("HTML 源码里 .shtml 出现次数：", html.count(".shtml"))
print("=" * 78)
all_shtml_in_src = re.findall(r'["\']([^"\']*?\.shtml)["\']', html)
print(f"源码中引号包裹的 .shtml 路径：{len(all_shtml_in_src)} 个")
for s in all_shtml_in_src[:15]:
    print("  ", s)
