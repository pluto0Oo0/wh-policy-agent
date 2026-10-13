"""命令行入口 —— 纵切的最后一步（SPEC §5 / §6 第 10 项）。

用法：
    python -m src.cli ask --profile data/profile.json [--policy <doc_id>]

════════════════════════════════════════════════════════════════
本模块只做三件事，其余一概不做
════════════════════════════════════════════════════════════════
1. **读输入**（画像 + 政策 + 条件）
2. **调引擎**（`check_eligibility`，纯代码）
3. **排版输出**（人话）

**它不做判定、不做计算、不碰网络。** 判定逻辑全在 `src/engine/`。
为什么要把这条写死：CLI 是最容易变成"顺手加业务逻辑"的地方，
而一旦判定逻辑跑进 CLI，`engine/` 就不再是唯一可测的判定入口了。

════════════════════════════════════════════════════════════════
输出设计的三条原则
════════════════════════════════════════════════════════════════
**① 不确定的事必须说出来。**
    `policy_status=未核实` 要显式警告（SPEC §3.5b），不许静默给结论。

**② 追问要给"用户答得出来的问题"。**
    用条件里的 `ask` 字段（标注时人工填），**不是把政策术语原样抛回去**。
    「什么算正常缴纳？」是让用户答政策定义；「你有没有断缴记录？」才是他答得出的。

**③ 「不适用」和「不符合」要分开显示。**
    `N/A` 的条件**不能**混在"你不满足"里 —— 那是"你该走另一条轨道"。
"""

import argparse
import json
import sys
from pathlib import Path

from src.conditions.loader import load_conditions
from src.conditions.model import Condition
from src.engine.eligibility import (
    FAIL,
    NOT_APPLICABLE,
    PASS,
    UNKNOWN,
    VERDICT_ELIGIBLE,
    VERDICT_INELIGIBLE,
    VERDICT_UNKNOWN,
    check_eligibility,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 每条 reason 的显示符号。为什么用符号不用文字：
#   一眼扫出"哪几条是问题"，比读 11 行"PASS/FAIL"快得多。
STATUS_MARK = {
    PASS: "✅",
    FAIL: "❌",
    UNKNOWN: "❓",
    NOT_APPLICABLE: "➖",
}

STATUS_LABEL = {
    PASS: "符合",
    FAIL: "不符合",
    UNKNOWN: "判不了",
    NOT_APPLICABLE: "不适用",
}

# 画像字段名 → 人话。
# 为什么需要：输出「请补充：market_rent」是**把内部字段名抛给用户**，
# 他既不知道那是什么、也不知道该填什么格式。
# ⚠️ 与 `data/profile.json` 的字段一一对应，加字段必须同步加这里。
FIELD_LABELS = {
    "age": "年龄（周岁）",
    "education": "学历（大专/本科/硕士/博士）",
    "education_type": "学习形式（全日制/非全日制）",
    "grad_year": "毕业年份",
    "grad_years": "毕业年数",
    "hukou_wuhan": "是否武汉户籍",
    "first_insurance_date": "首次缴纳社保的日期（决定走新政策还是老政策）",
    "employed": "是否在汉就业创业",
    "housing_owned_in_wuhan": "家庭在武汉是否已有自有住房",
    "social_insurance_active": "社保是否在正常缴纳",
    "marital_status": "婚姻状况（未婚/已婚）",
    "market_rent": "你租的房子月租金（元）",
    "qualification_valid": "你的安居资格是否还在有效期内",
    "region": "所在区",
}


def _load_json(path: Path) -> dict:
    """读一个 JSON 文件，读不到/格式坏都抛错，**不静默返回空 dict**。

    为什么不能返回空 dict：空画像会让引擎判出一堆 UNKNOWN，
    而用户看到的是"你什么都没填"——**真正的原因（文件没找到）被掩盖了。**
    """
    if not path.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} 不是合法 JSON：{e.msg}（第 {e.lineno} 行）") from e


def _find_policy(docs: list[dict], doc_id: str | None) -> dict:
    """从 policies.jsonl 里挑一条政策。给了 doc_id 就精确找，没给就取第一条。"""
    if not docs:
        raise ValueError("policies.jsonl 是空的，先跑爬取（纵切第 1 步）")
    if doc_id is None:
        if len(docs) > 1:
            print(f"⚠️  库里有 {len(docs)} 条政策，未指定 --policy，取第一条"
                  f"（{docs[0]['doc_id']}）\n")
        return docs[0]
    hit = next((d for d in docs if d["doc_id"] == doc_id), None)
    if hit is None:
        raise ValueError(f"库里没有 doc_id={doc_id!r}，现有："
                         f"{[d['doc_id'] for d in docs]}")
    return hit


def _print_result(result: dict, conditions: list[Condition]) -> None:  # noqa: F821
    """把人话结果打到终端。"""
    by_id = {c.cond_id: c for c in conditions}

    print("=" * 66)
    print(f"  {result['policy_title']}")
    print(f"  文号：{result['doc_number'] or '(无)'}    政策状态：{result['policy_status']}")
    print("=" * 66)

    # ── ① 政策有效性警告（SPEC §3.5b：非"现行"必须显式说）────────
    if result["status_warning"]:
        print(f"\n⚠️  {result['status_warning']}")

    # ── ② 结论 ─────────────────────────────────────────────────
    verdict_text = {
        VERDICT_ELIGIBLE: "✅ 符合条件",
        VERDICT_INELIGIBLE: "❌ 不符合条件",
        VERDICT_UNKNOWN: "❓ 信息不足，暂时判不了",
    }[result["verdict"]]
    print(f"\n【结论】{verdict_text}")

    # ── ③ 逐条依据（SPEC §2.4：每条带 source_text）──────────────
    print("\n【逐条依据】")
    for r in result["reasons"]:
        mark = STATUS_MARK.get(r["status"], "?")
        label = STATUS_LABEL.get(r["status"], r["status"])
        src = r["source_text"]
        src = src if len(src) <= 40 else src[:40] + "…"
        extra = ""
        if r.get("exempted"):
            # 豁免必须说明理由，否则用户看到"年龄不满45周岁 ✅"会以为算错了
            extra = "  ← 因豁免而满足"
        print(f"  {mark} [{label}] {src}{extra}")

    # ── ④ 金额 ─────────────────────────────────────────────────
    amount = result.get("amount")
    if amount and amount.get("value") is not None:
        print(f"\n【能省多少】约 {amount['value']:,.0f} 元（{amount['type']}）")
        print(f"  {amount['detail']}")
    elif amount and amount.get("type") == "unknown":
        print(f"\n【能省多少】算不了 —— {amount['detail']}")

    # ── ⑤ 追问（用条件里的 ask 话术，不是把政策术语抛回去）──────
    if result["missing_fields"] or result["verdict"] == VERDICT_UNKNOWN:
        print("\n【还需要你告诉我】")
        covered = set()

        # ① 先给"用户答得出来的问题" —— 条件里人工填的 `ask` 话术
        for r in result["reasons"]:
            if r["status"] != UNKNOWN:
                continue
            cond = by_id.get(r["cond_id"])
            if cond is not None and cond.ask:
                print(f"  · {cond.ask}")
                covered.add(cond.field)

        # ② 再补剩下的缺失字段。
        #    ⚠️ 用 `missing_fields`（引擎给的权威清单），**不用 cond.field** ——
        #    计算类条件的 `field` 是**输出字段**（如 `rent`），
        #    缺的输入字段（`market_rent`）只在 missing_fields 里。
        #    2026-10-13 实测踩过：用 cond.field 会输出「请补充：rent」，
        #    用户根本不知道那是什么。
        for f in result["missing_fields"]:
            if f in covered:
                continue
            print(f"  · 请补充：{FIELD_LABELS.get(f, f)}")

        # ③ 引擎层的问题（用户补字段没用）→ 明说，别让他白填
        for r in result["reasons"]:
            if r["status"] == UNKNOWN and r.get("status_detail"):
                print(f"  · （这条不是你能补的）{r['status_detail']}")

    # ── ⑥ 去哪办 ───────────────────────────────────────────────
    wta = result.get("where_to_apply")
    if wta:
        print(f"\n【去哪办】{wta.get('office', '')} {wta.get('phone', '')}".rstrip())
        if wta.get("source_date"):
            print(f"  （联系方式来源：{wta['source_date']} 年发文，窗口可能已调整）")
    else:
        print("\n【去哪办】该政策原文没有受理部门/联系方式，暂无法指路。")


def _cmd_ask(args: argparse.Namespace) -> int:
    """`ask` 子命令：读画像 → 判定 → 打印结果。"""
    profile = _load_json(Path(args.profile))

    policies_path = PROJECT_ROOT / "data" / "processed" / "policies.jsonl"
    if not policies_path.exists():
        print(f"❌ 找不到 {policies_path}，先跑纵切第 1 步（爬取）", file=sys.stderr)
        return 2
    docs = [json.loads(ln) for ln in
            policies_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    policy = _find_policy(docs, args.policy)

    conditions = load_conditions(PROJECT_ROOT / "eval" / "golden_conditions.jsonl")
    # 只取属于这条政策的条件（将来库里多条政策时要过滤）
    conditions = [c for c in conditions if c.doc_id == policy["doc_id"]]
    if not conditions:
        print(f"❌ 没有属于 {policy['doc_id']} 的条件", file=sys.stderr)
        return 2

    result = check_eligibility(profile, conditions, policy_meta=policy)
    _print_result(result, conditions)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="武汉大学生政策条件判定助手（Phase 1 · 纯代码规则引擎）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ask = sub.add_parser("ask", help="输入画像，输出能享受哪些政策")
    p_ask.add_argument("--profile", required=True, help="画像 JSON 路径（SPEC §2.3）")
    p_ask.add_argument("--policy", default=None, help="指定 doc_id；不给则取第一条")
    p_ask.set_defaults(func=_cmd_ask)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as e:
        # 可预期的错误：给人话，退出码非 0（**不静默成功**）
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
