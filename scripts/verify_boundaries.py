"""边界判定验证 · age 与分界日（2026-11-20 新增）

**这个脚本为什么存在**：

本项目曾经把两条**并不存在**的缺陷写进了存档、评测报告和 README：

1. 「`age<45` 被实现成 `age<=45`」
2. 「分界日 off-by-one（2022-06-07 前后差一天）」

两条都源自同一处旧讨论——**「50 岁的博士会被 age<45 判 fail 掉」这个举例不成立**
（`_01` 带豁免机制，50 岁博士本来就 PASS）。评审者 2026-11-06 就纠正过，
但后来被简化成了「off-by-one」，当成「已定位的缺陷」传了下去。

**教训：把「我以为的缺陷」写进文档 = 给未来的自己派一个不存在的活。**
而它还有传染性——README 里那行字会让每个读仓库的人（包括未来的我）以为有个 bug 要修。

**所以有了这个脚本**：把「这两条到底成不成立」变成**可运行、可复现、可回归**的事实，
而不是又一段会失真的文字。

用法：
    .venv/Scripts/python.exe scripts/verify_boundaries.py

退出码 0 = 全部符合预期；非 0 = 某条边界判定出了问题（真出问题了，不是脚本坏了）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conditions.loader import GOLDEN_PATH, load_conditions  # noqa: E402
from src.engine.cohort import resolve_cohort  # noqa: E402
from src.engine.eligibility import check_eligibility  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 一份最小可用画像：只保留被测条件用到的字段
BASE = {
    "education": "本科",
    "education_type": "全日制",
    "grad_year": 2026,
    "first_insurance_date": "2026-07-01",
    "employed": True,
    "housing_owned_in_wuhan": False,
    "region": "洪山",
    "age": 23,
    "social_insurance_active": True,
    "marital_status": "未婚",
    "market_rent": 1800,
    "qualification_valid": True,
    "education_file": "毕业证.pdf",
}

DOC_78 = "t20220608_1983869"   # 武政办〔2022〕78号


def _judge(profile: dict, cond, as_of_year: int = 2026) -> str:
    """判单条条件，返回状态。"""
    r = check_eligibility(
        profile, [cond], policy_meta={"doc_id": DOC_78}, as_of_year=as_of_year
    )
    return r["reasons"][0]["status"]


def main() -> int:
    conds = load_conditions(GOLDEN_PATH)
    by_id = {c.cond_id: c for c in conds}
    bad = 0

    print("=" * 70)
    print("边界验证 ①：age 的『不满 45 周岁』")
    print("=" * 70)
    print("原文：年龄不满45周岁（研究生不受年龄限制）的高校毕业生…")
    print("标注：op='<' value=45  →  45 岁**不**满足（45 < 45 为假）\n")

    c01 = by_id["t20220608_1983869_01"]
    c12 = by_id["t20220608_1983869_12"]

    # ── 本科（无豁免）：44 PASS / 45 FAIL / 46 FAIL ──────────────────
    for age, want in ((44, "PASS"), (45, "FAIL"), (46, "FAIL")):
        got = _judge({**BASE, "age": age}, c01)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '🔴'} 本科 age={age} → {want:<5} 实得 {got}")

    # ── 博士（豁免生效）：45/46 都 PASS，且标记 exempted ─────────────
    for age in (45, 46):
        r = check_eligibility(
            {**BASE, "age": age, "education": "博士"}, [c01],
            policy_meta={"doc_id": DOC_78}, as_of_year=2026,
        )
        x = r["reasons"][0]
        ok = x["status"] == "PASS" and x.get("exempted") is True
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '🔴'} 博士 age={age} → PASS 且标记豁免   "
              f"实得 status={x['status']} exempted={x.get('exempted')}")

    # ── 豁免没起作用时**不许**标豁免（44 岁本来就符合）──────────────
    r = check_eligibility(
        {**BASE, "age": 44, "education": "博士"}, [c01],
        policy_meta={"doc_id": DOC_78}, as_of_year=2026,
    )
    x = r["reasons"][0]
    ok = x["status"] == "PASS" and "exempted" not in x
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '🔴'} 博士 age=44 → 正常就符合，**不标**豁免   "
          f"实得 status={x['status']} exempted={x.get('exempted')}")

    # ── `_12` 与 `_01` 同源，必须行为一致 ────────────────────────────
    same = all(
        _judge({**BASE, "age": age}, c01) == _judge({**BASE, "age": age}, c12)
        for age in (44, 45, 46)
    )
    bad += 0 if same else 1
    print(f"  {'✅' if same else '🔴'} _01 与 _12（同源重复条）行为一致")

    print()
    print("=" * 70)
    print("边界验证 ②：分界日 2022-06-07")
    print("=" * 70)
    print("_10 原文：本通知**公布前**留汉的同等条件大学毕业生…（grandfathering 条款）")
    print("标注：op='<' value='2022-06-07'  →  只对**公布前**留汉的人生效\n")

    c10 = by_id["t20220608_1983869_10"]

    # ── 公布前：条款适用 ─────────────────────────────────────────────
    prof_before = {**BASE, "first_insurance_date": "2022-06-06"}
    in_track = resolve_cohort(prof_before, c10)
    got = _judge(prof_before, c10)
    ok = in_track and got == "PASS"
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '🔴'} 2022-06-06 首保 → 老政策通道，_10 PASS   "
          f"实得 cohort={in_track} status={got}")

    # ── 当天：条款**不**适用（「公布前」不含当天）────────────────────
    prof_day = {**BASE, "first_insurance_date": "2022-06-07"}
    in_track = resolve_cohort(prof_day, c10)
    got = _judge(prof_day, c10)
    ok = (not in_track) and got == "N/A"
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '🔴'} 2022-06-07 当天 → 新政策通道，_10 N/A   "
          f"实得 cohort={in_track} status={got}")

    # ── 公布后：条款不适用 ───────────────────────────────────────────
    prof_after = {**BASE, "first_insurance_date": "2022-06-08"}
    in_track = resolve_cohort(prof_after, c10)
    got = _judge(prof_after, c10)
    ok = (not in_track) and got == "N/A"
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '🔴'} 2022-06-08 首保 → 新政策通道，_10 N/A   "
          f"实得 cohort={in_track} status={got}")

    print()
    print("=" * 70)
    print("边界验证 ③：评测集里的成对边界用例")
    print("=" * 70)
    print("E24（06-06 首保）→ ELIGIBLE；E25（06-07 首保）→ INELIGIBLE")
    print("**两个用例只差一天**，分界日逻辑稍有偏差就会判错。\n")

    import json
    cases = {
        json.loads(line)["case_id"]: json.loads(line)
        for line in (PROJECT_ROOT / "eval" / "eval_cases.jsonl")
        .read_text(encoding="utf-8").splitlines() if line.strip()
    }
    pols = {
        p["doc_id"]: p
        for p in (
            json.loads(line)
            for line in (PROJECT_ROOT / "data" / "processed" / "policies.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()
        )
    }
    for cid in ("E24", "E25"):
        case = cases[cid]
        own = [c for c in conds if c.doc_id == case["policy_id"]]
        r = check_eligibility(
            case["profile"], own,
            policy_meta=pols[case["policy_id"]], as_of_year=2026,
        )
        ok = r["verdict"] == case["expected_verdict"]
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '🔴'} {cid}（首保 {case['profile']['first_insurance_date']}）"
              f" → {case['expected_verdict']:<11} 实得 {r['verdict']}")

    print()
    if bad:
        print(f"🔴 {bad} 项不符合预期 —— **边界判定真的出问题了**，请查。")
        return 1
    print("✅ 全部符合预期")
    print()
    print("📌 结论：**「age off-by-one」和「分界日 off-by-one」这两条缺陷都不存在。**")
    print("   存档/评测报告/README 里关于它们的记录是误传，应当撤销。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
