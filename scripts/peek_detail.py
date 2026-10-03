"""看一眼单条政策的正文长什么样。

目的：确认详情页有没有调研报告说的「七段式」结构
      （政策内容 / 申报对象及条件 / 补贴标准 / 文件依据 / 申请材料 / 业务流程 / 受理部门）

这是能不能做"条件判定"的前提——如果条件不在正文里，整个项目不成立。

用法：python scripts/peek_detail.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from src.ingest.crawl import fetch_html

# 人才租赁房租金减免 —— MVP 的核心政策
DETAIL_URL = (
    "https://www.wuhan.gov.cn/ztzl/23zt/jzwh/zcqd/zf/202308/t20230802_2241617.shtml"
)

# 七段式的七个段落名
SEVEN_SECTIONS = [
    "政策内容",
    "申报对象及条件",
    "补贴标准",
    "文件依据",
    "申请材料",
    "业务流程",
    "受理部门",
]

print(f"正在抓取：{DETAIL_URL}")
html = fetch_html(DETAIL_URL)
print(f"页面长度：{len(html)} 字符")
print()

soup = BeautifulSoup(html, "lxml")

# 去掉脚本和样式，只留正文文字
for tag in soup(["script", "style"]):
    tag.decompose()
text = soup.get_text(separator="\n", strip=True)

print("=" * 78)
print("七段式段落检查")
print("=" * 78)
for name in SEVEN_SECTIONS:
    mark = "✅" if name in text else "❌"
    print(f"  {mark} {name}")

print()
print("=" * 78)
print("正文前 1500 字")
print("=" * 78)
print(text[:1500])
