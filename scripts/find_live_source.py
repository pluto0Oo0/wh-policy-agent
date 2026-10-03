"""核查：这个网站有没有"活"的大学生政策栏目。

上一步已确认：「就」在武汉专题页（jzwh）内容停在 2023 年，是死数据。
现在要找的是 —— 有没有在持续更新的官方栏目。

检查对象：
1. 武汉市人社局官网
2. 市政府门户的政策文件栏目（已有调研报告提供过路径）
3. 武汉人才工作网接口（调研报告实测过，免登录）
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 直接用 requests，不走 crawl.py（这些不是我们要正式爬的源，只是探测）
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

TARGETS = [
    (
        "武汉市人社局 · 通知公告",
        "https://rsj.wuhan.gov.cn/zwgk_17/zc/tzgg/",
    ),
    (
        "武汉市人社局 · 首页",
        "https://rsj.wuhan.gov.cn/",
    ),
    (
        "市政府 · 政策文件（市政府文件）",
        "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/",
    ),
    (
        "市政府 · 政策文件（办公厅文件）",
        "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/",
    ),
    (
        "市政府 · 政策问答",
        "https://www.wuhan.gov.cn/zwgk/xxgk/zcwd/",
    ),
]


def probe(name: str, url: str) -> None:
    print("=" * 74)
    print(f"{name}")
    print(f"{url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        html = r.text

        if r.status_code != 200:
            print(f"  ❌ HTTP {r.status_code}")
            return

        if "window.location" in html and len(html) < 700:
            print(f"  ⚠️ JS 跳转: {html.strip()[:120]}")
            return

        print(f"  ✅ HTTP 200，{len(html)} 字符")

        # URL 时间戳年份分布 —— 最可靠的"新旧"指标
        years = re.findall(r"t(20\d{2})\d{4}[_.]", html)
        if years:
            dist = Counter(years)
            top = " ".join(f"{y}:{n}" for y, n in sorted(dist.items(), reverse=True)[:6])
            newest = max(dist)
            print(f"  时间戳年份: {top}")
            print(f"  → 最新: {newest}")
        else:
            print("  未找到 URL 时间戳")

        # 有没有"大学生/毕业生"相关内容
        for kw in ["大学生", "毕业生", "人才租赁房", "就业创业"]:
            if kw in html:
                print(f"  含关键词: {kw}")

    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
    print()


for name, url in TARGETS:
    probe(name, url)
