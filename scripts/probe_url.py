"""临时探针：确认政策清单页现在到底在哪个地址。

背景：SPEC 里记录的 `https://www.wuhan.gov.cn/ztzl/23zt/jzwh/zcqd/`
实测返回的是一段 JavaScript 跳转代码，不是页面内容。

本脚本依次尝试几个候选地址，打印每个的真实结果，用来定位正确入口。
定位完成后本文件可删除。
"""

import sys
from pathlib import Path

# 让脚本能 import 到项目里的 src 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.crawl import fetch_html

CANDIDATES = [
    # 原始地址（已知会返回 JS 跳转）
    "https://www.wuhan.gov.cn/ztzl/23zt/jzwh/zcqd/",
    # JS 跳转指向的地址
    "https://www.wuhan.gov.cn/ztzl/23zt/jzwh/?itemid=86601",
    # 上一级目录
    "https://www.wuhan.gov.cn/ztzl/23zt/jzwh/",
]

for url in CANDIDATES:
    print("=" * 70)
    print("URL:", url)
    try:
        html = fetch_html(url)
        print(f"长度: {len(html)} 字符")

        # 判断是不是又是 JS 跳转
        if "window.location" in html and len(html) < 500:
            print("⚠️  又是 JS 跳转:", html.strip().replace("\n", " "))
        else:
            # 数一下页面里有多少个链接，粗略判断是不是列表页
            link_count = html.count("<a ")
            print(f"页面内 <a> 标签数: {link_count}")
            # 找找有没有"政策"字样
            for kw in ["政策", "补贴", "毕业生", "住房", "清单"]:
                if kw in html:
                    print(f"  含关键词: {kw}")
            print("片段:", html[:200].replace("\n", " "))
    except Exception as e:
        print(f"❌ 失败: {type(e).__name__}: {e}")
    print()
