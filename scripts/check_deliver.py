"""交付前自检 —— 跑所有可枚举的检查项，退出码非 0 即未通过。

用法：
    python scripts/check_deliver.py            # 完整检查
    python scripts/check_deliver.py --init     # 首次初始化（生成 expected_samples 模板）

退出码：
    0 = 通过
    1 = 有检查项未通过（**此时不得宣布完成**）

════════════════════════════════════════════════════════════════
设计原则（来自实际踩坑，不是拍脑袋）
════════════════════════════════════════════════════════════════
1. **只在真正出问题时报错** —— 报警太多会被当噪音忽略
2. **每项失败打印「为什么这条重要」** —— 否则不知道为什么要修
3. **硬指标失败报 warn 不报 fail** —— 因为"0 命中"有两种原因
   （源不对 / 翻页不够），自动判错会误导
4. **检查项拆到 scripts/checks/** —— 单文件 ≤200 行（CLAUDE.md 第 2 条）

来源：wb 设计，CC 修订。见 _handoff/ 下的往来文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让 scripts/checks/ 里的模块能被 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import config as C  # noqa: E402
from checks import contract_checks as K  # noqa: E402
from checks import data_checks as D  # noqa: E402
from checks.expected_samples import check_expected_samples as _check_samples  # noqa: E402
from checks.module_tests import check_module_selftests  # noqa: E402

# 五个"可自动判定"的检查 + 两个"只警告"的检查
AUTO_CHECKS = [
    ("静默吞错", C.check_silent_except),
    ("显式编码", C.check_encoding),
    ("JSONL 完整性", D.check_jsonl),
    ("画像契约同步", K.check_profile_contract),
    ("模块自测（全仓）", check_module_selftests),
]
WARN_CHECKS = [
    ("SPEC 签名同步", D.check_spec_signatures),
    ("数据源有效性", D.check_source_usefulness),
]


def main() -> int:
    init = "--init" in sys.argv

    print("=" * 72)
    print("交付前自检")
    print("=" * 72)
    if init:
        print("（--init 模式：生成 expected_samples.json 模板）")
    print()

    # ── 自动判定的检查 ────────────────────────────────────
    for name, fn in AUTO_CHECKS:
        try:
            fn()
        except Exception as e:
            C.fail(f"[{name}] 检查本身崩了：{type(e).__name__}: {e}")
        print(f"  已跑 · {name}")

    # ── 真对比（单独跑，因为是唯一能证明"内容对了"的一环）──
    try:
        _check_samples(C.fail, init=init)
    except Exception as e:
        C.fail(f"[expected_samples] 检查本身崩了：{type(e).__name__}: {e}")
    print("  已跑 · expected_samples 真对比")

    # ── 只警告的检查 ──────────────────────────────────────
    for name, fn in WARN_CHECKS:
        try:
            fn()
        except Exception as e:
            C.fail(f"[{name}] 检查本身崩了：{type(e).__name__}: {e}")
        print(f"  已跑 · {name}")

    # ── 行数双口径（单独跑 + 显式声明口径，F3 教训：口径不声明 = 数字失真）──
    print("  已跑 · 行数（双口径：会话增量=硬红线 / 单文件总量=软预警）")
    try:
        C.check_file_length()
    except Exception as e:
        C.fail(f"[行数] 检查本身崩了：{type(e).__name__}: {e}")

    # ── 汇总 ──────────────────────────────────────────────
    print()
    # 🔴 口径声明（F3，wb 2026-10-13）：同一命令在提交前后报的数字不同，
    #    根子是"检查范围"没声明。这里显式写明每项查的是哪个口径。
    print("📋 检查范围口径：")
    print("   · 静默吞错 / 显式编码 —— 本轮 diff（提交后退化为全仓扫描）")
    print("   · JSONL 完整性 / expected_samples / 数据源 —— 全仓数据文件")
    print("   · 模块自测 —— 全仓 src/（python -m 逐个跑，非 0 即报）")
    print("   · 行数 —— 会话增量（硬）+ 单文件总量（软），两个口径分开报")
    print()
    if C.warnings:
        print(f"警告 {len(C.warnings)} 条（不阻断，但必须逐条看过）：")
        for w in C.warnings:
            print(f"  ⚠️  {w}")
        print()

    if C.problems:
        print(f"❌ 未通过，{len(C.problems)} 个问题：")
        for p in C.problems:
            print(f"  ❌ {p}")
        print()
        print("修完重跑。不处理等于把问题推到后面才发现。")
        return 1

    print("✅ 自动检查全部通过。")
    print()
    print("⚠️  但脚本只能查可枚举的问题。交付前还必须回答三个问题：")
    print("   1. 这批数据真的达到目的了吗？（去数，不要凭感觉）")
    print("   2. 若有检查失败，失败的真实原因是什么？（别被布尔判断骗了）")
    print("   3. 有没有脚本没报警但你觉得不对劲的地方？")
    print()
    print("   涉及代码改动 → /code-review    涉及阶段交付 → /reflect")
    return 0


if __name__ == "__main__":
    sys.exit(main())
