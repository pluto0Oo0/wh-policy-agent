"""检查项定义 —— 交付前自检的 7 项检查。

被 scripts/check_deliver.py 调用。拆开的原因：
    CLAUDE.md 第 2 条限制单文件 ≤200 行。全写在一个文件里会到 470+ 行，
    超出所有者"能逐行读懂"的带宽上限（这正是 D11 记录的教训）。

本文件只放"怎么查"，不放"怎么跑" —— 跑在 check_deliver.py 里。
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path

# ⚠️ 项目根目录的确定方式（2026-09-27 改）
#
# 原来写死为「本文件往上两级」，导致**检查器只能检查自己所在的项目**——
# 跑故障注入时无法指向临时目录，两个用例因此失败。
#
# 现在：默认仍是本文件往上两级，但**允许用环境变量 CHECK_TARGET_DIR 覆盖**。
# 故障注入脚本（scripts/selftest.py）用这个变量把检查指向临时构造的假项目。
_target = os.environ.get("CHECK_TARGET_DIR")
PROJECT_ROOT = Path(_target).resolve() if _target else Path(__file__).resolve().parents[2]

# ── 阈值（改这里，不要改代码）──────────────────────────────
MAX_FILE_LINES = 200  # CLAUDE.md 第 2 条
MAX_FIELD_EMPTY_RATE = 0.20  # 自检清单 §二 第 3 条
MIN_EXPECTED_SAMPLES = 1

# 数据源验收硬指标（decisions.md D12）
TARGET_DOC_NUMBERS = ["武政办〔2022〕78号", "武房规〔2018〕2号"]

# 乱码特征字符（UTF-8 字节被当 GBK 解读的典型结果）
SUSPECT_MOJIBAKE = ["锛", "銆", "鍏", "姘", "甯", "鏀", "锟斤拷"]

# SPEC §5 声明了、但属于后续阶段的函数 —— 当前阶段没有不算"未实现"
NOT_YET_PHASED = {
    # Phase 1 尚未开始的模块
    "crawl_detail",
    "clean_text",
    "detect_template_family",
    "save_jsonl",
    "load_conditions",
    "resolve_cohort",
    "check_eligibility",
    "calc_amount",
    # Phase 2/3
    "vector_search",
    "rrf_merge",
    "hybrid_search",
    "rerank_docs",
    "rewrite_query",
}

problems: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def changed_py_files() -> list[Path]:
    """本次改动/新增的 py 文件。取不到 git 信息时退化为扫描 src/ 和 scripts/。

    ⚠️ **排除检查器自身** —— 实测踩过：
        检查脚本的正则（如 `\\.(open|read_text)\\s*\\(...\\)`）会把**自己源码里的
        模式字符串**当成真实调用来匹配，产生假警报，而且指向的行正好是写正则那几行。
        这类"检查器检查自己"的假阳性，正是自检清单警告的"检查本身有 bug"。
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
        )
        names = [n for n in out.stdout.splitlines() if n.endswith(".py")]
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15,
        )
        names += [n for n in untracked.stdout.splitlines() if n.endswith(".py")]
    except Exception:
        names = []

    if not names:
        for sub in ("src", "scripts"):
            d = PROJECT_ROOT / sub
            if d.exists():
                names += [
                    str(p.relative_to(PROJECT_ROOT))
                    for p in d.rglob("*.py")
                    if ".venv" not in p.parts
                ]

    # 排除自检器自己（整个 scripts/checks/ 目录 + check_deliver.py）
    result = []
    for n in names:
        posix = n.replace("\\", "/")
        if posix.startswith("scripts/checks/"):
            continue
        if posix == "scripts/check_deliver.py":
            continue
        p = PROJECT_ROOT / n
        if p.exists():
            result.append(p)
    return result


# ── 1. 单文件行数 ─────────────────────────────────────────────
def check_file_length() -> None:
    for p in changed_py_files():
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        if n > MAX_FILE_LINES:
            fail(
                f"[行数] {p.name} 有 {n} 行，超过 {MAX_FILE_LINES} 上限（CLAUDE.md 第 2 条）。"
                f"超了不报错，但所有者读不过来，审码会变成走过场——"
                f"这正是项目要避免的头号风险（D11）。"
            )


# ── 2. 静默吞错 ───────────────────────────────────────────────
def check_silent_except() -> None:
    for p in changed_py_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"except[^\n:]*:\s*\n\s*pass\b", src):
            line = src[: m.start()].count("\n") + 1
            fail(
                f"[静默吞错] {p.name}:{line} 出现 `except: pass`。"
                f"这条会让所有错误消失得无声无息（CLAUDE.md 第 8 条）。"
            )


# ── 3. 显式编码 ───────────────────────────────────────────────
def check_encoding() -> None:
    """检查文件读写有没有显式 encoding='utf-8'。

    ⚠️ 正则必须允许跨行 —— 实测踩过：
        SAMPLES_PATH.write_text(
            json.dumps(...), encoding="utf-8"    ← 跨行
        )
        早期版本用 `\\(([^)]*)\\)`，跨行时匹配不到 encoding，
        产生**假警报**。这是"检查本身有 bug"的典型。
    """
    for p in changed_py_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        pattern = r"\.(read_text|write_text|open)\s*\([\s\S]{0,200}?\)"
        for m in re.finditer(pattern, src):
            if "encoding" in m.group(0):
                continue
            line = src[: m.start()].count("\n") + 1
            warn(f"[编码] {p.name}:{line} 文件读写未显式 encoding='utf-8'。")
