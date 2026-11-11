"""人群分层 —— grandfathering 双轨的落点。

SPEC §5 签名（不得改名）：
    resolve_cohort(profile, condition) -> bool

════════════════════════════════════════════════════════════════
这个模块在解决什么（SPEC §3.2，本项目最有技术含量的设计）
════════════════════════════════════════════════════════════════
武汉的安居政策有**两套并行规则**，不是"新的替代旧的"：

  老政策（武房规〔2018〕2号）：毕业 3 年内 + 武汉户籍 + 家庭无房
  新政策（武政办〔2022〕78号）：毕业 6 年内 + 社保 + 家庭无房
  **分界点：2022-06-07**（以**首次缴纳社保时点**认定，不是申请时点）

→ 所以 **"取最新版本"是错的**。同一份画像，走哪条轨道拿到的答案不一样。
  而且**轨道判断本身就是一个条件**（`_04` / `_09` 两条时序互斥条件）。

════════════════════════════════════════════════════════════════
本模块最容易被写错的一处：**"不适用" ≠ "不符合"**
════════════════════════════════════════════════════════════════
    一个 2021 年留汉的人，去看新政策的「毕业 6 年内」这条 —— 该判 FAIL 吗？

    **不该。** 那条规则**根本不适用于他**。
    判 FAIL 的后果是：他被判定为"不符合新政策"，**看起来像他自己的问题**；
    真相是"他该走另一条轨道"。

    → 所以 `resolve_cohort` 返回 False 时，调用方必须**跳过**这条条件
      （记为 `N/A`），**不是记 `FAIL`**。

    这正是 SPEC §3.5「UNKNOWN 不是 INELIGIBLE」的同一个原则的第二次应用：
    **"不适用" / "不知道" / "不符合" 是三件事，混成两件就会误导用户。**
"""

from src.conditions.model import Condition

# ── 三个规范 cohort 名 ──────────────────────────────────────
COHORT_ALL = "全体"
COHORT_NEW = "新政策通道"
COHORT_OLD = "老政策通道"

# grandfathering 分界点（SPEC §3.2）
# ⚠️ 这个日期是**市级**的分界（78号文印发日 2022-06-07）。
#    汉阳区还有自己的分界 2022-09-16（按政策印发日，不是社保时点），
#    两者不能混 —— 见 CONTEXT.md 政策层结论 7。
BOUNDARY_DATE = "2022-06-07"

# 分界依据字段（SPEC §2.3 明确：`first_insurance_date` 是 grandfathering 的分界依据）
BOUNDARY_FIELD = "first_insurance_date"


class CohortError(ValueError):
    """cohort 相关数据不合法（如条件里写了一个无法识别的 cohort 名）。"""


def classify_cohort(applies_to_cohort: str) -> str:
    """把条件里的 `applies_to_cohort` 归一到三个规范值之一。

    为什么需要归一、而不是直接字符串相等比较：
        标注时写的是自由文本。实测 golden set 里出现过
        「新政策通道的分界本身」——它**不是**规范名，但语义上属于新政策通道。

    为什么匹配失败必须抛异常、不能默认成「全体」：
        **默认成「全体」= 把一条只适用于老人的规则套到所有人身上**，
        结果是对新人也判这条条件 —— **错误静默扩散到每一条画像**。
        宁可加载时就炸。
    """
    if applies_to_cohort == COHORT_ALL:
        return COHORT_ALL
    if COHORT_OLD in applies_to_cohort:
        return COHORT_OLD
    if COHORT_NEW in applies_to_cohort:
        return COHORT_NEW
    raise CohortError(
        f"无法识别的 applies_to_cohort={applies_to_cohort!r}，"
        f"应含「{COHORT_OLD}」或「{COHORT_NEW}」，或恰为「{COHORT_ALL}」"
    )


def resolve_cohort(profile: dict, condition: Condition) -> bool:
    """判断该画像是否落在该条件的**适用人群**内。

    参数：
        profile:   用户画像（SPEC §2.3）
        condition: 一条条件

    返回：
        True  → 这条条件适用于他，**照常判定**
        False → **不适用**，调用方必须**跳过**（记 N/A），不是记 FAIL

    抛出：
        CohortError: 条件的 cohort 名无法识别；或轨道判定缺少必要画像字段
    """
    cohort = classify_cohort(condition.applies_to_cohort)

    # 全体适用：与轨道无关
    if cohort == COHORT_ALL:
        return True

    # 轨道判定依据：首次缴纳社保时点（SPEC §2.3）
    first_insurance = profile.get(BOUNDARY_FIELD)
    if not first_insurance:
        # 缺这个字段就**无法判轨道**。
        # 为什么不默认成某一边：默认哪边都是猜，而猜错会让用户拿到另一条轨道的结果。
        # 按 SPEC §3.5，这种情况该让调用方返回 UNKNOWN 并追问这个字段。
        raise CohortError(
            f"画像缺 {BOUNDARY_FIELD}，无法判定 grandfathering 轨道"
            f"（条件 {condition.cond_id} 属于「{cohort}」）"
        )

    # 字符串比较在 ISO 日期（YYYY-MM-DD）上是安全的：字典序 == 时间序。
    # ⚠️ 但仅限格式严格为 YYYY-MM-DD。格式不对会**静默给出错误结果**，所以先校验。
    if len(str(first_insurance)) != 10 or str(first_insurance)[4] != "-":
        raise CohortError(
            f"{BOUNDARY_FIELD}={first_insurance!r} 不是 YYYY-MM-DD 格式，"
            f"字符串比较会给出错误结果"
        )

    is_new_track = str(first_insurance) >= BOUNDARY_DATE
    return is_new_track if cohort == COHORT_NEW else not is_new_track


# ══════════════════════════════════════════════════════════════
# 验收：python -m src.engine.cohort
# ══════════════════════════════════════════════════════════════


def _run_acceptance() -> int:
    """四条断言 + 故障注入，返回退出码（0 = 全过）。"""
    from src.conditions.loader import GOLDEN_PATH, load_conditions

    conds = load_conditions(GOLDEN_PATH)
    failures: list[str] = []

    # 断言 1：所有条件的 cohort 名都能归一（识别不了的会在加载时炸）
    print("cohort 归一结果：")
    for c in conds:
        print(f"  {c.cond_id[-2:]}  {c.applies_to_cohort!r:<22} → {classify_cohort(c.applies_to_cohort)}")

    # 断言 2：分界两侧的画像分别落在正确轨道
    new_profile = {"first_insurance_date": "2022-06-07"}  # 恰好当天 → 新政策（>=）
    old_profile = {"first_insurance_date": "2022-06-06"}  # 前一天   → 老政策
    all_profile = {"first_insurance_date": "2022-01-01"}  # 全体条件不看这个

    # ⚠️ v4（2026-11-11）起，同轨道条件已有多条（区级条件并入），
    #    原来"恰好命中一条"的断言会失效。这里改成**显式点名 78 号文的三条**，
    #    并核对它们确实属于预期轨道 —— ID 变更时炸，而不是静默换一条对象。
    #    为什么点名而不是按后缀选：2026-10-13 重编号后，按 `_04`/`_09` 后缀选
    #    **静默选错了条件**，测试红了 2.5 小时还打印"✅ 全部符合预期"。
    #    点名 + 核对 cohort 是双重校验：改名会炸，语义变了也会炸。
    #    ⚠️ 显式 raise 不用 assert（NF-2，wb 2026-10-19）：`python -O` 会剥掉 assert，
    #       保障随之静默消失 —— 保障机制不该依赖可被编译选项关掉的语法。
    def _pick_explicit(cond_id: str, cohort: str):
        hits = [c for c in conds if c.cond_id == cond_id]
        if len(hits) != 1:
            raise AssertionError(f"测试对象选择：{cond_id} 命中 {len(hits)} 条（期望恰好 1 条）")
        got = classify_cohort(hits[0].applies_to_cohort)
        if got != cohort:
            raise AssertionError(
                f"测试对象选择：{cond_id} 的轨道是 {got}，期望 {cohort} —— 条件语义变了")
        return hits[0]

    new_cond = _pick_explicit("t20220608_1983869_05", COHORT_NEW)
    old_cond = _pick_explicit("t20220608_1983869_10", COHORT_OLD)
    all_cond = _pick_explicit("t20220608_1983869_01", COHORT_ALL)

    checks = [
        ("新轨道条件对新轨道画像", resolve_cohort(new_profile, new_cond), True),
        ("新轨道条件对老轨道画像", resolve_cohort(old_profile, new_cond), False),
        ("老轨道条件对老轨道画像", resolve_cohort(old_profile, old_cond), True),
        ("老轨道条件对新轨道画像", resolve_cohort(new_profile, old_cond), False),
        ("全体条件对任何人", resolve_cohort(all_profile, all_cond), True),
    ]
    for label, got, want in checks:
        if got != want:
            failures.append(f"断言2：{label} 期望 {want} 实得 {got}")

    print()
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
        return 1
    print(f"  ✅ 断言1：{len(conds)} 条 cohort 名全部可归一")
    print("  ✅ 断言2：分界点两侧轨道判定正确（2022-06-07 当天算新政策）")
    return 0


def _run_fault_injection() -> int:
    """故障注入：坏输入必须抛异常，好输入不能误报。"""
    from src.conditions.model import Condition

    def mk(cohort):
        return Condition(cond_id="t_01", doc_id="t", applies_to_cohort=cohort,
                         cond_type="资格", field="f", op="==", value=1, source_text="原文")

    cases = [
        ("无法识别的 cohort 名", lambda: classify_cohort("随便写的"), True),
        ("画像缺 first_insurance_date",
         lambda: resolve_cohort({}, mk(COHORT_NEW)), True),
        ("日期格式不对（会静默判错）",
         lambda: resolve_cohort({"first_insurance_date": "2022/6/7"}, mk(COHORT_NEW)), True),
        ("正常：新轨道", lambda: resolve_cohort({"first_insurance_date": "2023-01-01"}, mk(COHORT_NEW)), False),
        ("正常：全体不需要该字段", lambda: resolve_cohort({}, mk(COHORT_ALL)), False),
    ]

    print("=" * 62)
    print("故障注入：坏输入必须抛异常")
    print("=" * 62)
    bad = 0
    for label, fn, want_raise in cases:
        try:
            fn()
            got = False
        except CohortError:
            got = True
        ok = got == want_raise
        if not ok:
            bad += 1
        print(f"  {'✅' if ok else '🔴'} {label:<28} 期望{'抛异常' if want_raise else '正常'} / "
              f"实际{'抛异常' if got else '正常'}")
    print()
    if bad:
        print(f"🔴 {bad} 个用例不符合预期")
        return 1
    print("✅ 全部符合预期")
    return 0


if __name__ == "__main__":
    code = _run_acceptance()
    print()
    code |= _run_fault_injection()
    raise SystemExit(code)
