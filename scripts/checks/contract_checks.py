"""检查项 —— 画像契约同步（SPEC §2.3 声明的字段集 vs 引擎实际要的字段集）。

为什么单独一个文件：`data_checks.py` 已接近 200 行上限，
且本检查与数据源检查无关，是**契约层**的事。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from checks.config import PROJECT_ROOT, fail


def _engine_required_fields(golden_p: Path) -> set[str]:
    """引擎会向用户追问的字段集（= 画像必须能填的字段集）。

    ⚠️ **为什么用「空画像跑一遍」而不是「评测集 profile 的键并集」**：
        评测集里有 `migrate_spouse_children` 这种**没有条件在读**的键
        （它是 _14「可随迁」那条权益留下的残留，已移出资格集）。
        拿它当契约要求 = 要求用户填一个**不影响任何判定**的字段。

        **契约要覆盖的是「引擎会问你要什么」，不是「谁在测试里填了什么」。**

    空画像跑一次，引擎把所有「需要但没填」的字段报进 `missing_fields` ——
    那是权威来源。
    """
    try:
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        from src.conditions.loader import load_conditions
        from src.engine.eligibility import check_eligibility

        conds = load_conditions(golden_p)
        pol_p = PROJECT_ROOT / "data" / "processed" / "policies.jsonl"
        if not pol_p.exists():
            return set()

        required: set[str] = set()
        for ln in pol_p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                meta = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if not meta.get("doc_id"):
                continue
            try:
                res = check_eligibility({}, conds, policy_meta=meta, as_of_year=2026)
            except Exception:
                continue
            required |= set(res.get("missing_fields") or [])
        return required
    except Exception:
        return set()


def check_profile_contract() -> None:
    """SPEC §2.3 声明的画像字段集，必须覆盖引擎真正会追问的字段。

    ⚠️ 为什么这条必须存在（2026-11-25 实测踩坑）：
        SPEC §2.3 的 JSON 抄的是 `profile.json` 的**早期版本**，
        之后 v3/v4 一路加字段（`age` / `social_insurance_active` /
        `education_file` / `grad_years` / `market_rent`）——**加在实现里和评测集里，
        唯独没同步回 SPEC**。
        后果不是报错，是**默默少一个字段**：
        照 SPEC 写画像 → 引擎判 UNKNOWN → 用户拿不到结论。
        **契约不跟着实现走 = 判错的时候不报警。**
    """
    spec = PROJECT_ROOT / "docs" / "SPEC.md"
    golden_p = PROJECT_ROOT / "eval" / "golden_conditions.jsonl"
    if not (spec.exists() and golden_p.exists()):
        return

    src = spec.read_text(encoding="utf-8", errors="replace")
    if "### 2.3" not in src or "### 2.4" not in src:
        return
    block = src[src.index("### 2.3"):src.index("### 2.4")]
    declared = set(re.findall(r'"([a-z_]+)"\s*:', block))
    if not declared:
        return

    required = _engine_required_fields(golden_p)
    if not required:
        # 引擎跑不起来时退回「条件 field 并集」，至少不漏
        for ln in golden_p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                continue
            f = row.get("field")
            if f:
                required.add(f)

    # `rent` 是计算类条件的**输出字段**，不是画像要填的输入
    output_only = {"rent"}
    missing = sorted(required - declared - output_only)
    if missing:
        fail(
            f"[画像契约] SPEC §2.3 缺字段：{missing}。"
            "引擎会用它们（空画像跑出来的 missing_fields），但契约没声明 —— "
            "照契约写画像会漏字段 → 引擎判 UNKNOWN。"
        )
