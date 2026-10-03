"""自检：验证落盘的 JSONL 是不是真的没问题。

起因：PowerShell 的 Get-Content 显示中文乱码。
     需要确认这是"显示问题"还是"文件真的坏了"。

判断方法：用 Python 自己读回来，和源数据对比。
         如果 Python 读出来正常，那就是 PowerShell 的显示问题。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIST_JSONL = PROJECT_ROOT / "data" / "processed" / "list.jsonl"

print("=" * 72)
print("自检：JSONL 文件完整性")
print("=" * 72)
print()

# ── 检查 1：文件编码声明 ────────────────────────────────
raw_bytes = LIST_JSONL.read_bytes()
print(f"文件大小：{len(raw_bytes):,} 字节")

# UTF-8 BOM 检查（BOM 会导致 json.loads 在某些工具里失败）
if raw_bytes[:3] == b"\xef\xbb\xbf":
    print("  ⚠️  文件带 UTF-8 BOM —— 部分工具解析会出错")
else:
    print("  ✅ 无 BOM")

# ── 检查 2：能否被 utf-8 正确解码 ───────────────────────
try:
    text = raw_bytes.decode("utf-8")
    print("  ✅ UTF-8 解码成功")
except UnicodeDecodeError as e:
    print(f"  ❌ UTF-8 解码失败：{e}")
    sys.exit(1)

# ── 检查 3：逐行 json 解析 ──────────────────────────────
lines = [ln for ln in text.splitlines() if ln.strip()]
print(f"  行数：{len(lines)}")

bad = 0
records = []
for i, ln in enumerate(lines, 1):
    try:
        records.append(json.loads(ln))
    except json.JSONDecodeError as e:
        bad += 1
        if bad <= 3:
            print(f"  ❌ 第 {i} 行解析失败：{e}")

if bad == 0:
    print(f"  ✅ 全部 {len(lines)} 行 JSON 解析成功")
else:
    print(f"  ❌ 有 {bad} 行解析失败")

# ── 检查 4：中文有没有乱码 ──────────────────────────────
# 乱码的特征：出现大量"锟斤拷"、"锛"、"銆"这类字符
# （这是 UTF-8 字节被当 GBK 解读的典型结果）
SUSPECT = ["锛", "銆", "鍏", "姘", "甯", "鏀", "锟斤拷"]

mojibake = 0
for r in records:
    if any(s in r.get("title", "") for s in SUSPECT):
        mojibake += 1

print()
if mojibake:
    print(f"  ❌ 发现 {mojibake} 条标题疑似乱码！")
else:
    print(f"  ✅ 未发现乱码特征")

# ── 检查 5：打印真实内容对比 ────────────────────────────
print()
print("─" * 72)
print("文件里实际存的内容（Python 读出来的样子）：")
print("─" * 72)
for r in records[:3]:
    print(f"  {r['title']}")
print()

print("─" * 72)
print("对照：浏览器里这些政策的真实标题应该是")
print("─" * 72)
print("  市人民政府办公厅关于印发《武汉市推进政务服务场所综合改革工作实施方案（试行）》的通知")
print("  市人民政府办公厅关于印发武汉市支持生物医药产业创新发展若干措施的通知")
print("  市人民政府办公厅关于印发市人民政府2026年度重大行政决策事项目录的通知")
print()

if mojibake == 0 and bad == 0:
    print("✅ 结论：文件本身没有问题，PowerShell 的 Get-Content 显示乱码是终端编码问题")
else:
    print("❌ 结论：文件确实有问题，需要修复写入逻辑")
    sys.exit(1)

# ── 检查 6：字段完整性 ──────────────────────────────────
print()
print("─" * 72)
print("字段完整性检查：")
print("─" * 72)
from collections import Counter

empty = Counter()
for r in records:
    for k in ["url", "title", "path", "source", "page"]:
        if not r.get(k):
            empty[k] += 1

if empty:
    for k, n in empty.items():
        print(f"  ⚠️  {k} 为空：{n} 条")
else:
    print("  ✅ 所有字段非空")

# 标题长度分布 —— 太短的很可能是抓错了
lens = [len(r["title"]) for r in records]
print(f"  标题长度：最短 {min(lens)}，最长 {max(lens)}，平均 {sum(lens)//len(lens)}")

short = [r for r in records if len(r["title"]) < 10]
if short:
    print(f"  ⚠️  有 {len(short)} 条标题异常短，检查：")
    for r in short[:3]:
        print(f"      {r['title']!r}")
else:
    print("  ✅ 无异常短标题")
