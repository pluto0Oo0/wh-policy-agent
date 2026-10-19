"""检查项（第三部分）—— 模块自测扫描。

F3（wb 2026-10-13）：check_deliver 原来只查格式类问题，
**从不跑任何模块自测** —— F1 那个红了的 cohort 验收就这样漏掉的。
修法：扫描 src/ 下全部可自测模块，逐个跑 `python -m <module>`，非 0 即报警。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import PROJECT_ROOT, fail, warn

# 无自测 harness 的模块（跑了也是无意义退出）：
# - __init__ / cli：cli 无参数时 argparse 退出码 2，属正常用法提示
# - 判断标准：模块 __main__ 是否真有验收断言，用「退出码 0/1 语义」约定，
#   没有自测 harness 的模块退出码恒 0，不会误报；有 harness 的红了必被抓住。
SKIP_MODULES = {"__init__", "cli"}


def _module_name(p: Path) -> str | None:
    """src/ 下的 py 文件 → 模块名（src.engine.cohort）。非模块/跳过项返回 None。"""
    if p.name != "__init__.py" and p.stem not in SKIP_MODULES:
        rel = p.relative_to(PROJECT_ROOT / "src")
        parts = list(rel.with_suffix("").parts)
        return "src." + ".".join(parts)
    return None


def check_module_selftests() -> None:
    """跑全部 src/ 模块的 `python -m` 自测，任一非 0 即 fail。

    ⚠️ 口径：**全仓**（不是本轮 diff）—— 模块自测本来就快（<10s），
    而提交后 diff 口径会漏检历史遗留（F3 教训），索性全跑。
    """
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    python = str(venv_python if venv_python.exists() else Path(sys.executable))

    mods = sorted(
        m for p in (PROJECT_ROOT / "src").rglob("*.py")
        if (m := _module_name(p)) is not None
    )
    if not mods:
        warn("[自测] src/ 下没找到任何可跑模块（结构变了？）")
        return

    for m in mods:
        try:
            r = subprocess.run(
                [python, "-m", m], cwd=PROJECT_ROOT,
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            fail(f"[自测] {m} 超时（>120s），疑似卡死。")
            continue

        # 退出码语义：0=过，1=自测 harness 判定失败，其他=模块崩了。
        # 都必须报 —— "程序不报错但结果是垃圾"里最危险的一种，
        # 就是自测红了但没人看见（F1：红了 2.5 小时还打印 ✅）。
        if r.returncode != 0:
            tail = (r.stdout or r.stderr or "").strip().splitlines()
            hint = tail[-1] if tail else "(无输出)"
            fail(f"[自测] python -m {m} 退出码 {r.returncode}：{hint}")
