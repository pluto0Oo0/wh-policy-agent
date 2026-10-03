"""摸清三个主源的列表页结构（写正式解析前的必做步骤）。

自检清单第 5 条：**先看结构再写解析，不对结构做假设。**

本脚本对 szfwj / bgtwj / zcwd 三个页面做同样的体检：
  1. 页面还活着吗（HTTP 状态 + 长度）
  2. 是软 404 吗（跳转页特征）
  3. 列表数据在哪（<a> 标签里？还是 inline JS 里？）
  4. **六个来源的时间戳年份分布** —— 判断新鲜度
  5. 抽第一条完整样本打印出来

用法：python scripts/survey_sources.py
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

SOURCES = [
    ("市政府文件", "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/"),
    ("办公厅文件", "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/"),
    ("政策问答", "https://www.wuhan.gov.cn/zwgk/xxgk/zcwd/"),
]

# 从源码里提取「列表记录」的正则。
# 依据：已实测 szfwj 的结构是 var url = "./202609/t20260917_2849324.shtml"
#       紧随其后 var title = "市人民政府关于印发……的通知"
RECORD_PATTERN = re.compile(
    r'url\s*=\s*"(\./\d{6}/t\d{8}_\d+\.shtml)"'      # 链接
    r'.{0,400}?'                                      # 中间可能有若干行
    r'title\s*=\s*"([^"]{4,200})"',                   # 标题
    re.DOTALL,
)


def check(name: str, url: str) -> dict:
    """对单个源做体检，返回结果 dict。"""
    print("=" * 78)
    print(f"【{name}】{url}")
    print("=" * 78)

    result = {"name": name, "url": url, "ok": False, "count": 0}

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.encoding = "utf-8"
        html = r.text
    except Exception as e:
        print(f"  ❌ 请求失败：{type(e).__name__}: {e}")
        print()
        return result

    # ── 检查 1：HTTP 状态 ───────────────────────────────
    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}")
        print()
        return result
    print(f"  ✅ HTTP 200")

    # ── 检查 2：内容长度 + 软 404 特征 ──────────────────
    print(f"  内容长度：{len(html)} 字符")
    if len(html) < 1000:
        print(f"  ❌ 内容过短，疑似软 404")
        print(f"     内容：{html.strip()[:200]}")
        print()
        return result
    if "window.location" in html and len(html) < 1000:
        print(f"  ❌ 是 JS 跳转页，不是内容页")
        print()
        return result

    # ── 检查 3：列表数据在哪 ────────────────────────────
    a_total = len(re.findall(r"<a\b", html))
    a_shtml = len(re.findall(r'<a[^>]+href="[^"]*\.shtml"', html))
    print(f"  <a> 标签 {a_total} 个，其中含 .shtml 的 {a_shtml} 个")

    # ── 检查 4：用正则抽记录 ────────────────────────────
    records = RECORD_PATTERN.findall(html)
    print(f"  正则抽到记录：{len(records)} 条")
    result["count"] = len(records)

    if len(records) == 0:
        print(f"  ❌ 抽到 0 条 —— 结构可能和预期不同，不能继续")
        # 自检：给出可能的原因线索
        hint = re.findall(r'url\s*=\s*"([^"]{4,80})"', html)
        print(f"     线索：源码里 url = \"...\" 有 {len(hint)} 处，样本：{hint[:3]}")
        print()
        return result

    # ── 检查 5：时间戳年份分布（新鲜度） ────────────────
    years = [re.search(r"t(20\d{2})\d{4}_", path).group(1) for path, _ in records]
    dist = Counter(years)
    newest = max(dist)
    print(f"  时间戳年份分布：{dict(sorted(dist.items(), reverse=True))}")
    print(f"  → 最新：{newest}")

    if int(newest) < 2025:
        print(f"  ⚠️  警告：最新内容距今超过 1 年，疑似死数据")
    else:
        print(f"  ✅ 新鲜度合格")

    # ── 检查 6：抽样打印，人工确认 ──────────────────────
    print()
    print(f"  ── 前 3 条样本 ──")
    for path, title in records[:3]:
        shown = title if len(title) <= 52 else title[:52] + "…"
        print(f"    {path}")
        print(f"    {shown}")

    result["ok"] = True
    result["newest"] = newest
    print()
    return result


print()
print("数据源体检：开始")
print()

results = [check(name, url) for name, url in SOURCES]

print("=" * 78)
print("体检汇总")
print("=" * 78)
for r in results:
    status = "✅ 可用" if r["ok"] else "❌ 不可用"
    print(f"  {status}  {r['name']:<12} 抽到 {r['count']:>3} 条")
