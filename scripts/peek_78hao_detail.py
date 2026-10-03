"""打开 78 号文详情页，验证正文确实是我们需要的政策。

这一步是 P0 的关键：如果详情页正文含七段式 + 可判定条件，
说明**数据源成立、Phase 1 不需要重新设计**。

用法：python scripts/peek_78hao_detail.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bs4 import BeautifulSoup  # noqa: E402
from src.ingest.crawl import fetch_html  # noqa: E402

URL = "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/202206/t20220608_1983869.shtml"

# 我们关心的关键词（决定这个源能不能支撑"条件判定"）
KEYWORDS = [
    "武政办",
    "武房规",
    "人才租赁房",
    "不高于市场租金的70%",
    "免缴2年",
    "毕业6年",
    "2022年6月7日",
    "社会保险",
    "无自有住房",
    "申报对象",
    "申请材料",
    "受理部门",
]

# 七段式的七个段落名（实测有变体，所以只作参考）
SEVEN = ["政策内容", "申报对象", "补贴标准", "文件依据", "申请材料", "业务流程", "受理部门"]

print(f"抓取：{URL}")
print()

html = fetch_html(URL)
print(f"页面长度：{len(html):,} 字符")

soup = BeautifulSoup(html, "lxml")

# 提取 <title>（这也在验证 wb 的方案 A）
t = soup.find("title")
print(f"<title>：{t.get_text(strip=True) if t else '(无)'}")
print()

# 去脚本样式，取正文
for tag in soup(["script", "style"]):
    tag.decompose()

# 政府网站正文容器实测是 TRS_Editor
editor = soup.find(class_="TRS_Editor")
if editor:
    text = editor.get_text(separator="\n", strip=True)
    print(f"✅ 找到正文容器 TRS_Editor，纯文本 {len(text):,} 字")
else:
    text = soup.get_text(separator="\n", strip=True)
    print(f"⚠️  未找到 TRS_Editor 容器，退回全页文本（{len(text):,} 字）")

print()
print("=" * 78)
print("关键词命中（决定这个源能否支撑条件判定）")
print("=" * 78)
for kw in KEYWORDS:
    mark = "✅" if kw in text else "❌"
    print(f"  {mark} {kw}")
print()

print("=" * 78)
print("七段式段落（实测有变体，仅供参考）")
print("=" * 78)
for s in SEVEN:
    mark = "✅" if s in text else "❌"
    print(f"  {mark} {s}")
print()

print("=" * 78)
print("正文前 2000 字")
print("=" * 78)
print(text[:2000])
