"""验证部门网站是否为可用主源（回应 wb 的 P0 建议）。

背景：已确认 szfwj/bgtwj（市政府本级）层级不对——90 条里只有 1 条相关。
wb 的推断：大学生政策是市人社局/市房管局的**部门发文**，不在市政府本级栏目里。

本脚本验证三个部门源，并对每个源做**两道检查**：
  1. 新鲜度（时间戳年份分布）
  2. **相关度**（关键词命中率）← 这正是 wb 建议补进自检清单的那一条

同时验证硬指标：能否检索到 武房规〔2018〕2号 / 武政办〔2022〕78号

用法：python scripts/verify_dept_sources.py
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# wb 推断的部门源 + 已验证存在的栏目
CANDIDATES = [
    ("房管局·规范性文件库", "https://zgj.wuhan.gov.cn/xxgk/zcfgyjd_1/gfxwjsjk/"),
    ("房管局·政策解读", "https://zgj.wuhan.gov.cn/xxgk/zcfgyjd_1/zcjd/"),
    ("房管局·通知公告", "https://zgj.wuhan.gov.cn/zwdt/tzgg/"),
    ("房管局·政策问答", "https://zgj.wuhan.gov.cn/xxgk/zcfgyjd_1/zcwd/"),
]

# 判断"这条跟大学生/安居有关"
REL_KEYWORDS = [
    "大学生", "毕业生", "高校", "租赁房", "安居", "落户",
    "补贴", "人才", "住房", "创业", "就业",
]

# 硬指标：两个 grandfathering 关键文号
HARD_TARGETS = ["武房规〔2018〕2号", "武政办〔2022〕78号", "武房规", "武政办〔2022〕78"]

# 通用记录提取：政府站列表页的链接通常是 <a href="./YYYYMM/tYYYYMMDD_ID.shtml">
LINK_PATTERN = re.compile(r'href="(\.?/?[^"]*?t(20\d{2})\d{4}_\d+\.shtml)"[^>]*>([^<]{4,200})')


def check(name: str, url: str) -> dict:
    print("=" * 76)
    print(f"【{name}】{url}")
    print("=" * 76)

    result = {"name": name, "url": url, "total": 0, "relevant": 0, "hard_hits": []}

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
    except Exception as e:
        print(f"  ❌ 请求失败：{type(e).__name__}: {e}")
        print()
        return result

    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}")
        print()
        return result

    html = r.text
    print(f"  ✅ HTTP 200 | {len(html):,} 字符")

    # ── 软 404 检查 ────────────────────────────────────────
    if len(html) < 1000:
        print(f"  ❌ 内容过短，疑似软 404：{html.strip()[:120]}")
        print()
        return result

    # ── 提取记录 ───────────────────────────────────────────
    links = LINK_PATTERN.findall(html)
    result["total"] = len(links)

    if not links:
        print(f"  ⚠️  未提取到记录 —— 结构可能不同（需单独看）")
        # 给线索
        a_count = len(re.findall(r"<a\b", html))
        shtml_count = len(re.findall(r"\.shtml", html))
        print(f"     线索：<a> {a_count} 个，.shtml 出现 {shtml_count} 次")
        print()
        return result

    # ── 检查 1：新鲜度 ─────────────────────────────────────
    years = Counter(y for _, y, _ in links)
    newest = max(years)
    dist = dict(sorted(years.items(), reverse=True))
    print(f"  📅 记录 {len(links)} 条 | 年份分布 {dist}")
    print(f"     最新：{newest} {'✅' if int(newest) >= 2025 else '⚠️ 疑似死数据'}")

    # ── 检查 2：相关度（wb 建议补的检查项）─────────────────
    relevant = [(href, y, t) for href, y, t in links if any(k in t for k in REL_KEYWORDS)]
    result["relevant"] = len(relevant)
    rate = len(relevant) / len(links) * 100
    mark = "✅" if rate >= 20 else "⚠️"
    print(f"  🎯 相关度：{len(relevant)}/{len(links)} = {rate:.0f}%  {mark}")

    if relevant:
        print(f"     相关条目样本：")
        for _, y, t in relevant[:8]:
            shown = t if len(t) <= 52 else t[:52] + "…"
            print(f"       [{y}] {shown}")

    # ── 检查 3：硬指标（两个关键文号）──────────────────────
    all_text = html
    for target in HARD_TARGETS:
        if target in all_text:
            result["hard_hits"].append(target)
    if result["hard_hits"]:
        print(f"  🎯 硬指标命中：{result['hard_hits']}")
    else:
        print(f"  ⚠️  硬指标未命中（本页未见 武房规 / 武政办〔2022〕78）")

    print()
    return result


print()
print("数据源验证：部门网站")
print()

results = []
for name, url in CANDIDATES:
    results.append(check(name, url))

print("=" * 76)
print("汇总")
print("=" * 76)
print()
print(f"{'栏目':<22} {'记录':>5} {'相关':>5} {'相关度':>7}  判断")
print("-" * 76)
for r in results:
    if r["total"] == 0:
        print(f"{r['name']:<22} {'—':>5} {'—':>5} {'—':>7}  ❌ 需单独看结构")
    else:
        rate = r["relevant"] / r["total"] * 100
        verdict = "✅ 可用" if rate >= 20 else "⚠️ 相关度低"
        print(f"{r['name']:<22} {r['total']:>5} {r['relevant']:>5} {rate:>6.0f}%  {verdict}")
