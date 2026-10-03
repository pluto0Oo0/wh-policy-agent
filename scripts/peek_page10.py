"""取 bgtwj 第 10 页的全部条目，人工确认目标文件。

背景：verify_78hao.py 报"未找到目标文件"，但第 10 页命中了「高校毕业生」。
原因：列表页**只有标题，不含文号**（文号在详情页里），
      所以用文号去搜列表页必然搜不到 —— 这是脚本的判断逻辑问题，不是数据问题。

本脚本直接列出第 10 页所有 15 条，人眼一看就知道。

用法：python scripts/peek_page10.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.crawl import RECORD_PATTERN, fetch_html  # noqa: E402

BASE = "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/"
URL = f"{BASE}index_9.shtml"  # 第 10 页 = index_9.shtml

print(f"抓取：{URL}")
print()

html = fetch_html(URL)
records = RECORD_PATTERN.findall(html)

print("=" * 78)
print(f"bgtwj 第 10 页 · 共 {len(records)} 条")
print("=" * 78)
print()

for i, (path, title) in enumerate(records, 1):
    # 从路径里提取日期
    m = re.search(r"t(\d{4})(\d{2})(\d{2})_", path)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "?"

    # 高亮可能相关的
    mark = "  ★" if any(k in title for k in ["高校毕业生", "大学生", "人才", "租赁", "毕业生"]) else ""

    print(f"  {i:>2}. [{date}] {title}{mark}")
    print(f"      {BASE}{path.lstrip('./')}")
print()

# 统计
hits = [t for _, t in records if any(k in t for k in ["高校毕业生", "大学生", "人才", "租赁", "毕业生"])]
print(f"含目标关键词的：{len(hits)} 条")
for t in hits:
    print(f"  · {t}")
