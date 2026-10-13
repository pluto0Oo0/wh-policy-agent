"""加载 `eval/golden_conditions.jsonl` —— 把标注数据变成 `Condition` 对象。

SPEC §5 签名（不得改名）：
    load_conditions(path) -> list[Condition]

════════════════════════════════════════════════════════════════
坏记录怎么办：跳过并告警，但**一条都加载不出来时必须报错**
════════════════════════════════════════════════════════════════
SPEC §8.3 要求「解析层宽松跳过但记 warning」。这条对**抓取来的脏数据**是对的
——一条坏记录不该让整批任务挂掉。

但对 golden set 有个额外要求（`CLAUDE.md` 第 10.1 条第 5 问：
**"如果输入是空的/全失败了，我的代码会输出什么？"**）：

    如果 9 条全坏了 → 跳过 9 条 → 返回空列表 →
    engine 拿空条件去判定 → **对每个人都判 ELIGIBLE**（没有条件要满足）→
    **输出一个看起来很确定的错误答案。**

所以本模块的规则是：
    部分坏 → 告警 + 跳过（宽松）
    全坏 / 文件不存在 / 文件为空 → **抛 ConditionError**（严格）

**"全坏"和"部分坏"要区别对待，因为它们的后果不同。**
"""

import json
from pathlib import Path

from .model import Condition, ConditionError


def load_conditions(path: str | Path) -> list[Condition]:
    """从 JSONL 读入全部条件。

    参数：
        path: `eval/golden_conditions.jsonl` 的路径

    返回：
        list[Condition]，按文件顺序

    抛出：
        ConditionError: 文件不存在 / 文件为空 / **一条都没加载成功**

    为什么要检查"一条都没成功"而不只是"文件非空"：
        文件有 9 行但 9 行全坏，和空文件**后果完全一样**——
        engine 会拿零条件去判定。只查文件非空会漏掉这一种。
    """
    path = Path(path)
    if not path.exists():
        raise ConditionError(f"找不到条件文件：{path}")

    raw_lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not raw_lines:
        raise ConditionError(f"条件文件是空的：{path}")

    conditions: list[Condition] = []
    skipped: list[str] = []

    for lineno, line in enumerate(raw_lines, start=1):
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            # 宽松跳过，但**必须留下可定位的信息**（第几行、坏在哪）
            skipped.append(f"第 {lineno} 行：JSON 解析失败（{e.msg}）")
            continue

        try:
            # 只把模型认识的字段传进去，多余字段（如文档里附带的注释）忽略
            known = {f for f in Condition.__dataclass_fields__ if f != "warnings"}
            conditions.append(Condition(**{k: v for k, v in data.items() if k in known}))
        except ConditionError as e:
            skipped.append(f"第 {lineno} 行：{e}")
        except TypeError as e:
            # 字段名不认识 / 必填字段缺失
            skipped.append(f"第 {lineno} 行：字段不匹配（{e}）")

    # ── 部分坏：告警，继续 ────────────────────────────────────
    if skipped:
        print(f"⚠️  跳过 {len(skipped)} 条坏记录：")
        for s in skipped:
            print(f"    {s}")

    # ── 全坏：必须报错，不能返回空列表 ────────────────────────
    if not conditions:
        raise ConditionError(
            f"{path} 里 {len(raw_lines)} 行**一条都没能加载**。\n"
            f"原因：{'；'.join(skipped[:3])}\n"
            f"→ 直接返回空列表会让 engine 拿零条件去判定，对每个人都判 ELIGIBLE。"
        )

    # 非致命问题（如 cond_type 与 formula 不匹配）单独汇总，不阻断
    warn_count = sum(len(c.warnings) for c in conditions)
    if warn_count:
        print(f"⚠️  {warn_count} 条可疑（不阻断加载）：")
        for c in conditions:
            for w in c.warnings:
                print(f"    {w}")

    return conditions


# ══════════════════════════════════════════════════════════════
# 验收：python -m src.conditions.loader
# ══════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = PROJECT_ROOT / "eval" / "golden_conditions.jsonl"


def _run_acceptance() -> int:
    """加载 golden set 并做四条断言，返回退出码（0 = 全过）。"""
    print(f"加载 {GOLDEN_PATH}")
    conds = load_conditions(GOLDEN_PATH)
    print(f"✅ 加载 {len(conds)} 条\n")

    failures: list[str] = []

    # 断言 1：78 号文的 9 条都在
    if len(conds) != 9:
        failures.append(f"断言1：期望 9 条，实得 {len(conds)} 条")

    # 断言 2：cond_id 唯一（重复会让 reason 列表对不上号）
    ids = [c.cond_id for c in conds]
    if len(set(ids)) != len(ids):
        failures.append(f"断言2：cond_id 有重复 {[i for i in ids if ids.count(i) > 1]}")

    # 断言 3：计算类必须有 formula（六重叠加是纵切的计算核心）
    calc = [c for c in conds if c.cond_type == "计算"]
    if not calc:
        failures.append("断言3：一条计算类条件都没有（六重叠加没标进来）")
    for c in calc:
        if not c.formula:
            failures.append(f"断言3：{c.cond_id} 是计算类但没有 formula")

    # 断言 4：老/新两个 cohort 的分界都在（grandfathering 双轨）
    cohorts = {c.applies_to_cohort for c in conds}
    if not any("老政策" in c for c in cohorts):
        failures.append(f"断言4：缺老政策通道，现有 cohort={cohorts}")

    # 断言 5：核对留痕状态（D17）—— 未核对不算失败，但必须如实报
    unverified = [c.cond_id for c in conds if not c.is_verified]
    print(f"核对状态：{len(conds) - len(unverified)}/{len(conds)} 条已核对留痕")
    if unverified:
        print(f"  ⏳ 待所有者核对：{unverified}")

    print()
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
        print(f"\n❌ 未通过，{len(failures)} 个问题")
        return 1

    print("  ✅ 断言1：9 条齐全")
    print("  ✅ 断言2：cond_id 唯一")
    print(f"  ✅ 断言3：计算类 {len(calc)} 条且都有 formula")
    print(f"  ✅ 断言4：含老政策通道（cohort 共 {len(cohorts)} 种）")
    print("\n✅ 全部通过")
    return 0


def _run_fault_injection() -> int:
    """故障注入：坏输入必须被抓到，好输入不能误报。

    为什么必须做：本项目踩过一条**永远不会触发**的检查
    （`len(html) < 1000` 那条软 404）。**断言全绿不等于断言有效。**
    """
    import tempfile

    cases = [
        ("空文件", "", "抛异常"),
        ("全是坏 JSON", "{不是json}\n{也不是}\n", "抛异常"),
        ("只有空白行", "\n\n   \n", "抛异常"),
        ("一行好一行坏", '{"cond_id":"x","doc_id":"d","applies_to_cohort":"全体",'
                      '"cond_type":"资格","field":"f","op":"==","value":1,'
                      '"source_text":"原文"}\n{坏行}\n', "通过"),
        ("合法字段但 cond_type 非法",
         '{"cond_id":"x","doc_id":"d","applies_to_cohort":"全体",'
         '"cond_type":"瞎写的","field":"f","op":"==","value":1,"source_text":"原文"}\n', "抛异常"),
    ]

    print("=" * 62)
    print("故障注入：坏输入必须被抓到")
    print("=" * 62)
    bad = 0
    for label, content, want in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp = f.name
        try:
            load_conditions(tmp)
            got = "通过"
        except ConditionError:
            got = "抛异常"
        ok = got == want
        if not ok:
            bad += 1
        print(f"  {'✅' if ok else '🔴'} {label:<24} 期望{want} / 实际{got}")

    print()
    if bad:
        print(f"🔴 {bad} 个用例不符合预期")
        return 1
    print("✅ 全部符合预期（含「全坏必须抛异常」这条关键防线）")
    return 0


if __name__ == "__main__":
    code = _run_acceptance()
    print()
    code |= _run_fault_injection()
    raise SystemExit(code)
