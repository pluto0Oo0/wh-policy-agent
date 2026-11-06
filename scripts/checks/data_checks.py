"""检查项（第二部分）—— JSONL 完整性 / SPEC 签名同步 / 数据源有效性。

从 _checks.py 拆出，因为原文件 247 行超过 CLAUDE.md 第 2 条的 200 行上限。
拆法：config.py（配置 + 基础检查），本文件（数据类检查）。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from .config import (
    ALLOWED_EMPTY_FIELDS,
    MAX_FIELD_EMPTY_RATE,
    MIN_RECORDS_FOR_RATE,
    NOT_YET_PHASED,
    PROJECT_ROOT,
    SUSPECT_MOJIBAKE,
    TARGET_DOC_NUMBERS,
    fail,
    warn,
)


# ── 4. JSONL 完整性 ───────────────────────────────────────────
def check_jsonl() -> None:
    processed = PROJECT_ROOT / "data" / "processed"
    if not processed.exists():
        return

    for p in sorted(processed.rglob("*.jsonl")):
        raw = p.read_bytes()
        if raw[:3] == b"\xef\xbb\xbf":
            fail(f"[编码] {p.name} 带 UTF-8 BOM，部分工具解析会失败。")

        text = raw.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        records, bad = [], 0
        for i, ln in enumerate(lines, 1):
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError:
                bad += 1
                if bad <= 3:
                    fail(f"[JSON] {p.name} 第 {i} 行解析失败。")
        if bad or not records:
            continue

        moji = sum(
            1 for r in records
            if any(s in json.dumps(r, ensure_ascii=False) for s in SUSPECT_MOJIBAKE)
        )
        if moji:
            fail(f"[乱码] {p.name} 有 {moji} 条含乱码特征字符。")

        keys = set().union(*(set(r) for r in records))
        for k in keys:
            if k in ALLOWED_EMPTY_FIELDS:
                # 这些字段空/None 是合法态（语义见 config.py 注释），但有
                # 配套的一致性检查：
                #   status_evidence 有值 → policy_status 必须已核实
                if k == "status_evidence":
                    bad = [
                        r["doc_id"] for r in records
                        if r.get(k) and not r.get("policy_status") not in ("现行",)
                    ]
                    if bad:
                        fail(f"[一致性] {p.name} 有 status_evidence 但 policy_status 不是『现行』：{bad[:3]}")
                continue
            # 「空值」= 字段缺失或 None。[] 和 "" 是合法值（区级页无附件=空列表、
            # 无文号=空串是事实陈述，不是缺失）——2026-10-19 实测：
            # not [] == True 导致 28 条「无附件」被误报成空值率 93%
            empty = sum(1 for r in records if r.get(k) is None or k not in r)
            # 单记录空值率没有统计意义（1/1 = 100%）：样本不足时声明不评估，
            # 不静默跳过也不报错（欠条 #5，2026-10-19 所有者批的方向：
            # len(records)>=5 才算率）
            if len(records) < MIN_RECORDS_FOR_RATE:
                if empty:
                    warn(f"[空字段] {p.name} 字段 `{k}` 有 {empty} 条空值，"
                         f"但仅 {len(records)} 条记录（<{MIN_RECORDS_FOR_RATE}），样本不足未评估。")
                continue
            if empty / len(records) > MAX_FIELD_EMPTY_RATE:
                fail(
                    f"[空字段] {p.name} 字段 `{k}` 空值率 {empty}/{len(records)}，"
                    f"超过 {MAX_FIELD_EMPTY_RATE:.0%} 阈值。"
                )

        urls = [r.get("url") for r in records if r.get("url")]
        if len(urls) != len(set(urls)):
            fail(f"[重复] {p.name} url 有重复 {len(urls) - len(set(urls))} 条。")

        titles = [r.get("title") for r in records if r.get("title")]
        dup = {t for t in titles if titles.count(t) > 1}
        if dup:
            warn(f"[重复] {p.name} 标题重复 {len(dup)} 个：{list(dup)[:2]}")


# ── 5. SPEC 签名同步 ──────────────────────────────────────────
def check_spec_signatures() -> None:
    spec = PROJECT_ROOT / "docs" / "SPEC.md"
    if not spec.exists():
        return

    src = spec.read_text(encoding="utf-8", errors="replace")
    block = re.search(r"## 5\..*?```python(.*?)```", src, re.DOTALL)
    if not block:
        return

    declared = set(re.findall(r"def\s+(\w+)\s*\(", block.group(1)))
    if not declared:
        return

    implemented: set[str] = set()
    src_dir = PROJECT_ROOT / "src"
    if src_dir.exists():
        for p in src_dir.rglob("*.py"):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    implemented.add(node.name)

    missing = sorted(declared - implemented - NOT_YET_PHASED)
    if missing:
        warn(f"[签名] SPEC §5 声明但未实现：{missing}（需人工确认是否漏实现）")


# ── 6. 数据源有效性 ──────────────────────────────────────────
def check_source_usefulness() -> None:
    """用目标文号做布尔判断，**不用关键词命中率**。

    实测教训：房管局源关键词命中率 39% 看起来很好，
    但逐条看全是"行政处罚""房屋安全检查"——匹配了"住房"两字，与大学生无关。
    """
    lst = PROJECT_ROOT / "data" / "processed" / "list.jsonl"
    if not lst.exists():
        return

    records = []
    for ln in lst.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    if not records:
        return

    years = [y for y in (re.search(r"/t(20\d{2})", r.get("path", "")) for r in records) if y]
    if years:
        newest = max(int(y.group(1)) for y in years)
        if newest < 2025:
            fail(f"[新鲜度] list.jsonl 最新内容 {newest} 年，距今超 1 年，疑似死数据。")

    pages = sorted({r.get("page") for r in records if r.get("page")})
    if pages and max(pages) <= 5:
        warn(
            f"[翻页] 只抓到第 {max(pages)} 页。硬指标 0 命中有两种原因："
            f"**源不对** 或 **翻页不够**。武政办〔2022〕78号 实测在 bgtwj 第 10 页。"
        )

    all_text = json.dumps(records, ensure_ascii=False)
    for dn in TARGET_DOC_NUMBERS:
        if dn not in all_text:
            warn(f"[硬指标] 未找到 `{dn}`。⚠️ 不命中不一定等于源不对，也可能是翻页不够。")
