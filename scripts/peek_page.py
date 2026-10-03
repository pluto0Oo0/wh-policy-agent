"""看一眼：这个页面里到底有什么。

不是正式代码，只是一次"侦察"——确认这个页面是不是我们要的数据源。
正式解析会在 SPEC 的模块 4（parse.py）里做。

用法：python scripts/peek_page.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from src.ingest.crawl import POLICY_LIST_URL, fetch_html

# 这些词出现在链接文字里，说明它可能是一条政策
POLICY_KEYWORDS = ["政策", "补贴", "住房", "毕业生", "落户", "创业", "就业", "人才", "社保"]

print(f"正在抓取：{POLICY_LIST_URL}")
html = fetch_html(POLICY_LIST_URL)

soup = BeautifulSoup(html, "lxml")
all_links = soup.find_all("a", href=True)

print(f"页面共 {len(all_links)} 个链接")
print()

# 只挑"链接文字里含政策关键词"的
hits = []
for a in all_links:
    text = a.get_text(strip=True)
    if not text or len(text) < 4:
        continue
    if any(kw in text for kw in POLICY_KEYWORDS):
        hits.append((text, a["href"]))

print(f"其中像政策的有 {len(hits)} 条")
print("=" * 78)

for text, href in hits[:35]:
    # 文字太长截断，方便看
    shown = text if len(text) <= 46 else text[:46] + "…"
    print(f"· {shown}")
    print(f"  {href}")
