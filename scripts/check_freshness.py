"""核查：这个政策专题页的内容是不是"死数据"。

要回答的问题：
1. 这个专题里有没有 2024-2026 年的新内容？
2. 那条人才租赁房政策（2023-08-02）现在还有效吗？
   —— 政策文件几年不改是正常的，但页面不更新就不正常
3. 有没有更新的权威源？

用法：python scripts/check_freshness.py
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.crawl import fetch_html

# 政策清单页
LIST_URL = "https://www.wuhan.gov.cn/ztzl/23zt/jzwh/zcqd/"

# 备用：上一级专题页
FALLBACK_URL = "https://www.wuhan.gov.cn/ztzl/23zt/jzwh/"


def year_stats(html: str, label: str) -> None:
    """统计页面里出现的年份分布——能直接看出内容的新旧。"""
    print("=" * 70)
    print(label)
    print("=" * 70)

    # 政府网站 URL 里普遍带 t20230802 这种时间戳，这是最可靠的线索
    url_years = re.findall(r"t(20\d{2})\d{4}_", html)
    if url_years:
        print("URL 时间戳里的年份分布：")
        for y, n in sorted(Counter(url_years).items(), reverse=True):
            print(f"   {y}: {n} 条")
    else:
        print("URL 里没找到时间戳")

    # 页面上显示的文字日期，如 发布id：2023-08-02
    text_years = re.findall(r"(20\d{2})-\d{2}-\d{2}", html)
    if text_years:
        print()
        print("正文日期里的年份分布：")
        for y, n in sorted(Counter(text_years).items(), reverse=True):
            print(f"   {y}: {n} 处")

    print()


print("正在核查内容新鲜度...")
print()

# 1. 先看清单页（注意：这个地址前面实测会返回 JS 跳转，先试一次）
try:
    html_zcqd = fetch_html(LIST_URL)
    if "window.location" in html_zcqd and len(html_zcqd) < 500:
        print(f"⚠️  {LIST_URL} 仍是 JS 跳转，改用上一级目录")
        html_zcqd = fetch_html(FALLBACK_URL)
        label_zcqd = f"清单页（实际取自 {FALLBACK_URL}）"
    else:
        label_zcqd = f"清单页 {LIST_URL}"
except Exception as e:
    print(f"清单页抓取失败：{e}，改用上一级目录")
    html_zcqd = fetch_html(FALLBACK_URL)
    label_zcqd = f"清单页（实际取自 {FALLBACK_URL}）"

year_stats(html_zcqd, label_zcqd)
