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
    domain_errors: list[str] = []

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
            cond = Condition(**{k: v for k, v in data.items() if k in known})
        except ConditionError as e:
            skipped.append(f"第 {lineno} 行：{e}")
            continue
        except TypeError as e:
            # 字段名不认识 / 必填字段缺失
            skipped.append(f"第 {lineno} 行：字段不匹配（{e}）")
            continue

        # ── 取值域交集检测（强检测，2026-10-13 新增）────────────
        # 为什么是 fail 不是 warn：**不相交 = 这条永远不可能 PASS**，
        # 那不是"可能有问题"，是"确定是错的"。warn 会让它混过去。
        domain_problem = check_value_domain(cond)
        if domain_problem:
            domain_errors.append(f"{cond.cond_id}：{domain_problem}")

        conditions.append(cond)

    # ── 取值域不相交：**确定是错的，必须停下来** ──────────────
    # 这是 `_03` 那次教训落成的检查。它当初靠"偶然跑一次真数据"才被发现。
    if domain_errors:
        raise ConditionError(
            f"{path} 里 {len(domain_errors)} 条条件的取值域与画像字段**没有交集**：\n"
            + "\n".join(f"  · {e}" for e in domain_errors)
            + "\n→ 这类条件**永远不可能 PASS**，会让整体判定永远落在同一个结论上。\n"
            "→ 请核对是标注抄错了，还是画像字段的取值域定义要改。"
        )

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

# ⚠️ parents[2] 在这里**有意走死**（wb 2026-11-06 三.1 定论）：
# golden set 是项目真实评测基准，不存在"指向临时目录"的注入场景
# （CHECK_TARGET_DIR 隔离机制只服务 scripts/checks 检查器）。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = PROJECT_ROOT / "eval" / "golden_conditions.jsonl"

# golden set 的预期条件数（2026-11-11：v4 = v3 14 条 + T04 27 条）。
# 为什么写成常量而不是在断言里写死字面量：
#   2026-10-13 实测踩过 —— 断言里写死 `!= 9`，golden set 从 9 条涨到 13 条后
#   验收直接失败，**而失败原因是"断言过期"，不是"数据错了"**。
#   写成一个有名字的常量，下次改数据时至少会看到它、需要主动改它。
EXPECTED_CONDITION_COUNT = 41

# ══════════════════════════════════════════════════════════════
# 取值域交集检测（2026-10-13 新增，wb 建议的"强检测"）
# ══════════════════════════════════════════════════════════════
# 【这条检测的由来】
#   `_03` 曾写成 `education_type in ["全日制大专及以上"]`，而画像里
#   `education_type` 的取值域是 `{全日制, 非全日制}` —— **两个集合没有交集**。
#   后果：**任何画像都必然 FAIL** → 整体永远 INELIGIBLE。
#
#   而它**没有被任何检查发现**：格式全合法、`check_eligibility` 照常返回 FAIL
#   （FAIL 是正常返回值）。**是跑真数据时偶然暴露的。**
#
#   → 一条永远不可能 PASS 的条件，和一条永远不报警的检查，是同一种东西。
#
# 【取值域为什么写在这里而不是从 SPEC 读】
#   SPEC §2.3 目前**没有**定义画像字段的取值域（只给了字段名和类型）。
#   这是又一个"写代码才暴露的契约缺口" —— 已报 wb/所有者，待补进 SPEC §2.3。
#   ⚠️ 在那之前，这份常量是**唯一的事实源**，改画像字段必须同步改这里。
FIELD_DOMAINS: dict[str, object] = {
    "education": {"大专", "本科", "硕士", "博士"},
    "education_type": {"全日制", "非全日制"},
    "grad_year": (1980, 2100),          # 年份区间
    "grad_years": (0, 60),              # 毕业年数区间（引擎从 grad_year 派生）
    "hukou_wuhan": {True, False},
    "first_insurance_date": ("1900-01-01", "2100-12-31"),  # 日期区间（ISO 字符串）
    "employed": {True, False},
    "housing_owned_in_wuhan": {True, False},
    "age": (16, 70),
    "social_insurance_active": {True, False},
    "marital_status": {"未婚", "已婚"},
    "market_rent": (0.0, 100000.0),
    # 资格有效期（`_11`）。⚠️ 它是**外部依赖型条件** ——
    # 既不是画像静态属性，也不是引擎能算出的中间状态，
    # 永远需要用户自报或查外部系统。本期标 UNKNOWN + 追问。
    "qualification_valid": {True, False},
}


def check_value_domain(cond) -> str | None:
    """检查一条条件的 `value` 与画像字段取值域**有没有交集**。

    返回 None = 通过；返回字符串 = 不相交的原因。

    ⚠️ 计算类不检 —— 它的 `field`（如 `rent`）是**输出字段**，不是画像输入。
       拿输出字段去查画像取值域，会报出一堆假警报。
    """
    if cond.cond_type == "计算":
        return None

    # `exists` 只判"字段有没有值"，与取值无关
    if cond.op == "exists":
        return None

    domain = FIELD_DOMAINS.get(cond.field)
    if domain is None:
        # 取值域未知的字段：不报错（报错会变成假警报），但也查不了。
        # 让上层汇总提示，避免"以为查过了其实没查"。
        return None

    # ── 集合型取值域 ────────────────────────────────────────
    if isinstance(domain, set):
        if cond.op == "in":
            if not (set(cond.value) & domain):
                return (f"{cond.field} 的取值域是 {sorted(map(str, domain))}，"
                        f"而条件是 {cond.value} —— **两者没有交集，这条永远不可能 PASS**")
        elif cond.op == "==":
            if cond.value not in domain:
                return (f"{cond.field} 的取值域是 {sorted(map(str, domain))}，"
                        f"而条件是 == {cond.value!r} —— **永远不可能相等**")
        return None

    # ── 区间型取值域 ────────────────────────────────────────
    if isinstance(domain, tuple) and len(domain) == 2:
        lo, hi = domain
        try:
            v = cond.value
            if cond.op in (">=", ">"):
                # 阈值必须落在区间内，否则这条永远不成立（或永远成立）
                if not (lo <= v <= hi):
                    return f"{cond.field} 的合理区间是 {domain}，而阈值 {v!r} 落在区间外"
            elif cond.op in ("<=", "<"):
                if not (lo <= v <= hi):
                    return f"{cond.field} 的合理区间是 {domain}，而阈值 {v!r} 落在区间外"
            elif cond.op == "==":
                if not (lo <= v <= hi):
                    return f"{cond.field} 的合理区间是 {domain}，而 {v!r} 落在区间外"
        except TypeError:
            # 类型不可比（如 str 和 int 比大小）—— 这本身就是个错误
            return f"{cond.field} 的取值域是区间 {domain}，而 value={cond.value!r} 类型不匹配"
    return None



def _run_acceptance() -> int:
    """加载 golden set 并做四条断言，返回退出码（0 = 全过）。"""
    print(f"加载 {GOLDEN_PATH}")
    conds = load_conditions(GOLDEN_PATH)
    print(f"✅ 加载 {len(conds)} 条\n")

    failures: list[str] = []

    # 断言 1（**语义特征**）：检查"该有的东西在不在"，**不检查具体条数**。
    #
    # 2026-10-13 由 wb 指出：我原来把 `!= 9` 改成具名常量 `EXPECTED_CONDITION_COUNT`，
    # 那是「**换皮没换骨**」—— 常量仍然是写死的数字，改数据时照样会过期，
    # 只是过期时更容易被发现而已。**而我自己的教训恰恰是"不要写死条数"。**
    #
    # 真正的修法：检查语义特征。它们**不随编号和条数变化**，因此不会过期。
    if not any(c.cond_type == "计算" for c in conds):
        failures.append("断言1a：一条计算类都没有（六重叠加没标进来）")
    if not any(c.cond_type == "时序互斥" for c in conds):
        failures.append("断言1b：一条时序互斥都没有（grandfathering 分界条件）")
    if not any("老政策" in c.applies_to_cohort for c in conds):
        failures.append("断言1c：缺老政策通道的 cohort（双轨的另一半）")
    if not any(c.is_ambiguous for c in conds):
        failures.append("断言1d：一条 ambiguity 都没有（SPEC §3.5 说约 30% 条件含模糊表述）")
    # 条数下限兜底：防"加载到 0 条 / 极少条"这种极端情况
    if len(conds) < 5:
        failures.append(f"断言1e：只加载到 {len(conds)} 条，疑似加载不完整")

    # 具名常量保留为**可见提醒**（不是断言）：过期时至少能看到它，需要主动改
    if len(conds) != EXPECTED_CONDITION_COUNT:
        print(f"  ⚠️  条数 {len(conds)} 与 EXPECTED_CONDITION_COUNT="
              f"{EXPECTED_CONDITION_COUNT} 不符 —— 不是失败，是提醒你该更新那个常量了")

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

    print(f"  ✅ 断言1（语义特征）：计算类/时序互斥/老政策通道/ambiguity 都在")
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
        # ── 关键用例：**复现 `_03` 当初那个 bug 的原始写法** ──────────
        # 如果这条检测当初就在，`_03` 会在第一次加载时被抓到，
        # 而不是等到"偶然跑了一次真数据"才暴露。
        ("复现 _03 原写法（取值域不相交）",
         '{"cond_id":"t_03","doc_id":"d","applies_to_cohort":"全体",'
         '"cond_type":"资格","field":"education_type","op":"in",'
         '"value":["全日制大专及以上"],"source_text":"全日制大专以上学历"}\n', "抛异常"),
        # ── 对照：同一个字段，**交集存在**时不该误报 ──────────────────
        ("对照：同字段取值域有交集（不该误报）",
         '{"cond_id":"t_04","doc_id":"d","applies_to_cohort":"全体",'
         '"cond_type":"资格","field":"education_type","op":"==",'
         '"value":"全日制","source_text":"全日制大专以上学历"}\n', "通过"),
        # ── 计算类的 field 是输出字段，不该拿画像取值域去查（防假警报）──
        ("对照：计算类的输出字段不该被误报",
         '{"cond_id":"t_09","doc_id":"d","applies_to_cohort":"全体",'
         '"cond_type":"计算","field":"rent","op":"==","value":null,'
         '"formula":"x","source_text":"租金公式"}\n', "通过"),
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
