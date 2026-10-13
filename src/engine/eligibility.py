"""规则判定 —— 纯代码，不调任何模型。

SPEC §5 签名（不得改名）：
    check_eligibility(profile, conditions) -> dict   # 返回 SPEC §2.4 契约

════════════════════════════════════════════════════════════════
为什么判定必须是纯代码（SPEC §3.6）
════════════════════════════════════════════════════════════════
**可判定的事不交给模型。** 比大小、查区间、算封顶 —— 这些是确定性问题，
用 LLM 做只会引入不确定性和幻觉。LLM 的活是"从文本抽条件"（Phase 2），
不是"判断张三符不符合"。

════════════════════════════════════════════════════════════════
三种"不通过"必须分开（这是本模块最核心的设计）
════════════════════════════════════════════════════════════════
| 状态 | 含义 | 用户的处境 |
|---|---|---|
| `PASS` | 符合 | — |
| `FAIL` | **确实不符合** | "你不满足这条" |
| `UNKNOWN` | **信息不足，判不了** | "告诉我 X 我就能判" |
| `N/A` | **这条规则不适用于你** | "你该走另一条轨道" |

**把 `UNKNOWN` 当成 `FAIL` 的后果**：用户被告知"你不符合"，
而他其实只是**没填某个字段** —— 他会放弃申请，而这可能是错的。

**把 `N/A` 当成 `FAIL` 的后果**：老轨道的人去看新政策条件，被判"不符合"，
**看起来像他自己的问题**，真相是他该走另一条轨道。

**汇总规则**：`FAIL` 优先于 `UNKNOWN`（有一条确定不符合，就不用再问了）；
但**只要有一条 UNKNOWN 且没有 FAIL，整体就是 UNKNOWN**，不许硬给 ELIGIBLE。
"""

from src.conditions.model import Condition
from src.engine.cohort import CohortError, resolve_cohort

# ── 单条条件的判定结果 ──────────────────────────────────────
PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
NOT_APPLICABLE = "N/A"  # 不适用（cohort 不匹配），**不是失败**

# ── 整体判定（SPEC §2.4）────────────────────────────────────
VERDICT_ELIGIBLE = "ELIGIBLE"
VERDICT_INELIGIBLE = "INELIGIBLE"
VERDICT_UNKNOWN = "UNKNOWN"

# ── 政策有效性（SPEC §2.1 / §3.5b）──────────────────────────
STATUS_CURRENT = "现行"
STATUS_REPEALED = "已废止"
STATUS_PARTIAL = "部分失效"
STATUS_UNVERIFIED = "未核实"

# 参与"资格判定"的条件类型。计算类不参与 —— 它产出的是金额，不是资格。
ELIGIBILITY_TYPES = ("资格", "时序互斥", "材料")


class EligibilityError(ValueError):
    """判定过程中的可预期错误。"""


def _derive_fields(profile: dict, as_of_year: int) -> dict:
    """补出「条件里用到、但画像里没直接给」的派生字段。

    为什么需要这一层：
        SPEC §2.3 的画像给的是 `grad_year`（毕业**年份**，如 2026），
        而条件 `_05` 判的是 `grad_years`（毕业**年数**，`<= 6`）。
        同一个事实的两种表示 —— **必须有人换算**。

    **为什么换算是引擎的活、不是标注的活**：
        标注只负责"把原文抄准"（原文写的是「毕业6年以内」）。
        "用年份减还是用月数算"是实现细节，不该让标注去管 ——
        否则同一条政策换个实现方式就要重标一次。

    ⚠️ **这让判定结果依赖当前时间**（"毕业6年以内"是滚动窗口）。
       这是**对的**——政策窗口本来就是滚动的。
       但意味着测试要能固定时间，所以 `as_of_year` 是参数而不是写死 `date.today()`。
    """
    derived = dict(profile)

    grad_year = derived.get("grad_year")
    if grad_year and "grad_years" not in derived:
        try:
            derived["grad_years"] = as_of_year - int(grad_year)
        except (TypeError, ValueError):
            # 年份不是数字 → 不派生，让下游判成 UNKNOWN 并把这个字段报出去
            pass

    return derived


def _compare(left, op: str, right) -> bool:
    """按 op 比较两个值。

    为什么 `<` `>` 也要在这里实现：
        SPEC §2.2 的 op 清单原本只有 `>=` `<=` `==` `in` `exists`，
        但真实标注里「年龄**不满**45周岁」「本通知公布**前**留汉」的语义就是 `<`。
        （详见 src/conditions/model.py 里 OPS 的注释）
    """
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    if op == "<":
        return left < right
    if op == ">":
        return left > right
    if op == "in":
        # right 是候选集合。注意 profile 里的值必须**恰好等于**其中一项，
        # 不做模糊匹配 —— 模糊匹配会把"全日制"和"全日制大专及以上"判成同一个东西。
        return left in right
    raise EligibilityError(f"不支持的 op：{op!r}")


def _eval_condition(profile: dict, cond: Condition) -> tuple[str, str | None]:
    """判定单条条件。

    返回：
        (状态, 缺失字段名或 None)

    判定顺序（**顺序本身是设计**）：
        1. cohort 不适用 → N/A（**先分流，再判内容**）
        2. 有 ambiguity  → UNKNOWN（模糊表述判不了，不许硬答）
        3. 画像缺字段    → UNKNOWN + 记下缺哪个
        4. 正常比较      → PASS / FAIL
    """
    # ── 1. 轨道分流 ─────────────────────────────────────────
    try:
        if not resolve_cohort(profile, cond):
            return NOT_APPLICABLE, None
    except CohortError as e:
        # 缺分界字段 → 判不了轨道 → UNKNOWN，并把缺的字段报出来
        if "first_insurance_date" in str(e):
            return UNKNOWN, "first_insurance_date"
        raise

    # ── 2. 模糊表述 ─────────────────────────────────────────
    # SPEC §3.5：ambiguity 非 null 时**判定必须返回 UNKNOWN**，不许硬给答案。
    # 约 30% 的条件含模糊/需裁量表述（调研报告 §5.2 实测）。
    if cond.is_ambiguous:
        return UNKNOWN, None

    # ── 3. 画像字段 ─────────────────────────────────────────
    if cond.op == "exists":
        # exists 判的是"字段有没有值"，不是"值等于什么"
        value = profile.get(cond.field)
        return (PASS if value not in (None, "") else FAIL), None

    if cond.field not in profile or profile[cond.field] is None:
        return UNKNOWN, cond.field

    # ── 4. 比较 ─────────────────────────────────────────────
    return (PASS if _compare(profile[cond.field], cond.op, cond.value) else FAIL), None


def check_eligibility(
    profile: dict,
    conditions: list[Condition],
    *,
    policy_meta: dict | None = None,
    as_of_year: int | None = None,
) -> dict:
    """对一份画像做全部条件的判定，返回 SPEC §2.4 契约。

    参数：
        profile:     用户画像（SPEC §2.3）
        conditions:  该政策的全部条件
        policy_meta: 政策元信息（title / doc_number / policy_status / where_to_apply），
                     来自 `policies.jsonl` 的一条。缺省时用安全默认值。
        as_of_year:  判定基准年份，用于算"毕业N年以内"这类滚动窗口。
                     **缺省取当前年份**；测试时传入以固定时间。

    返回：SPEC §2.4 的 dict。

    抛出：
        EligibilityError: conditions 为空（见下）
    """
    # ── 空条件必须报错，不能"全通过" ─────────────────────────
    # 零条件的循环不会执行任何判定 → reasons 为空 → 没有 FAIL → 判 ELIGIBLE。
    # **对每个人都判"能享受"，而且是确定的口气。** 这是最危险的一类输出。
    if not conditions:
        raise EligibilityError(
            "条件列表为空，无法判定。\n"
            "→ 直接返回会让空循环产出 ELIGIBLE（没有条件要满足），"
            "对每个人都判'能享受'。宁可报错。"
        )

    if as_of_year is None:
        from datetime import date

        as_of_year = date.today().year
    profile = _derive_fields(profile, as_of_year)

    meta = policy_meta or {}
    policy_status = meta.get("policy_status", STATUS_UNVERIFIED)

    # ── SPEC §3.5b：已废止的政策不参与判定 ────────────────────
    # 给已废止政策做资格判定，无论结果是什么都是错的：
    #   ELIGIBLE 是错的（申请不了）；INELIGIBLE 也是错的（误导用户以为只是自己不符合）。
    if policy_status == STATUS_REPEALED:
        return {
            "policy_id": meta.get("doc_id", ""),
            "policy_title": meta.get("title", ""),
            "doc_number": meta.get("doc_number", ""),
            "verdict": VERDICT_INELIGIBLE,
            "reasons": [],
            "missing_fields": [],
            "amount": None,
            "policy_status": policy_status,
            "status_warning": "该政策已废止，不参与判定。",
            "where_to_apply": None,
        }

    reasons: list[dict] = []
    missing: list[str] = []

    for cond in conditions:
        if cond.cond_type not in ELIGIBILITY_TYPES:
            # 计算类不参与资格判定（它产出金额，由 calc.py 处理）
            continue
        status, missing_field = _eval_condition(profile, cond)
        reasons.append(
            {"cond_id": cond.cond_id, "status": status, "source_text": cond.source_text}
        )
        if missing_field and missing_field not in missing:
            missing.append(missing_field)

    # ── 汇总（FAIL 优先于 UNKNOWN）──────────────────────────
    statuses = {r["status"] for r in reasons}
    if FAIL in statuses:
        verdict = VERDICT_INELIGIBLE
    elif UNKNOWN in statuses:
        # **不许把 UNKNOWN 当 ELIGIBLE**：那等于默认成立
        verdict = VERDICT_UNKNOWN
    else:
        verdict = VERDICT_ELIGIBLE

    # ── status_warning（SPEC §3.5b）──────────────────────────
    status_warning = None
    if policy_status == STATUS_PARTIAL:
        status_warning = "该政策部分失效，结论仅供参考。"
    elif policy_status == STATUS_UNVERIFIED:
        status_warning = "该政策状态未核实，请以官方口径为准。"

    return {
        "policy_id": meta.get("doc_id", ""),
        "policy_title": meta.get("title", ""),
        "doc_number": meta.get("doc_number", ""),
        "verdict": verdict,
        "reasons": reasons,
        "missing_fields": missing if verdict == VERDICT_UNKNOWN else [],
        "amount": None,  # 由 calc_amount 填（纵切第 9 步）
        "policy_status": policy_status,
        "status_warning": status_warning,
        "where_to_apply": meta.get("where_to_apply"),
    }


# ══════════════════════════════════════════════════════════════
# 验收：python -m src.engine.eligibility
# ══════════════════════════════════════════════════════════════


def _load_fixtures():
    import json
    from pathlib import Path

    from src.conditions.loader import GOLDEN_PATH, load_conditions

    root = Path(__file__).resolve().parents[2]
    conds = load_conditions(GOLDEN_PATH)
    doc = [json.loads(l) for l in (root / "data" / "processed" / "policies.jsonl")
           .read_text(encoding="utf-8").splitlines() if l.strip()][0]
    profile = json.loads((root / "data" / "profile.json").read_text(encoding="utf-8"))
    return conds, doc, profile


def _run_acceptance() -> int:
    conds, doc, profile = _load_fixtures()
    print(f"画像：{profile}")
    print(f"条件：{len(conds)} 条\n")

    r = check_eligibility(profile, conds, policy_meta=doc)
    print(f"verdict        : {r['verdict']}")
    print(f"policy_status  : {r['policy_status']}   警告：{r['status_warning']}")
    print(f"missing_fields : {r['missing_fields']}")
    print("\n逐条：")
    for x in r["reasons"]:
        print(f"  {x['cond_id'][-2:]}  {x['status']:<8} {x['source_text'][:34]}")

    failures: list[str] = []
    # 断言 1：reasons 每条都带 source_text（SPEC §2.4 硬要求）
    if not all(x["source_text"] for x in r["reasons"]):
        failures.append("断言1：有 reason 缺 source_text")
    # 断言 2：未核实状态必须带 warning，不许静默给结论
    if r["policy_status"] == "未核实" and not r["status_warning"]:
        failures.append("断言2：未核实却没有 status_warning")
    # 断言 3：verdict 必须是三个合法值之一
    if r["verdict"] not in ("ELIGIBLE", "INELIGIBLE", "UNKNOWN"):
        failures.append(f"断言3：verdict={r['verdict']!r} 不合法")
    # 断言 4：UNKNOWN 时必须列出缺哪些字段
    if r["verdict"] == "UNKNOWN" and not r["missing_fields"]:
        failures.append("断言4：UNKNOWN 但 missing_fields 为空（用户不知道该补什么）")

    print()
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
        return 1
    print("  ✅ 断言1：每条 reason 都带 source_text")
    print("  ✅ 断言2：未核实状态带 status_warning")
    print("  ✅ 断言3：verdict 合法")
    print("  ✅ 断言4：UNKNOWN 时列出了缺失字段")
    return 0


def _run_fault_injection() -> int:
    """故障注入：坏输入必须被抓到。"""
    conds, doc, profile = _load_fixtures()

    cases = [
        ("空条件列表必须抛异常", lambda: check_eligibility(profile, []), True),
        ("正常判定不抛异常", lambda: check_eligibility(profile, conds, policy_meta=doc), False),
    ]
    print("=" * 62)
    print("故障注入")
    print("=" * 62)
    bad = 0
    for label, fn, want_raise in cases:
        try:
            fn()
            got = False
        except EligibilityError:
            got = True
        ok = got == want_raise
        if not ok:
            bad += 1
        print(f"  {'✅' if ok else '🔴'} {label:<24} 期望{'抛异常' if want_raise else '正常'} / "
              f"实际{'抛异常' if got else '正常'}")

    # 已废止政策必须不参与判定
    r = check_eligibility(profile, conds, policy_meta={**doc, "policy_status": "已废止"})
    ok = r["reasons"] == [] and r["status_warning"]
    print(f"  {'✅' if ok else '🔴'} 已废止政策不参与判定        reasons={len(r['reasons'])} 条")
    if not ok:
        bad += 1

    # 缺失字段 → 该字段必须被记成 UNKNOWN（**不测整体 verdict**：
    # 只要还有别的条件 FAIL，整体就是 INELIGIBLE，那是对的，不该拿来测"缺字段"这个机制）
    thin = {k: v for k, v in profile.items() if k not in ("housing_owned_in_wuhan", "social_insurance_active")}
    r2 = check_eligibility(thin, conds, policy_meta=doc)
    unknown_ids = {x["cond_id"][-2:] for x in r2["reasons"] if x["status"] == UNKNOWN}
    ok2 = {"07", "06"} <= unknown_ids
    print(f"  {'✅' if ok2 else '🔴'} 缺字段 → 对应条件记 UNKNOWN     UNKNOWN 的条件={sorted(unknown_ids)}")
    if not ok2:
        bad += 1

    # UNKNOWN 但**没有 FAIL** 时，整体 verdict 必须是 UNKNOWN（不许硬给 ELIGIBLE）
    only_unknown = [c for c in conds if c.cond_id.endswith(("_06", "_07"))]
    r3 = check_eligibility({}, only_unknown, policy_meta=doc)
    ok3 = r3["verdict"] == "UNKNOWN" and r3["missing_fields"]
    print(f"  {'✅' if ok3 else '🔴'} 全 UNKNOWN → verdict=UNKNOWN     verdict={r3['verdict']} "
          f"缺={r3['missing_fields']}")
    if not ok3:
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
