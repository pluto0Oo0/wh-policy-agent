"""检查器自检 —— 用故障注入验证「检查本身有效」。

════════════════════════════════════════════════════════════════
为什么需要这个（wb 2026-09-27 提出）
════════════════════════════════════════════════════════════════
> **判断一个检查是否有效，看它能不能抓到「注入的故障」，
> 而不是看它正常运行时会不会全部通过。**
>
> **一个永远不会报警的检查，和没有这个检查，是同一件事。**

本脚本做的事：**构造已知的坏输入，断言检查器必须报错。**
哪个没报错，**哪个就是恒真的检查**（或假通过的检查）。

════════════════════════════════════════════════════════════════
它为什么必要
════════════════════════════════════════════════════════════════
2026-09-26 实测踩过两类"检查器自己的 bug"：

① **假通过**：`verify_title_format.py` 在 3 个样本全部抓取失败时，
   输出 **"✅ 无后缀"** —— 空输入落进了 else 分支，产出了错误结论。

② **假警报**：`check_encoding` 的旧正则跨行时不匹配 `encoding`，
   而且扫自己源码里的正则字符串 → 两类假阳性。
   **假警报会训练人忽略警告。**

**两种都能用故障注入抓出来。**

用法：
    python scripts/selftest.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
CHECK_DELIVER = str(PROJECT_ROOT / "scripts" / "check_deliver.py")


def run_check_deliver(target: Path) -> tuple[int, str]:
    """在指定目录跑 check_deliver.py，返回 (退出码, 输出)。

    ⚠️ 关键：通过环境变量 CHECK_TARGET_DIR 告诉检查器"检查哪个目录"。
       否则检查器会去检查它自己所在的项目（写死的 PROJECT_ROOT），
       故障注入就测不出东西——**这是本脚本第一版失败的原因。**
    """
    try:
        env = dict(os.environ)
        env["CHECK_TARGET_DIR"] = str(target)
        r = subprocess.run(
            [PYTHON, CHECK_DELIVER],
            cwd=target,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════════
# 故障注入用例
# ══════════════════════════════════════════════════════════════


def case_empty_jsonl() -> tuple[bool, str]:
    """故障 1：JSONL 是空的（一个样本都没有）。

    对应 2026-09-26 那个 bug——空输入落进 else 分支输出 ✅。
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        # 造一个最小项目结构
        (tmp / "data" / "processed").mkdir(parents=True)
        (tmp / "data" / "processed" / "list.jsonl").write_text("", encoding="utf-8")
        (tmp / "eval").mkdir()
        (tmp / "docs").mkdir()
        (tmp / "src").mkdir()
        (tmp / "scripts").mkdir()

        # 空 JSONL 不该让脚本崩，但也不该输出 ✅ 全通过
        code, out = run_check_deliver(tmp)
        if code == -1:
            return False, f"脚本本身崩了：{out[:200]}"
        # 空数据 + 没有 expected_samples → 应该报「假对比」缺失
        if "假对比" in out or code != 0:
            return True, f"✅ 抓到了（exit={code}）"
        return False, f"❌ 没抓到 —— 空输入竟然全通过！输出：{out[-200:]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_long_file() -> tuple[bool, str]:
    """故障 2：单文件超过 200 行。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "data" / "processed").mkdir(parents=True)
        (tmp / "eval").mkdir()
        (tmp / "docs").mkdir()
        (tmp / "src").mkdir()
        (tmp / "scripts").mkdir()
        (tmp / "scripts" / "too_long.py").write_text(
            "\n".join(f"x{i} = {i}" for i in range(250)), encoding="utf-8"
        )

        code, out = run_check_deliver(tmp)
        if "行数" in out and "250" in out:
            return True, "✅ 抓到了（250 行）"
        return False, f"❌ 没抓到 —— 250 行文件竟然没报错"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_silent_except() -> tuple[bool, str]:
    """故障 3：静默吞错 `except: pass`。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "data" / "processed").mkdir(parents=True)
        (tmp / "eval").mkdir()
        (tmp / "docs").mkdir()
        (tmp / "src").mkdir()
        (tmp / "scripts").mkdir()
        (tmp / "scripts" / "swallow.py").write_text(
            "try:\n    x = 1\nexcept Exception:\n    pass\n", encoding="utf-8"
        )

        code, out = run_check_deliver(tmp)
        if "静默吞错" in out:
            return True, "✅ 抓到了"
        return False, "❌ 没抓到 —— `except: pass` 竟然没报错"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_placeholder_samples() -> tuple[bool, str]:
    """故障 4：expected_samples 里全是占位符（假对比）。

    这是当前项目里的真实状态。
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "data" / "processed").mkdir(parents=True)
        (tmp / "data" / "processed" / "list.jsonl").write_text(
            '{"url": "http://x/a", "title": "A", "path": "./t20260101_1.shtml", "page": 1}\n',
            encoding="utf-8",
        )
        (tmp / "eval").mkdir()
        (tmp / "eval" / "expected_samples.json").write_text(
            '{"http://x/a": {"expected_title": "<待人工填写：打开 URL 复制真实标题>"}}',
            encoding="utf-8",
        )
        (tmp / "docs").mkdir()
        (tmp / "src").mkdir()
        (tmp / "scripts").mkdir()

        code, out = run_check_deliver(tmp)
        if "假对比" in out and "占位符" in out:
            return True, "✅ 抓到了（占位符被识破）"
        return False, "❌ 没抓到 —— 占位符竟然被当成有效对比"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_no_bom() -> tuple[bool, str]:
    """故障 5：JSONL 带 UTF-8 BOM。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "data" / "processed").mkdir(parents=True)
        p = tmp / "data" / "processed" / "list.jsonl"
        p.write_bytes(b"\xef\xbb\xbf" + b'{"url": "http://x/a", "title": "A"}\n')
        (tmp / "eval").mkdir()
        (tmp / "docs").mkdir()
        (tmp / "src").mkdir()
        (tmp / "scripts").mkdir()

        code, out = run_check_deliver(tmp)
        if "BOM" in out:
            return True, "✅ 抓到了"
        return False, "❌ 没抓到 —— BOM 竟然没报错"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════

CASES = [
    ("空 JSONL（空输入不该输出 ✅）", case_empty_jsonl),
    ("超长文件（250 行）", case_long_file),
    ("静默吞错 except: pass", case_silent_except),
    ("占位符当有效对比", case_placeholder_samples),
    ("JSONL 带 BOM", case_no_bom),
]


def main() -> int:
    print("=" * 72)
    print("检查器自检（故障注入）")
    print("=" * 72)
    print()
    print("原理（wb 2026-09-27）：判断一个检查是否有效，看它能不能抓到「注入的故障」，")
    print("而不是看它正常运行时会不会全部通过。")
    print()

    passed, failed = 0, 0

    for name, fn in CASES:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"用例本身崩了：{type(e).__name__}: {e}"

        mark = "✅" if ok else "❌"
        print(f"  {mark} {name}")
        print(f"      {msg}")
        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print("=" * 72)
    print(f"通过 {passed} / {failed + passed}")
    print("=" * 72)
    print()

    if failed:
        print("❌ 有检查项抓不到对应的故障 —— 那个检查是「恒真」的，等于没有。")
        print("   修 `scripts/checks/` 里对应的检查项，然后重跑本脚本。")
        return 1

    print("✅ 所有检查项都抓到了对应的故障 —— 它们不是恒真的。")
    print()
    print("⚠️  但请注意（CC 补充，2026-09-27）：")
    print("   本脚本只能测「我想到要注入的故障」。")
    print("   真正漏掉的，可能是「我连该检查这个都没想到」的东西。")
    print("   所以故障注入能提高可信度，**但不能证明完备**。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
