"""以固定基准年复现画像用例的资格判定准确率。"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.conditions.loader import load_conditions
from src.engine.eligibility import check_eligibility
VERDICTS = ("ELIGIBLE", "INELIGIBLE", "UNKNOWN")
DEFAULT_YEAR = 2026
def read_jsonl(path: Path) -> list[dict]:
    """读取 UTF-8 JSONL，并拒绝缺失、空文件及非法行。"""
    if not path.is_file():
        raise ValueError(f"文件不存在：{path}")
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no} JSON 无效：{exc}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_no} 必须是 JSON 对象")
                rows.append(row)
    if not rows:
        raise ValueError(f"文件无数据：{path}")
    return rows
def validate_cases(cases: list[dict], policy_ids: set[str], minimum: int = 50) -> None:
    """检查用例结构、标签、唯一性及政策引用。"""
    if not cases:
        raise ValueError("cases 为空，拒绝评测")
    if len(cases) < minimum:
        raise ValueError(f"用例只有 {len(cases)} 条，至少需要 {minimum} 条")
    seen = set()
    for case in cases:
        required = ("case_id", "policy_id", "profile", "expected_verdict",
                    "expected_missing", "derivation", "source")
        absent = [key for key in required if key not in case]
        if absent:
            raise ValueError(f"用例缺少字段：{absent}")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id 必须是非空字符串")
        if case_id in seen:
            raise ValueError(f"case_id 重复：{case_id}")
        seen.add(case_id)
        if case["policy_id"] not in policy_ids:
            raise ValueError(f"未知 policy_id：{case['policy_id']} ({case_id})")
        if case["expected_verdict"] not in VERDICTS:
            raise ValueError(f"非法 expected_verdict：{case['expected_verdict']} ({case_id})")
        if not isinstance(case["profile"], dict):
            raise ValueError(f"profile 必须是对象：{case_id}")
        missing = case["expected_missing"]
        if not isinstance(missing, list) or any(not isinstance(x, str) for x in missing):
            raise ValueError(f"expected_missing 必须是字符串数组：{case_id}")
        if case["expected_verdict"] != "UNKNOWN" and missing:
            raise ValueError(f"非 UNKNOWN 用例的 expected_missing 必须为空：{case_id}")
        if not isinstance(case["derivation"], str) or not case["derivation"].strip():
            raise ValueError(f"derivation 不能为空：{case_id}")
        if case["source"] != "constructed":
            raise ValueError(f"source 必须是 constructed：{case_id}")
    if minimum == 50 and [c["case_id"] for c in cases] != [f"E{i:02d}" for i in range(1, 51)]:
        raise ValueError("case_id 必须按 E01–E50 连续排列")
def score_cases(cases: list[dict], policies: dict, grouped: dict,
                as_of_year: int) -> dict:
    """调用规则引擎，并分别统计准确率、混淆矩阵和诊断差异。"""
    matrix = {want: {got: 0 for got in VERDICTS} for want in VERDICTS}
    totals, correct = Counter(), Counter()
    failures, missing_mismatches, records = [], [], []
    for case in cases:
        policy_id = case["policy_id"]
        conditions = grouped.get(policy_id, [])
        if not conditions:
            raise ValueError(f"政策没有 golden 条件：{policy_id}")
        result = check_eligibility(case["profile"], conditions, policy_meta=policies[policy_id],
                                   as_of_year=as_of_year)
        got, expected = result["verdict"], case["expected_verdict"]
        if got not in VERDICTS:
            raise ValueError(f"引擎返回未知 verdict：{got!r} ({case['case_id']})")
        totals[expected] += 1
        matrix[expected][got] += 1
        if got == expected:
            correct[expected] += 1
        else:
            failures.append((case, result))
        actual_missing = sorted(result.get("missing_fields", []))
        expected_missing = sorted(case["expected_missing"])
        if actual_missing != expected_missing:
            missing_mismatches.append((case, expected_missing, actual_missing))
        records.append({"case_id": case["case_id"], "expected": expected, "got": got})
    return {"matrix": matrix, "totals": totals, "correct": correct,
            "failures": failures, "missing_mismatches": missing_mismatches,
            "records": records, "total": len(cases)}
def print_results(cases: list[dict], skipped: dict, report: dict,
                  as_of_year: int, include_incomplete: bool) -> None:
    """输出分层准确率、混淆矩阵、失败和覆盖信息。"""
    print(f"as_of_year: {as_of_year}")
    if include_incomplete:
        print("⚠️ --include-incomplete 已启用，结果仅用于诊断")
    total_correct = sum(report["correct"].values())
    print(f"总准确率: {total_correct}/{report['total']} = {total_correct / report['total']:.1%}")
    print("按 expected 类别准确率（正确数 / 该类样本数）：")
    for verdict in VERDICTS:
        count = report["totals"][verdict]
        good = report["correct"][verdict]
        rate = f"{good / count:.1%}" if count else "N/A"
        print(f"  {verdict}: {good}/{count} = {rate}")
    print("混淆矩阵（行=expected，列=got）：")
    print("  expected\\got " + " ".join(f"{v:>12}" for v in VERDICTS))
    for want in VERDICTS:
        print(f"  {want:>13} " + " ".join(f"{report['matrix'][want][got]:>12}" for got in VERDICTS))
    print("失败清单：")
    if not report["failures"]:
        print("  （无）")
    for case, result in report["failures"]:
        summary = case["derivation"].split("汇总：")[-1][:100]
        print(f"  {case['case_id']} expected={case['expected_verdict']} got={result['verdict']} "
              f"missing={result.get('missing_fields', [])} derivation={summary}")
    print("expected_missing 与引擎 missing_fields 差异：")
    if not report["missing_mismatches"]:
        print("  （无）")
    for case, expected, actual in report["missing_mismatches"]:
        print(f"  {case['case_id']} expected_missing={expected} engine_missing_fields={actual}")
    print(f"覆盖信息：输入用例数={len(cases)}，参与用例数={report['total']}，"
          f"参与政策数={len({c['policy_id'] for c in cases if c['policy_id'] not in skipped})}")
    print(f"跳过政策：{', '.join(sorted(skipped)) if skipped else '无'}")
def reject_test(label: str, cases: list[dict], policy_ids: set[str]) -> None:
    """确认结构错误会被验证器明确拒绝。"""
    try:
        validate_cases(cases, policy_ids, minimum=0)
    except ValueError as exc:
        print(f"[自检] {label}：正确拒绝（{exc}）")
        return
    raise ValueError(f"自检失败：{label} 未被拒绝")
def run_selftest(cases: list[dict], policies: dict, grouped: dict,
                 as_of_year: int, selected: list[dict]) -> None:
    """注入空数据、非法标签、重复 ID 和翻转标签验证检查器。"""
    policy_ids = set(policies)
    reject_test("空 cases", [], policy_ids)
    bad = [dict(cases[0], expected_verdict="MAYBE")]
    reject_test("非法 expected 值", bad, policy_ids)
    duplicate = [dict(cases[0]), dict(cases[1])]
    duplicate[1]["case_id"] = duplicate[0]["case_id"]
    reject_test("重复 case_id", duplicate, policy_ids)
    baseline = score_cases(selected, policies, grouped, as_of_year)
    right = next((r for r in baseline["records"] if r["expected"] == r["got"]), None)
    if right is None:
        raise ValueError("自检无法找到可翻转的正确用例")
    changed = [dict(c) for c in selected]
    target = next(c for c in changed if c["case_id"] == right["case_id"])
    original = target["expected_verdict"]
    target["expected_verdict"] = next(v for v in VERDICTS if v != original)
    injected = score_cases(changed, policies, grouped, as_of_year)
    listed = any(c["case_id"] == right["case_id"] for c, _ in injected["failures"])
    if injected["correct"].values() and sum(injected["correct"].values()) != sum(baseline["correct"].values()) - 1:
        raise ValueError("自检失败：翻转标签未使准确数恰好下降 1")
    if not listed:
        raise ValueError("自检失败：被翻转用例未进入失败清单")
    print(f"[故障注入] {right['case_id']} expected {original}→{target['expected_verdict']}；"
          f"准确数 {sum(baseline['correct'].values())}/{baseline['total']}→"
          f"{sum(injected['correct'].values())}/{injected['total']}；失败清单已包含该用例")
    print("[自检] 全部故障注入通过")
def main() -> int:
    """读取输入、执行评测或自检，并将结构错误映射为退出码 1。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--include-incomplete", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    try:
        policies_rows = read_jsonl(ROOT / "data/processed/policies.jsonl")
        cases = read_jsonl(ROOT / "eval/eval_cases.jsonl")
        pending = read_jsonl(ROOT / "eval/v4_pending.jsonl")
        conditions = load_conditions(ROOT / "eval/golden_conditions.jsonl")
        policies = {row["doc_id"]: row for row in policies_rows if row.get("doc_id")}
        if len(policies) != len(policies_rows):
            raise ValueError("policies.jsonl 中 doc_id 缺失或重复")
        pending_ids = {row["doc_id"] for row in pending if row.get("doc_id")}
        validate_cases(cases, set(policies))
        grouped = {}
        for condition in conditions:
            grouped.setdefault(condition.doc_id, []).append(condition)
        skipped = {} if args.include_incomplete else {c["policy_id"] for c in cases if c["policy_id"] in pending_ids}
        selected = [c for c in cases if args.include_incomplete or c["policy_id"] not in pending_ids]
        if not selected:
            raise ValueError("覆盖完整政策没有可评测用例")
        report = score_cases(selected, policies, grouped, args.as_of_year)
        print_results(cases, skipped, report, args.as_of_year, args.include_incomplete)
        if args.selftest:
            run_selftest(cases, policies, grouped, args.as_of_year, selected)
        return 0
    except (OSError, ValueError) as exc:
        print(f"结构错误：{exc}", file=sys.stderr)
        return 1
if __name__ == "__main__":
    raise SystemExit(main())
