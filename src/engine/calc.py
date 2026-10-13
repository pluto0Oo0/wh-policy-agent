"""金额计算 —— 纯代码，不调任何模型（SPEC §3.6）。

SPEC §5 签名（不得改名）：
    calc_amount(profile, condition) -> dict | None

返回 SPEC §2.4 的 `amount` 契约：
    {"type": "monthly"|"onetime", "value": float, "detail": str}
**算不出返回 None** —— 不返回 0、不返回空壳。

════════════════════════════════════════════════════════════════
为什么算不出要返回 None，而不是 0
════════════════════════════════════════════════════════════════
返回 0 会被读成"**你能省 0 元**"——一个确定的、错误的答案。
返回 None 会被读成"**这条我算不出来**"——诚实的、可追问的。

这和 `eligibility.py` 里「UNKNOWN 不是 INELIGIBLE」是同一条原则的第三次应用：
**"不知道" 和 "是 0" 是两件事。**

════════════════════════════════════════════════════════════════
⚠️ 契约缺口：`formula` 是自由文本，引擎执行不了
════════════════════════════════════════════════════════════════
SPEC §2.2 的 `formula` 存的是人话，例如：

    "博士: 免租2年,封顶2000元/月; 硕士: 免租1年,封顶1500元/月; 其他: 免租0;
     免租期后=市场租金×70%(不高于); 累计减免≤3年"

**这段文字机器执行不了。** 要通用执行，得先把 `formula` 变成结构化格式
（小 DSL 或 JSON 表达式）——**那是 SPEC 层面的决定，已报 wb/所有者，待批。**

**在那之前，本模块的做法**：按**已知形态**分派到写好的 Python 函数，
并且**只处理能识别的形态**；识别不了的**返回 None 并在 detail 里说清楚**。
→ **宁可说"我算不了"，不要用一套通用代码去算一种它没见过的规则。**
"""

from src.conditions.model import CALC_TYPE, Condition

# ── 已知的计算形态（目前只有一种，就是 78 号文那条）──────────
# 识别标志：公式里同时出现这几个片段。
# 为什么用标志片段而不是 cond_id：cond_id 会随标注变动漂移
# （2026-10-13 已经因为写死编号栽过一次）。
HOUSING_RULE_MARKERS = ("免租", "市场租金", "70%")

# 六重叠加的六个参数（SPEC §3.4 逐项对应）
FREE_YEARS_BY_EDUCATION = {"博士": 2, "硕士": 1}
FREE_CAP_PER_MONTH = {"博士": 2000.0, "硕士": 1500.0}
DISCOUNT_RATE = 0.70          # 「不高于市场租金的70%」
MAX_DISCOUNT_YEARS = 3        # 「累计减免期限不超过3年」
MONTHS_PER_YEAR = 12


def _is_housing_rule(condition: Condition) -> bool:
    """判断这条计算类条件是不是「人才租赁房六重叠加」形态。"""
    f = condition.formula or ""
    return all(m in f for m in HOUSING_RULE_MARKERS)


def _calc_housing(profile: dict) -> dict | None:
    """人才租赁房六重叠加（武政办〔2022〕78号原文）。

    原文：
    > 按照**不高于市场租金的70%**缴纳租金，**累计减免期限不超过3年**。其中，
    > 全日制博士、硕士**分别免缴2年、1年**租金，**免租金额每月分别不超过
    > 2000元、1500元**。

    拆成六重（SPEC §3.4）：
        1. 租金 = 市场租金 × ≤70%      ← 注意「**不高于**」，不是「等于」
        2. 累计减免 ≤ 3 年
        3. 博士免缴 2 年 / 4. 硕士免缴 1 年
        5. 免租金额：博士 ≤2000 元/月、硕士 ≤1500 元/月
        6. 续期（+2 年，延长期按市场价）—— **78 号文原文没有这句**，
           来自别的文件，纵切不做（标 `未核实`）

    返回：
        dict  —— 能算
        None  —— 缺 `market_rent`，算不了（**这是最常见的分支**）
    """
    market_rent = profile.get("market_rent")

    # ── 第 1 重的前提：没有市场租金，什么都算不了 ────────────────
    # 为什么这是"算不了"而不是"按 0 算"：
    #   「不高于市场租金的70%」里的市场租金是**用户所在房源的实际租金**，
    #   系统无从得知。**编一个数就是在编答案。**
    if market_rent is None:
        return None

    try:
        market_rent = float(market_rent)
    except (TypeError, ValueError):
        return None

    education = profile.get("education")
    free_years = FREE_YEARS_BY_EDUCATION.get(education, 0)
    free_cap = FREE_CAP_PER_MONTH.get(education, 0.0)

    # ── 第 2 重：累计减免 ≤ 3 年（免租期先占额度）────────────────
    free_years = min(free_years, MAX_DISCOUNT_YEARS)
    discounted_years = MAX_DISCOUNT_YEARS - free_years

    # ── 第 5 重：免租期的月省金额有**分层封顶** ──────────────────
    # 封顶的含义：免租期本可省下全部市场租金，但政策只免到 2000/1500 为止。
    free_saving_per_month = min(market_rent, free_cap) if free_years else 0.0

    # ── 第 1 重：免租期之后按「不高于 70%」缴，即省 30% ──────────
    # ⚠️「不高于 70%」意味着**实际折扣由各区房源定**，30% 是**下限**不是定值。
    #    所以 detail 里必须写清"这是按上限算的"，不能当成精确值输出。
    discounted_saving_per_month = market_rent * (1 - DISCOUNT_RATE)

    total = (
        free_saving_per_month * free_years * MONTHS_PER_YEAR
        + discounted_saving_per_month * discounted_years * MONTHS_PER_YEAR
    )

    detail = (
        f"按市场租金 {market_rent:.0f} 元/月估算："
        + (
            f"前 {free_years} 年免租（每月免 {free_saving_per_month:.0f} 元，"
            f"封顶 {free_cap:.0f} 元），"
            if free_years
            else "无免租期，"
        )
        + f"其余 {discounted_years} 年在 3 年减免期内按不高于市场租金的 70% 缴纳。"
        f"⚠️「不高于 70%」是上限，实际折扣由各区房源确定，本数偏高。"
    )

    return {
        "type": "onetime",  # 3 年累计总额，不是月额
        "value": round(total, 2),
        "detail": detail,
        # 额外的结构化字段，供 CLI 分层展示（SPEC §2.4 只要求三个 key，多给不冲突）
        "monthly_free": round(free_saving_per_month, 2),
        "free_years": free_years,
        "discounted_years": discounted_years,
        "assumption": "market_rent 由用户提供，非系统查询所得",
    }


def calc_amount(profile: dict, condition: Condition) -> dict | None:
    """算一条计算类条件的金额。

    参数：
        profile:   用户画像（SPEC §2.3）
        condition: 一条 `cond_type == "计算"` 的条件

    返回：
        SPEC §2.4 的 `amount` dict；**算不出返回 None**

    抛出：
        CalcError: 传进来的不是计算类条件（那是调用方的 bug，不该静默）

    为什么不是计算类要抛异常：
        静默返回 None 的话，调用方会把"传错类型"当成"算不出来"，
        **错误就此静默固化** —— 和本模块开头那条原则一致。
    """
    if condition.cond_type != CALC_TYPE:
        raise CalcError(
            f"{condition.cond_id} 的 cond_type={condition.cond_type!r} 不是计算类，"
            f"不该调 calc_amount"
        )

    if _is_housing_rule(condition):
        return _calc_housing(profile)

    # 识别不了的计算形态 → **说清"我算不了"，不要硬算**
    return {
        "type": "unknown",
        "value": None,
        "detail": (
            f"这条计算类条件的形态引擎不认识，未计算。"
            f"原因：`formula` 是自由文本，引擎只能执行已知形态"
            f"（目前只有「人才租赁房六重叠加」）。"
            f"formula={condition.formula!r}"
        ),
    }


class CalcError(ValueError):
    """调用 calc_amount 的方式不对（如传了非计算类条件）。"""


# ══════════════════════════════════════════════════════════════
# 验收：python -m src.engine.calc
# ══════════════════════════════════════════════════════════════


def _run_acceptance() -> int:
    """四条断言 + 故障注入，返回退出码（0 = 全过）。"""
    import json
    from pathlib import Path

    from src.conditions.loader import GOLDEN_PATH, load_conditions

    root = Path(__file__).resolve().parents[2]
    conds = load_conditions(GOLDEN_PATH)
    calc_cond = next(c for c in conds if c.cond_type == CALC_TYPE)
    profile = json.loads((root / "data" / "profile.json").read_text(encoding="utf-8"))

    print(f"计算类条件：{calc_cond.cond_id}（{calc_cond.field}）\n")

    failures: list[str] = []

    # 断言 1：画像缺 market_rent 时必须返回 None（**不能返回 0**）
    r_none = calc_amount(profile, calc_cond)
    if r_none is not None:
        failures.append(f"断言1：缺 market_rent 时应返回 None，实得 {r_none!r}")
    print(f"  缺 market_rent → {r_none!r}   （预期 None，**不是 0**）")

    # 断言 2：给了 market_rent 要能算，且结果结构符合 SPEC §2.4
    for edu, mrent, want_free_years in (("博士", 3000.0, 2), ("硕士", 3000.0, 1), ("本科", 3000.0, 0)):
        p = {**profile, "education": edu, "market_rent": mrent}
        r = calc_amount(p, calc_cond)
        if not r or r["type"] == "unknown":
            failures.append(f"断言2：{edu} 应能算出金额，实得 {r!r}")
            continue
        if r["free_years"] != want_free_years:
            failures.append(f"断言2：{edu} 免租期应 {want_free_years} 年，实得 {r['free_years']}")
        print(f"  {edu} 市场租金 {mrent:.0f} → 3 年累计省 {r['value']:.0f} 元"
              f"（免租 {r['free_years']} 年 × {r['monthly_free']:.0f} 元/月 + "
              f"{r['discounted_years']} 年 × 30%）")

    # 断言 3：博士的免租封顶必须生效（市场租金 5000 > 封顶 2000）
    p = {**profile, "education": "博士", "market_rent": 5000.0}
    r = calc_amount(p, calc_cond)
    if r["monthly_free"] != 2000.0:
        failures.append(f"断言3：博士免租应被封顶到 2000，实得 {r['monthly_free']}")
    print(f"  博士 市场租金 5000 → 每月免 {r['monthly_free']:.0f} 元   （预期 2000，封顶生效）")

    # 断言 4：3 年封顶必须生效（博士免 2 年，减免期只剩 1 年）
    if r["free_years"] + r["discounted_years"] != 3:
        failures.append("断言4：免租年数 + 折扣年数 应等于 3")
    print(f"  博士：免租 {r['free_years']} 年 + 折扣 {r['discounted_years']} 年 = 3 年   （3 年封顶）")

    print()
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
        return 1
    print("  ✅ 断言1-4 全过")
    return 0


def _run_fault_injection() -> int:
    """故障注入：坏输入必须被抓到。"""
    from src.conditions.loader import GOLDEN_PATH, load_conditions

    conds = load_conditions(GOLDEN_PATH)
    calc_cond = next(c for c in conds if c.cond_type == CALC_TYPE)
    qual_cond = next(c for c in conds if c.cond_type == "资格")

    cases = [
        ("传非计算类条件 → 必须抛异常",
         lambda: calc_amount({}, qual_cond), True),
        ("正常计算不抛异常",
         lambda: calc_amount({"education": "本科", "market_rent": 2000.0}, calc_cond), False),
        ("market_rent 是字符串数字也能算",
         lambda: calc_amount({"education": "本科", "market_rent": "2000"}, calc_cond), False),
        ("market_rent 是乱码 → 返回 None 不崩",
         lambda: calc_amount({"education": "本科", "market_rent": "不是数字"}, calc_cond), False),
    ]

    print("=" * 62)
    print("故障注入")
    print("=" * 62)
    bad = 0
    for label, fn, want_raise in cases:
        try:
            res = fn()
            got = False
        except CalcError:
            res, got = None, True
        ok = got == want_raise
        if not ok:
            bad += 1
        print(f"  {'✅' if ok else '🔴'} {label:<30} 期望{'抛异常' if want_raise else '正常'} / "
              f"实际{'抛异常' if got else '正常'}")

    # 关键：算不出来必须是 None，不能是 0
    r0 = calc_amount({"education": "本科", "market_rent": "不是数字"}, calc_cond)
    ok0 = r0 is None
    print(f"  {'✅' if ok0 else '🔴'} 乱码租金 → None（**不是 0**）        实得={r0!r}")
    if not ok0:
        bad += 1

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
