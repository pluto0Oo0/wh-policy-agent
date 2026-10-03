"""验证 wb 的 P0 建议：换的源对不对，有没有更好的源。

wb 的实测结论：90 条里只有 1 条跟大学生相关。
它的推断：szfwj/bgtwj 只收市政府本级发文，
         而大学生政策是市人社局/市房管局的部门发文，不在里面。

本脚本验证三件事：
  1. 复核 wb 的实测（90 条相关度）—— 确认它没数错
  2. 验证 wb 的推断（部门栏目是否存在）
  3. 验证两个硬指标（能不能检索到武房规〔2018〕2号 / 武政办〔2022〕78号）

用法：python scripts/verify_sources_p0.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIST_JSONL = PROJECT_ROOT / "data" / "processed" / "list.jsonl"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ══════════════════════════════════════════════════════════════
# 1. 复核 wb 的实测：90 条里有多少条跟大学生相关
# ══════════════════════════════════════════════════════════════
print("=" * 74)
print("一、复核 wb 的实测（90 条相关度）")
print("=" * 74)
print()

records = []
with LIST_JSONL.open(encoding="utf-8") as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

print(f"总条数：{len(records)}")
print()

KEYWORDS = [
    "大学生", "毕业生", "高校", "租赁房", "安居", "落户",
    "创业", "就业", "社保", "人才", "住房", "补贴", "见习",
]

print("关键词命中统计：")
for kw in KEYWORDS:
    hits = [r for r in records if kw in r["title"]]
    mark = "  " if len(hits) <= 1 else "★ "
    print(f"  {mark}{kw:<8} {len(hits):>3} 条")
    for h in hits[:3]:
        shown = h["title"][:56]
        print(f"        {shown}")
print()

# ══════════════════════════════════════════════════════════════
# 2. 验证 wb 的推断：部门网站有没有独立政策栏目
# ══════════════════════════════════════════════════════════════
print("=" * 74)
print("二、验证 wb 的推断：部门网站是否有独立政策栏目")
print("=" * 74)
print()

DEPARTMENTS = [
    ("市人社局", "https://rsj.wuhan.gov.cn/"),
    ("市住房和城市更新局", "https://zgj.wuhan.gov.cn/"),
    ("市人才工作网", "https://dsj.whrcgz.gov.cn/"),
]


def probe(name: str, url: str) -> None:
    print(f"── {name}：{url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        if r.status_code != 200:
            print(f"   ❌ HTTP {r.status_code}")
            print()
            return
        html = r.text
        print(f"   ✅ {len(html):,} 字符")

        # 找"政策"相关的栏目链接
        cols = re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>([^<]{2,30}(?:政策|文件|通知|公告|申报)[^<]{0,20})</a>',
            html,
        )
        if cols:
            seen = set()
            print("   含'政策/文件/通知'的栏目链接：")
            for href, text in cols:
                key = text.strip()
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > 12:
                    break
                print(f"     [{key}]")
                print(f"       {href}")
        else:
            print("   未找到明显政策栏目")
    except Exception as e:
        print(f"   ❌ {type(e).__name__}: {e}")
    print()


for name, url in DEPARTMENTS:
    probe(name, url)

# ══════════════════════════════════════════════════════════════
# 3. 硬指标验证：能否检索到两个关键文号
# ══════════════════════════════════════════════════════════════
print("=" * 74)
print("三、硬指标：两个 grandfathering 关键文号")
print("=" * 74)
print()

TARGETS = ["武房规〔2018〕2号", "武政办〔2022〕78号"]
for t in TARGETS:
    hits = [r for r in records if t in r["title"]]
    print(f"  {t}：在 90 条里命中 {len(hits)} 条")
print()
print("  → 注：这符合 wb 的推断（源层级不对），但需确认其他源能否找到")
