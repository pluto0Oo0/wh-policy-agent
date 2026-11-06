"""expected_samples 真对比 —— 全套检查里唯一能证明「内容对了」的一环。

════════════════════════════════════════════════════════════════
为什么单独一个文件
════════════════════════════════════════════════════════════════
自检清单 §五 写：「第 5 步最重要 —— 和'应该是什么'对比」。
但 2026-09-24 的实现是**假对比**：写死 3 个标题字符串打印出来让人眼看，
既不比对、也不报错，脚本永远返回成功。（wb 发现的缺口 E）

本文件把它做成真对比：
    ① expected_samples.json 存「url → 浏览器里看到的真实标题」
    ② 脚本拿它去 list.jsonl 里逐条核对
    ③ 不一致就报错退出

**关键约束**：expected_title 必须来自浏览器，不能从 list.jsonl 抄。
抄了就等于自己跟自己对，失去了对比的意义。
"""

from __future__ import annotations

import json
from pathlib import Path

# ⚠️ 必须用 config 的 PROJECT_ROOT（支持 CHECK_TARGET_DIR 覆盖）。
# 曾在这里写死 parents[2]，导致故障注入的临时目录场景检查了真项目 → 恒真。
# selftest 2026-10-19 抓到此问题。
from .config import PROJECT_ROOT

SAMPLES_PATH = PROJECT_ROOT / "eval" / "expected_samples.json"
LIST_PATH = PROJECT_ROOT / "data" / "processed" / "list.jsonl"

MIN_EXPECTED_SAMPLES = 1
PLACEHOLDER_MARK = "待人工填写"


def _gen_template() -> dict:
    """生成模板：从 list.jsonl 取前几条的 URL，标题留空待填。"""
    samples: dict = {}
    if not LIST_PATH.exists():
        return samples

    for ln in LIST_PATH.read_text(encoding="utf-8").splitlines()[:3]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        samples[r.get("url", "")] = {
            "expected_title": f"<{PLACEHOLDER_MARK}：打开该 URL，复制浏览器里的真实标题>",
            "note": "这个值必须来自浏览器，不能从 list.jsonl 抄——抄了就等于自己跟自己对。",
        }
    return samples


def check_expected_samples(fail, init: bool = False) -> None:
    """参数 fail 是报告错误的回调（由 check_deliver.py 传入）。"""

    # ── 文件不存在 ────────────────────────────────────────
    if not SAMPLES_PATH.exists():
        if init:
            samples = _gen_template()
            SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
            SAMPLES_PATH.write_text(
                json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  📝 已生成模板：eval/expected_samples.json（{len(samples)} 条）")
            if not samples:
                fail("[假对比] 无法生成模板——list.jsonl 不存在或为空。")
                return
            fail(
                f"[假对比] 模板已生成，但 {len(samples)} 条 expected_title 全是占位符。"
                f"**必须人工填写**：逐个打开 URL，把浏览器里看到的真实标题填进去。"
                f"这是全套检查里唯一能证明「内容对了」的一环。"
            )
            return

        fail(
            "[假对比] 缺 eval/expected_samples.json。"
            "当前 data 校验只能证明格式没坏，无法证明内容对了。"
            "跑 `python scripts/check_deliver.py --init` 生成模板。"
        )
        return

    # ── 解析 ──────────────────────────────────────────────
    try:
        data = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"[假对比] expected_samples.json 解析失败：{e}")
        return

    if len(data) < MIN_EXPECTED_SAMPLES:
        fail(f"[假对比] expected_samples.json 只有 {len(data)} 条，等于没做对比。")
        return

    # ── 占位符检查 ────────────────────────────────────────
    placeholders = [
        u for u, v in data.items()
        if PLACEHOLDER_MARK in str(v.get("expected_title", ""))
        or not v.get("expected_title")
    ]
    if placeholders:
        fail(
            f"[假对比] {len(placeholders)} 条 expected_title 是空值或占位符。"
            f"**必须人工填写真实标题**，否则这一步是假对比。"
        )
        return

    # ── 真对比：拿预期去实际数据里核对 ─────────────────────
    if not LIST_PATH.exists():
        return

    actual: dict = {}
    for ln in LIST_PATH.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        actual[r.get("url")] = r.get("title")

    mismatched = []
    for url, v in data.items():
        exp = str(v.get("expected_title", "")).strip()
        act = actual.get(url)
        if act is None:
            mismatched.append(f"{url} → 实际数据里找不到这个 URL")
        elif exp != str(act).strip():
            mismatched.append(f"{url}\n      期望: {exp}\n      实际: {act}")

    if mismatched:
        fail(
            f"[假对比] {len(mismatched)} 条与预期不符——**解析可能抽错了**：\n      "
            + "\n      ".join(mismatched[:3])
        )
