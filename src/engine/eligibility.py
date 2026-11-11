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
**全部条件都是 N/A 时同样返回 UNKNOWN** —— 一条 PASS 都没有，不能当"符合"。
"""

from src.conditions.model import CALC_TYPE, Condition, ConditionError
from src.engine.calc import calc_amount
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


def _matches(profile: dict, expr: dict) -> bool | None:
    """判断一个"条件表达式"（dict 形如 `{"field","op","value"}`）对画像是否成立。

    返回：
        True / False  能判定
        None          **判不了**（字段缺失或格式不支持）—— 调用方决定怎么处理

    为什么要单独抽出来：`exempt_when` 是一段**内嵌的子条件**，
    它的求值逻辑和主条件一样，但**处置不同**（主条件判 PASS/FAIL，
    子条件判"要不要豁免"）。抽出来避免两处实现漂移。
    """
    field, op, value = expr.get("field"), expr.get("op"), expr.get("value")
    if op == "exists":
        return field in profile and profile[field] not in (None, "")
    if field not in profile or profile[field] is None:
        return None  # 判不了，不是 False —— 这个区别决定要不要追问用户
    try:
        return _compare(profile[field], op, value)
    except EligibilityError:
        return None


def _eval_normal(profile: dict, cond: Condition) -> tuple[str, str | None]:
    """**不含豁免**的正常判定。

    返回：
        (状态, 缺失字段名或 None)

    为什么要单独抽出来：豁免是否"起了作用"，只能拿正常判定的结果当参照 ——
    见 `_eval_condition` 第 2 步。**不先算出正常结论，就没法判断豁免有没有改变它。**

    顺序（**顺序本身是设计**）：
        1. 有 ambiguity  → UNKNOWN（模糊表述判不了，不许硬答）
        2. 画像缺字段    → UNKNOWN + 记下缺哪个
        3. 正常比较      → PASS / FAIL
    """
    # ── 1. 模糊表述 ─────────────────────────────────────────
    # SPEC §3.5：ambiguity 非 null 时**判定必须返回 UNKNOWN**，不许硬给答案。
    # 约 30% 的条件含模糊/需裁量表述（调研报告 §5.2 实测）。
    if cond.is_ambiguous:
        return UNKNOWN, None

    # ── 2. 画像字段 ─────────────────────────────────────────
    if cond.op == "exists":
        # ⚠️ 「字段不存在」≠「值为 False」—— 这是 UNKNOWN，不是 FAIL。
        #
        # 2026-10-13 实测踩过：`_11`（has_dependents exists）在画像里没这个字段时
        # 被我的实现判成 FAIL，于是整体变 INELIGIBLE —— 而真相是"我们不知道他有没有
        # 需要随迁的家属"，该返回 UNKNOWN 并**追问这个字段**。
        #
        # **判 FAIL 的后果**：用户被告知"你不符合"，而他只是没填一项信息。
        # 这和本模块开头写的「UNKNOWN 不是 INELIGIBLE」是同一条原则 ——
        # 我把它写进了注释，却在 exists 分支上违反了它。
        if cond.field not in profile:
            return UNKNOWN, cond.field
        value = profile[cond.field]
        return (PASS if value not in (None, "") else FAIL), None

    if cond.field not in profile or profile[cond.field] is None:
        return UNKNOWN, cond.field

    # ── 3. 比较 ─────────────────────────────────────────────
    return (PASS if _compare(profile[cond.field], cond.op, cond.value) else FAIL), None


def _eval_condition(profile: dict, cond: Condition) -> tuple[str, str | None, bool]:
    """判定单条条件。

    返回：
        (状态, 缺失字段名或 None, 豁免是否**真正起了作用**)

    第三个返回值是这一版的**关键修正**（2026-10-13，wb 指出）：
        原实现是"`exempt_when` 命中就标 exempted"，**不管正常判定本来会不会通过**。
        后果：23 岁的硕士，`_01`（年龄不满 45 周岁）本来就 PASS，却标成"因豁免而满足"。
        → **豁免机制到底有没有生效，就永远测不出来了** ——
          不管触发没触发都标"因豁免"，这是"永远不报警的检查 == 没检查"的变体。

    现在的判据：**豁免只在它把结论从「不是 PASS」翻成「PASS」时才算数。**
        正常就 PASS → 标"因符合"（不标豁免）
        正常 FAIL / UNKNOWN，豁免后才 PASS → 标"因豁免而满足"

    判定顺序（**顺序本身是设计**）：
        1. cohort 不适用  → N/A（**先分流，再判内容**）
        2. 正常判定       → 作为豁免是否起作用的**参照**
        3. 豁免翻转结论   → PASS + 标记 exempted
    """
    # ── 1. 轨道分流 ─────────────────────────────────────────
    try:
        if not resolve_cohort(profile, cond):
            return NOT_APPLICABLE, None, False
    except CohortError as e:
        # 缺分界字段 → 判不了轨道 → UNKNOWN，并把缺的字段报出来
        if "first_insurance_date" in str(e):
            return UNKNOWN, "first_insurance_date", False
        raise

    normal_status, missing = _eval_normal(profile, cond)

    # ── 2. 豁免条件（exempt_when）─────────────────────────────
    # 语义：子条件对画像成立，**且正常判定本来不通过** → 本条视为满足（PASS）。
    #
    # 78 号文的例子：「年龄不满45周岁（研究生不受年龄限制）」
    #   → 50 岁的博士，`_01` 应该判 **PASS**（他被豁免了，满足落户条件）。
    #   → 判 FAIL 是错的（他会以为自己不能落户）；
    #     判 UNKNOWN 也是错的（问他什么？他的学历已经告诉我们答案了）。
    #   → 但 23 岁的硕士正常就该 PASS —— 这时豁免**没做事**，不许标"因豁免"。
    #
    # 为什么正常判 UNKNOWN 时也算"豁免起了作用"：
    #   比如某条含 ambiguity，正常只会返回"判不了"；豁免命中后能确定答 PASS，
    #   结论从"判不了"变成"符合"，是豁免带来的，必须标出来。
    #
    # ⚠️ 豁免成立时**本条的模糊性已无关紧要**，所以豁免判定在正常判定之后即可，
    #    不需要把 ambiguity 再挪到后面。
    if cond.exempt_when:
        hit = _matches(profile, cond.exempt_when)
        if hit is True and normal_status != PASS:
            return PASS, None, True
        # hit 为 None（豁免字段缺失）且正常判 FAIL → 之前 fall-through 成 FAIL，
        # 但真相是"博士则符合、本科则不符合，我们不知道他是哪种"——
        # 把两种可能压成 FAIL（且压的是坏的那种），违背「UNKNOWN 不是 INELIGIBLE」。
        # → 改判 UNKNOWN，追问的正是豁免字段（wb 2026-10-13 指出，F2）。
        if hit is None and normal_status == FAIL:
            return UNKNOWN, cond.exempt_when["field"], False
        # hit 为 None 但正常判 PASS/UNKNOWN → 豁免不可能让结果更差，
        # 保持正常判定的结论；正判 UNKNOWN 的缺失字段由 _eval_normal 已报出。

    return normal_status, missing, False


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
    # 计算类产出的金额（可能多条；SPEC §2.4 的 amount 是单数，取第一条并说明）
    amounts: list[dict] = []

    for cond in conditions:
        if cond.cond_type == CALC_TYPE:
            # ── 计算类也要进 reasons ────────────────────────────────
            # 🔴 2026-10-13 由 wb 指出：我原来在这里 `continue` 直接跳过了计算类，
            #    于是 `_09`（六重叠加，全项目最复杂的一条）**在输出里彻底消失**——
            #    reasons 只有 12 条 / 条件 13 条，没人看得出来少了一条。
            #
            #    为什么这是 bug：SPEC §2.4 写着 `reasons` 是「**逐条**条件的结果」。
            #    跳过 = 违反了契约，而且**症状是"少了东西"而不是"报错"**。
            #
            #    它什么时候能有确定状态：**已解决** —— `calc.py` 写好并接进来了，
            #    由它算 amount，这里再据"算得出/算不出"定 PASS/UNKNOWN。
            #
            # ── status_detail：区分两种完全不同的 UNKNOWN ──────────────
            # 2026-10-13 由 wb 指出、所有者已批。
            #
            #   "缺 market_rent"  → **数据层**问题，**用户补了就能判**
            #   "形态不认识"      → **引擎层**问题，用户补字段没用
            #
            # 为什么必须区分：不区分的话，一个 UNKNOWN 里混着两种原因，
            # **输出上看不出来** —— 用户会去补一堆字段，然后发现还是 UNKNOWN，
            # 却不知道问题不在他那边。**这是"让人做无用功"的错误信息。**
            amount = calc_amount(profile, cond)
            if amount is None:
                # 算不出来 = **缺输入字段** → 走正常的"缺字段"路径，
                # 让 CLI 用统一的方式追问用户。
                #
                # ⚠️ 这个字段名是**与计算规则耦合**的（目前只有六重叠加一条规则，
                #    它第 1 重依赖 market_rent）。
                #    等 `formula` 结构化后，"缺哪个字段"应由规则自己声明，
                #    而不是写死在引擎里。**已记为契约缺口。**
                status, detail, missing_field = UNKNOWN, None, "market_rent"
            elif amount.get("type") == "unknown":
                # 形态不认识：这是**引擎的短板**，不是用户的 —— 才用 status_detail
                status, detail, missing_field = UNKNOWN, amount.get("detail"), None
            else:
                status, detail, missing_field = PASS, None, None
            reasons.append(
                {
                    "cond_id": cond.cond_id,
                    "status": status,
                    "status_detail": detail,
                    "source_text": cond.source_text,
                    # 为什么单独标出来：它和其他条件的**产出语义不同**
                    # （资格类产 PASS/FAIL，计算类产 amount），
                    # 混在同一个 status 里会让人以为"它也是个资格条件"。
                    "is_calc": True,
                }
            )
            if missing_field and missing_field not in missing:
                missing.append(missing_field)
            if amount and amount.get("type") != "unknown":
                amounts.append(amount)
            continue

        status, missing_field, exempted = _eval_condition(profile, cond)
        reason = {"cond_id": cond.cond_id, "status": status, "source_text": cond.source_text}
        if exempted:
            # 为什么必须记下"豁免了什么"：
            #   用户看到「年龄不满45周岁 → PASS」会困惑（他 50 岁）。
            #   **只给结论不给理由，等于让他怀疑系统算错了。**
            #   带上 exempted_by，输出就能说清"因研究生学历豁免"。
            reason["exempted"] = True
            reason["exempted_by"] = cond.exempt_when
        reasons.append(reason)
        if missing_field and missing_field not in missing:
            missing.append(missing_field)

    # ── 汇总（FAIL 优先于 UNKNOWN；全部 N/A 不能当 ELIGIBLE）────
    statuses = {r["status"] for r in reasons}
    all_na = statuses == {NOT_APPLICABLE}
    if FAIL in statuses:
        verdict = VERDICT_INELIGIBLE
    elif all_na:
        # 全部条件都不适用于这个画像（例：老政策文档 × 新轨道画像）。
        # **一条 PASS 都没有，凭什么说"符合"？** 2026-11-11 v4 实测：
        # 汉阳解读 3 条全是老轨道，新轨道画像曾被判 ELIGIBLE —— 假阳性。
        verdict = VERDICT_UNKNOWN
    elif UNKNOWN in statuses:
        # **不许把 UNKNOWN 当 ELIGIBLE**：那等于默认成立
        verdict = VERDICT_UNKNOWN
    else:
        verdict = VERDICT_ELIGIBLE

    # ── status_warning（SPEC §3.5b）──────────────────────────
    status_warning = None
    if all_na:
        status_warning = "该政策的全部条件都不适用于你的政策轨道（老/新），无法给出结论。"
    elif policy_status == STATUS_PARTIAL:
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
        "amount": amounts[0] if amounts else None,
        "amount_count": len(amounts),  # 多条时提示调用方（本期只有 1 条）
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

    # ⚠️ parents[2] 在这里**有意走死**（wb 2026-11-06 三.1 定论）：
    # 本函数是引擎验收自测（python -m src.engine.*），数据源是**真实项目 data/**，
    # 不参与 CHECK_TARGET_DIR 注入场景（那是 scripts/checks 检查器的隔离机制）。
    # 若未来需要把引擎验收指向临时项目，再统一改 config 派生——现在不改是对的。
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
    # 断言 0：**每条条件都必须出现在 reasons 里**。
    #
    # 🔴 这条断言是 2026-10-13 补的，由 wb 指出 `_09` 漏报而引出。
    #    原来没有它，于是计算类被 `continue` 跳过后 **reasons 只有 12 条 / 条件 13 条**，
    #    而**没有任何东西会报警** —— 输出看起来完全正常，只是少了一条。
    #
    #    为什么用"逐条比对 cond_id"而不是"数条数"：
    #      数条数只能发现"少了"，不能发现"少了哪一条"。
    #      逐条比对能直接报出缺失的 cond_id，**报错信息本身就可行动**。
    reason_ids = {x["cond_id"] for x in r["reasons"]}
    missing_ids = [c.cond_id for c in conds if c.cond_id not in reason_ids]
    if missing_ids:
        failures.append(f"断言0：这些条件没进 reasons —— {missing_ids}")

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
    print(f"  ✅ 断言0：{len(conds)} 条条件全部出现在 reasons 里")
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

    # 缺失字段 → 该字段必须被记成 UNKNOWN
    # ⚠️ **不写死 cond_id** —— 条件编号会随 golden set 变动漂移
    #    （2026-10-13 踩过：`_03` 拆两条后全部重编号，写死 `_06`/`_07` 的断言直接失效，
    #     而失效原因是"断言过期"不是"代码错了"。和 loader 里那个写死的 `9` 同一个毛病。）
    #    改成按 `field` 反查该受影响的条，这样重编号不会让它失效。
    removed = ("housing_owned_in_wuhan", "social_insurance_active")
    thin = {k: v for k, v in profile.items() if k not in removed}
    r2 = check_eligibility(thin, conds, policy_meta=doc)
    # v4（2026-11-11）起同一字段出现在多条/多个轨道：老轨道条件对这个新轨道画像
    # 应记 N/A（不适用），不是 UNKNOWN。断言只要求"在适用范围内的受影响条件"变 UNKNOWN。
    affected = {c.cond_id for c in conds if c.field in removed}
    in_scope = {c.cond_id for c in conds
                if c.field in removed and resolve_cohort(thin, c)}
    # 空集合会让 `in_scope <= got_unknown` 恒真 —— 正是第 10.1 条 Q5 的"空输入输出 ✅"。
    if not in_scope:
        print("  🔴 缺字段断言：在轨道内命中 0 条，断言恒真（golden 结构变了？）")
        return 1
    got_unknown = {x["cond_id"] for x in r2["reasons"] if x["status"] == UNKNOWN}
    ok2 = in_scope <= got_unknown
    print(f"  {'✅' if ok2 else '🔴'} 缺字段 → 对应条件记 UNKNOWN     受影响 {len(affected)} 条"
          f"（在轨道内 {len(in_scope)}），其中 UNKNOWN {len(in_scope & got_unknown)} 条")
    if not ok2:
        bad += 1

    # 画像为空 → 每条都判不了（UNKNOWN），**没有一条 FAIL** 时，
    # 整体 verdict 必须是 UNKNOWN（不许硬给 ELIGIBLE），且必须告诉用户缺什么。
    # ⚠️ 用**全部条件 + 空画像**（F4 改法，wb 2026-10-13）：原按 `_06`/`_07` 后缀选
    #    子集，重编号后静默选错对象；按语义选就该选"最强形态"——什么都不填。
    r3 = check_eligibility({}, conds, policy_meta=doc)
    ok3 = r3["verdict"] == "UNKNOWN" and r3["missing_fields"]
    print(f"  {'✅' if ok3 else '🔴'} 空画像全 UNKNOWN → verdict=UNKNOWN   verdict={r3['verdict']} "
          f"缺={r3['missing_fields']}")
    if not ok3:
        bad += 1

    # ── 九格真值表 ⑨（SPEC §3.5c，NF-1 补断言，wb 2026-10-19）────────────
    # 缺分界字段（first_insurance_date）→ 轨道判不了 → 必须是 UNKNOWN + 追问分界字段，
    # 不许判 FAIL。引擎的实现（捕 CohortError 转 UNKNOWN，L207-211）在这之前**只有实现
    # 没有断言** —— 九格表标 ✅ 标错了，这就是没测的那格。
    # ⚠️ 按**语义**选轨道条件（applies_to_cohort 不是"全体"），不按 cond_id 后缀（F4 同源）。
    #    ⚠️ 二次踩坑更正（本轮自测抓的）：不能再用 `field != "first_insurance_date"`
    #    过滤——golden 里两条轨道条件的 field **就是**分界字段（它们本身就是
    #    "以首次社保时点分轨"这条规则），那样过滤会把轨道条件全排掉，
    #    CohortError 永远不触发，断言测了个空集。
    track_conds = [c for c in conds if "全体" not in c.applies_to_cohort]
    assert track_conds, "golden 里必须有轨道条件，否则⑨格测不了（golden 结构变了？）"
    r9 = check_eligibility({}, track_conds, policy_meta=doc)
    r9_ids = {x["cond_id"] for x in r9["reasons"]}
    got9 = {x["cond_id"] for x in r9["reasons"] if x["status"] == UNKNOWN}
    ok9 = (r9["verdict"] == "UNKNOWN" and r9_ids and r9_ids <= got9
           and "first_insurance_date" in r9["missing_fields"])
    print(f"  {'✅' if ok9 else '🔴'} ⑨缺分界字段 → 轨道条件 UNKNOWN+追问分界字段  "
          f"verdict={r9['verdict']} 分界字段在missing={'first_insurance_date' in r9['missing_fields']}")
    if not ok9:
        bad += 1

    # ── 九格真值表 ⑧（SPEC §3.5c，NF-1 补断言，wb 2026-10-19）────────────
    # cohort 不适用 → N/A，且 **N/A 不许进 verdict**（N/A 不是失败：
    # 老轨道的人看新政策条件被判"不符合"是把不适用当 FAIL 的典型后果）。
    # 同样在此之前只有实现没有断言。
    old_only = [c for c in conds if "老政策通道" in c.applies_to_cohort]
    assert old_only, "golden 里必须有老轨道条件，否则⑧格测不了（golden 结构变了？）"
    new_profile = {"first_insurance_date": "2023-01-01"}  # 新轨道画像
    r8 = check_eligibility(new_profile, old_only, policy_meta=doc, as_of_year=2026)
    na_cnt = sum(1 for x in r8["reasons"] if x["status"] == NOT_APPLICABLE)
    ok8 = (len(r8["reasons"]) == len(old_only) and na_cnt == len(old_only)
           and r8["verdict"] == VERDICT_UNKNOWN)
    print(f"  {'✅' if ok8 else '🔴'} ⑧cohort不适用 → 全部 N/A 记 UNKNOWN  "
          f"N/A={na_cnt}/{len(old_only)} verdict={r8['verdict']}")
    if not ok8:
        bad += 1

    # ── exempt_when（豁免）：50 岁博士必须 PASS，50 岁本科必须 FAIL ──────
    # 为什么这条必须测：豁免写错**不会报错，只会静默失效** ——
    # 50 岁的博士又会被判 FAIL，而输出看起来完全正常。
    base = {"education_type": "全日制", "grad_year": 2024, "first_insurance_date": "2023-01-01",
            "housing_owned_in_wuhan": False, "social_insurance_active": True,
            "qualification_valid": True, "age": 50}
    # ⚠️ 按**语义**选（有 exempt_when 且 field=="age"），不按 cond_id 后缀（F4，wb 2026-10-13）：
    #    `_01` 重编号后按后缀选会静默选错条件（F1 同源），按语义选重编号不会失效。
    c01 = next(c for c in conds if c.exempt_when is not None and c.field == "age")
    for edu, want in (("博士", "PASS"), ("本科", "FAIL")):
        rr = check_eligibility({**base, "education": edu}, [c01], policy_meta=doc, as_of_year=2026)
        got = rr["reasons"][0]["status"]
        oke = got == want
        if not oke:
            bad += 1
        mark = "✅" if oke else "🔴"
        print(f"  {mark} exempt_when：50 岁{edu} → {want}              实际={got}")

    # 豁免必须**说清理由**，不能只给结论（否则用户看到"年龄 PASS"会以为算错了）
    rr = check_eligibility({**base, "education": "博士"}, [c01], policy_meta=doc, as_of_year=2026)
    oke = rr["reasons"][0].get("exempted") is True and rr["reasons"][0].get("exempted_by")
    print(f"  {'✅' if oke else '🔴'} 豁免理由被记录                      "
          f"exempted_by={rr['reasons'][0].get('exempted_by')}")
    if not oke:
        bad += 1

    # ⚠️ 豁免**没起作用**时不许标"因豁免"（2026-10-13 修正，wb 指出）
    #
    # 23 岁的硕士：`_01`（年龄不满 45 周岁）**正常就 PASS**，豁免什么都没做。
    # 原实现在这里也标"因豁免而满足" —— 后果是
    #   **豁免机制到底有没有生效，永远测不出来**：不管触发没触发，输出都是同一句话。
    # 这是"永远不报警的检查 == 没检查"的变体。
    #
    # 为什么这条断言必须自己存在：这个 bug 的诊断信息就是 CLI 那一行输出，
    # 没有人会去怀疑"多标了一句豁免" —— 它看起来像是在**多给**用户信息。
    rr = check_eligibility({**base, "age": 23, "education": "硕士"}, [c01],
                           policy_meta=doc, as_of_year=2026)
    oke = rr["reasons"][0]["status"] == PASS and "exempted" not in rr["reasons"][0]
    print(f"  {'✅' if oke else '🔴'} 豁免未起作用时**不标**豁免          "
          f"status={rr['reasons'][0]['status']} exempted={rr['reasons'][0].get('exempted')}")
    if not oke:
        bad += 1

    # ── F2（wb 2026-10-13）：缺**豁免字段** + 正常 FAIL → UNKNOWN ─────────
    # 50 岁但没填学历：博士则豁免命中→PASS，本科则不命中→FAIL，
    # 真相是"不知道他是哪种"。原实现 fall-through 成 FAIL → 整体 INELIGIBLE，
    # 用户被告知"不符合"，而他只是没填一项信息 —— 违背「UNKNOWN 不是 INELIGIBLE」。
    # 修后必须 UNKNOWN，且追问的正是豁免字段（education）。
    no_edu = {k: v for k, v in {**base, "education": "本科"}.items() if k != "education"}
    rr = check_eligibility(no_edu, [c01], policy_meta=doc, as_of_year=2026)
    oke = rr["reasons"][0]["status"] == UNKNOWN and "education" in rr["missing_fields"]
    print(f"  {'✅' if oke else '🔴'} 缺豁免字段+正常FAIL → UNKNOWN+追问豁免字段 "
          f"status={rr['reasons'][0]['status']} missing={rr['missing_fields']}")
    if not oke:
        bad += 1

    # ── exempt_when 与 ambiguity 互斥（wb 疑点 B，所有者已批）──────────
    # 两者表达同一件事时是冗余 → 改一个忘改另一个 = 静默失效。
    # 实测来源：`_01` 原来的 ambiguity 就是"研究生不受年龄限制"。
    def _both():
        Condition(cond_id="t_x", doc_id="d", applies_to_cohort="全体", cond_type="资格",
                  field="age", op="<", value=45, source_text="年龄不满45周岁（研究生不受年龄限制）",
                  exempt_when={"field": "education", "op": "in", "value": ["硕士", "博士"]},
                  ambiguity="研究生不受年龄限制")
    try:
        _both()
        got_b = False
    except ConditionError:
        got_b = True
    print(f"  {'✅' if got_b else '🔴'} exempt_when+ambiguity 并存必须报错   实际={'报错' if got_b else '通过'}")
    if not got_b:
        bad += 1

    # ── status_detail：计算类的 UNKNOWN 必须说清是"缺字段"还是"引擎算不了" ──
    # ⚠️ 必须**新跑一次**取结果 —— 上面那个 `r` 是"已废止"的调用，reasons 本来就是空的
    r_calc = check_eligibility(profile, conds, policy_meta=doc)
    cr = next((x for x in r_calc["reasons"] if x.get("is_calc")), None)
    # 缺输入字段 → 走 missing_fields（用户能补），**不是** status_detail（引擎短板）
    okd = cr is not None and "market_rent" in r_calc["missing_fields"]
    print(f"  {'✅' if okd else '🔴'} 计算类缺输入 → 进 missing_fields（用户能补）   "
          f"missing={r_calc['missing_fields']}")
    if not okd:
        bad += 1

    # ── 补上 market_rent 后：计算类必须变 PASS 且 amount 有值 ──────────
    # 这是"status_detail 区分两种 UNKNOWN"的**正面证明**：
    # 数据层问题（缺 market_rent）补上数据就该能判，不该还卡在 UNKNOWN。
    r_full = check_eligibility({**profile, "market_rent": 3000.0}, conds, policy_meta=doc)
    cr2 = next((x for x in r_full["reasons"] if x.get("is_calc")), None)
    okf = (cr2 is not None and cr2["status"] == PASS
           and r_full["amount"] and r_full["amount"]["value"] > 0)
    print(f"  {'✅' if okf else '🔴'} 补上 market_rent → 计算类 PASS + amount   "
          f"status={cr2['status'] if cr2 else '?'} "
          f"amount={r_full['amount']['value'] if r_full['amount'] else None}")
    if not okf:
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
