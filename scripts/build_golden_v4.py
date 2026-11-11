"""golden v4 构建：v3（14 条）+ T04 独立条（28 条）。

输入：
    eval/v3_draft/golden_conditions_v3.jsonl   v3 冻结快照（14 条）
    eval/t04_draft/conditions-DRAFT.jsonl      Codex T04 草案（89 条）
    eval/t04_draft/*.txt                       19 份原文快照
输出：
    eval/golden_conditions.jsonl               v4（42 条）
    eval/v4_lineage.jsonl                      derived 14 条，只记归属
    eval/v4_pending.jsonl                      47 条待拍板/待公式

三分规则（2026-11-11 与进度存档一致）：
    derived_from 非空       → lineage，不进 conditions
    可判定的独立条（28 条）  → 转 Condition，进 v4
    其余                    → pending，写明原因，不静默丢弃

为什么 pending 也要落盘：
    漏掉一条条件 = 该政策对某人误判 ELIGIBLE，而且输出看起来正常。
    所以每条草案都必须落在且只落在一个桶里，脚本末尾对 89 条做分区断言。
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
DRAFT_DIR = EVAL / "t04_draft"
V3_PATH = EVAL / "v3_draft" / "golden_conditions_v3.jsonl"
GOLDEN_PATH = EVAL / "golden_conditions.jsonl"

# ── 决策表（数据，不是代码）：eval/v4_decisions.json ──────────
# 26 条并入项 + 1 条原文覆盖 + 3 条特殊挂起，逐条写在 JSON 里，
# 所有者可以直接逐条核对：cohort 依据、映射到哪个字段、为什么挂起。
DECISIONS_PATH = EVAL / "v4_decisions.json"
_D = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
ADD = _D["add"]
SOURCE_OVERRIDE = _D["source_override"]
PENDING_SPECIAL = _D["pending_special"]


def load_jsonl(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def dump_jsonl(path, rows):
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    path.write_text(text, encoding="utf-8")


def norm(s):
    """比对原文时去掉空白与句号编号（S08/Q203）。

    区级页面把长句按内联节点拆行，v3 快照又在句间插了 Sxx 编号；
    两者都不是原文内容，比对时必须忽略。
    """
    return re.sub(r"[QS]\d+|\s+", "", s or "")


def snapshot_map():
    """doc_id → 去掉 'Qxx<TAB>' 后整篇拼接的正文。"""
    out = {}
    for p in DRAFT_DIR.glob("t*.txt"):
        lines = p.read_text(encoding="utf-8").splitlines()
        out[p.stem] = norm("".join(re.sub(r"^Q\d+\t", "", ln) for ln in lines))
    return out


def main() -> int:
    v3 = load_jsonl(V3_PATH)
    drafts = load_jsonl(DRAFT_DIR / "conditions-DRAFT.jsonl")
    snaps = snapshot_map()

    # 决策表自身也要校验：写错/过期的 draft_id 不能静默失效。
    draft_ids = {r["draft_id"] for r in drafts}
    unknown = (set(ADD) | set(PENDING_SPECIAL) | set(SOURCE_OVERRIDE)) - draft_ids
    if unknown:
        raise SystemExit(f"🔴 决策表引用了不存在的 draft_id：{sorted(unknown)}")
    if set(ADD) & set(PENDING_SPECIAL):
        raise SystemExit(f"🔴 同一条既并入又挂起：{sorted(set(ADD) & set(PENDING_SPECIAL))}")

    golden = list(v3)
    lineage, pending, added = [], [], []
    seq_by_doc: dict[str, int] = {}

    for r in drafts:
        did = r["draft_id"]
        if r.get("derived_from"):
            lineage.append({
                "draft_id": did, "doc_id": r["doc_id"],
                "derived_from": r["derived_from"],
                "quote": r["quote"], "paraphrase": r["paraphrase"],
            })
            continue
        if did in ADD:
            entry = ADD[did]
            cohort, note = entry["cohort"], entry["note"]
            override = {k: v for k, v in entry.items() if k not in ("cohort", "note")}
            seq = seq_by_doc[r["doc_id"]] = seq_by_doc.get(r["doc_id"], 0) + 1
            golden.append({
                "cond_id": f"{r['doc_id']}_{seq:02d}",
                "doc_id": r["doc_id"],
                "applies_to_cohort": cohort,
                "cond_type": r["cond_type_suggest"],
                "field": override.get("field", r["field_suggest"]),
                "op": override["op"] if "op" in override else r["op_suggest"],
                "value": override["value"] if "value" in override else r["value_suggest"],
                "formula": None,
                "source_text": override.get("source_text")
                or SOURCE_OVERRIDE.get(did)
                or r["quote"],
                "verified_by": "",
                "verified_at": "",
                "verify_note": f"T04草案转写(CC 2026-11-11)：{note}；待所有者核对",
                "phase": 1,
                "era": "new",
            })
            added.append(did)
            continue
        # 其余全部进 pending，且必须给出原因
        if did in PENDING_SPECIAL:
            reason = PENDING_SPECIAL[did]
        elif not r.get("field_suggest"):
            reason = "需新增画像字段（待所有者拍板）"
        elif r["cond_type_suggest"] == "计算":
            reason = "计算类公式待 formula DSL（SPEC 契约缺口，calc.py 只认六重叠加）"
        elif r["op_suggest"] == "<=" and r["field_suggest"] == "qualification_valid":
            reason = "权益条款（优惠/延长期限），不是画像可判定的资格条件"
        elif r["field_suggest"] == "qualification_valid":
            reason = "退出/失效条款，不是申请时的资格条件"
        else:
            raise SystemExit(f"🔴 未分类草案：{did}（必须显式写明去向）")
        pending.append({
            "draft_id": did, "doc_id": r["doc_id"],
            "cond_type": r["cond_type_suggest"],
            "field_suggest": r["field_suggest"],
            "quote": r["quote"], "reason": reason,
        })

    # ── 分区断言：89 条必须 = 14 + 28 + 47 ─────────────────────
    total = len(lineage) + len(added) + len(pending)
    if total != len(drafts):
        raise SystemExit(f"🔴 分区丢条：{len(drafts)} 条草案只落了 {total} 条")
    if (len(lineage), len(added)) != (14, 28):
        raise SystemExit(f"🔴 分区数不符：derived={len(lineage)} added={len(added)}")
    ids = [c["cond_id"] for c in golden]
    if len(ids) != len(set(ids)):
        raise SystemExit("🔴 cond_id 重复")

    # ── 引文逐字核对：拼接整篇后 source_text 必须是子串 ──────────
    bad = []
    for c in golden:
        text = snaps.get(c["doc_id"], "")
        if not text:
            text = norm((EVAL / "v3_draft" / "source_snapshot.txt").read_text(encoding="utf-8"))
        if norm(c["source_text"]) not in text:
            bad.append(c["cond_id"])
    if bad:
        raise SystemExit(f"🔴 引文不在原文快照中：{bad}")

    # ── doc_id 必须在正式库 ────────────────────────────────────
    corpus = {r["doc_id"] for r in load_jsonl(ROOT / "data" / "processed" / "policies.jsonl")}
    missing = sorted({c["doc_id"] for c in golden} - corpus)
    if missing:
        raise SystemExit(f"🔴 doc_id 不在 policies.jsonl：{missing}")

    dump_jsonl(GOLDEN_PATH, golden)
    dump_jsonl(EVAL / "v4_lineage.jsonl", lineage)
    dump_jsonl(EVAL / "v4_pending.jsonl", pending)

    print(f"v4 = v3 {len(v3)} + T04 {len(added)} = {len(golden)} 条，{len({c['doc_id'] for c in golden})} 个政策")
    print(f"derived 归属 {len(lineage)} 条；pending {len(pending)} 条")
    print(f"引文核对 {len(golden)}/{len(golden)} 通过；doc_id 全部在正式库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
