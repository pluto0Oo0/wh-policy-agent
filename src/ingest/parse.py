"""解析模块 —— 把正文切成结构化段落。

SPEC §5 签名（不得改名）：
    parse_sections(text, family) -> list[dict]

════════════════════════════════════════════════════════════════
为什么不能只有一套切分规则
════════════════════════════════════════════════════════════════
`docs/SPEC.md` §3.3 原本假设所有政策页都是「七段式」。2026-10-04 实测推翻：

  - 汉阳区 15 条页面：七段式关键词 **0/15**
  - 78 号文（红头文件）：**0/10**（「受理/申报对象/申请材料」全部 0 次）

**它们用的是完全不同的组织方式**：
  红头文件   → 中文编号（一、二、三……），78 号文实测 **20 段**
  区级办事指南 → 七段式关键词小标题（若存在）

→ 所以 `parse_sections` **必须按 family 分流**。
   拿七段式去切红头文件，结果是"切出 0 段"，而且**不报错**。

════════════════════════════════════════════════════════════════
本模块的验收标准（2026-10-13 wb 定义，写在 __main__ 里自动跑）
════════════════════════════════════════════════════════════════
不用"看起来对"，用**布尔锚串**：

  1. 六重叠加段被**一个** span 完整框住（段内含三个锚串）
  2. 该 span **不含相邻段**的正文
  3. 全文段数 ≥ 10（切漏的检测）
  反例：段数为 1 → 判不合格（防止"把全文当一段"）

**为什么用锚串不用语义**：锚串是布尔判断，能写成断言、能自动回归。
这正好是故障注入方法的正向应用——**三个锚串就是三个"必须被抓到的已知事实"。**
"""

import json
import re
from pathlib import Path

from .clean import SEVEN_SECTION_KEYWORDS

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── G 族（红头文件）：按中文编号切 ──────────────────────────
# 实测 78 号文形态：`二、减轻租房安居负担。`（标题行自成一行，正文在下一行）
# 编号最大到「二十」（2 个字），留到 3 个字以防出现「一百」这类
CN_NUMERALS = "一二三四五六七八九十"
NUMBERED_HEADING_PATTERN = re.compile(rf"^([{CN_NUMERALS}]{{1,3}})、(.+)$", re.M)

# ── A~F 族：按七段式关键词切 ────────────────────────────────
# ⚠️ **未标定**。SPEC §3.3 给了各族的结构特征但没给判定规则，
#    关键词表沿用 clean.py 的 SEVEN_SECTION_KEYWORDS（那是 A 族的特征词）。
#    真要用在区级页面上，得先拿 33 个区级页面标定一遍。
KEYWORD_HEADING_PATTERN = re.compile(
    rf"^({'|'.join(SEVEN_SECTION_KEYWORDS)})(?:及.{0,6})?\s*[:：]?\s*$", re.M
)


def _split_by_numbering(text: str) -> list[dict]:
    """按中文编号（一、二、三…）切段。

    返回：
        [{"span": (start, end), "heading": "二、减轻租房安居负担。",
          "text": "……该段正文（不含标题行）……"}, ...]

    两个刻意的设计：
    1. **编号之前的内容单独成一段**（heading 为空）——
       78 号文的开头是「为贯彻落实……根据《国务院办公厅关于……》」，
       它不是任何编号段的正文，丢掉会损失背景信息。
    2. **`text` 不含标题行**——这样断言"该段不含相邻段的标题"才有意义
       （否则标题自己就把相邻段的名字带进来了）。
    """
    matches = list(NUMBERED_HEADING_PATTERN.finditer(text))
    if not matches:
        return []

    sections: list[dict] = []

    # 引言（第一个编号之前）
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append({"span": (0, matches[0].start()), "heading": "", "text": preamble})

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(
            {
                "span": (m.start(), end),
                "heading": m.group(0).strip(),
                "text": text[m.end() : end].strip(),
            }
        )

    return sections


def _split_by_keywords(text: str) -> list[dict]:
    """按七段式关键词小标题切段（A~F 族）。

    ⚠️ **未标定，未见真实样本验证过**。见模块 docstring 的说明。
    与 G 族保持同样的返回结构，这样调用方不用分支。
    """
    matches = list(KEYWORD_HEADING_PATTERN.finditer(text))
    if not matches:
        return []

    sections: list[dict] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append({"span": (0, matches[0].start()), "heading": "", "text": preamble})

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(
            {
                "span": (m.start(), end),
                "heading": m.group(0).strip(),
                "text": text[m.end() : end].strip(),
            }
        )

    return sections


def parse_sections(text: str, family: str = "G") -> list[dict]:
    """把正文切成结构化段落。

    参数：
        text:   已清洗的正文纯文本（`clean_text` 的产出）
        family: 模板族（`detect_template_family` 的产出）

    返回：
        [{"span": (start, end), "heading": str, "text": str}, ...]
        **切不出任何段时返回空列表** —— 由调用方决定这算不算失败。

    为什么空列表不在这里抛异常：
        与 `clean_text` 同一条原则——本函数只负责"切"，不负责
        "决定切不出算不算失败"。判断留在调用方，让处置点只有一个。
    """
    if family in ("A", "B", "C", "D", "E", "F"):
        return _split_by_keywords(text)
    # G 族（非结构化 / 红头文件）
    return _split_by_numbering(text)


# ══════════════════════════════════════════════════════════════
# 验收（2026-10-13 wb 定义的三个断言 + 一个反例）
# 跑法：python -m src.ingest.parse
# 数据来源：data/processed/policies.jsonl（已抓好的，不再联网）
# ══════════════════════════════════════════════════════════════

# 六重叠加段的三个锚串。**必须全部出现在同一个 span 里**，少一个就是切漏。
ANCHORS_IN_SECTION_2 = ("按照不高于市场租金的70%", "不超过3年", "2000元、1500元")

# 相邻段的锚串。它们**不得**出现在六重叠加段里。
ANCHORS_OF_NEIGHBOURS = ("先落户后就业", "稳定政策性岗位")


def _find_housing_section(sections: list[dict]) -> dict | None:
    """找出「减轻租房安居负担」那一段（用标题定位，不用序号——序号会变）。"""
    for s in sections:
        if "减轻租房安居负担" in s["heading"]:
            return s
    return None


def check_sections(sections: list[dict]) -> list[str]:
    """对切分结果做三条断言 + 一个反例，返回失败清单（空 = 全过）。

    为什么抽成独立函数、而不是写在 `_run_acceptance` 里：
        **断言本身也要能被注入故障验证。** 一个永远不会报错的断言，
        和没有这个断言是同一件事（本项目踩过：`len(html) < 1000`
        那条软 404 检查在失效页 190,250 字符面前永远不触发）。
        抽出来才能在 `__main__` 里拿坏输入直接打它。
    """
    failures: list[str] = []

    # ── 断言 1：六重叠加段被一个 span 完整框住 ────────────────
    housing = _find_housing_section(sections)
    if housing is None:
        failures.append("断言1：找不到「减轻租房安居负担」段")
    else:
        missing = [a for a in ANCHORS_IN_SECTION_2 if a not in housing["text"]]
        if missing:
            failures.append(f"断言1：该段缺锚串 {missing}")
        # ── 断言 2：不含相邻段的正文 ──────────────────────────
        leaked = [a for a in ANCHORS_OF_NEIGHBOURS if a in housing["text"]]
        if leaked:
            failures.append(f"断言2：该段混入了相邻段内容 {leaked}")

    # ── 断言 3：段数 ≥ 10 ─────────────────────────────────────
    if len(sections) < 10:
        failures.append(f"断言3：只切出 {len(sections)} 段（要求 ≥10，说明切漏了）")

    # ── 反例：段数为 1 = 把全文当一段，判不合格 ────────────────
    if len(sections) == 1:
        failures.append("反例：只切出 1 段 —— 等于没切")

    return failures


def _run_acceptance() -> int:
    """跑验收，返回退出码（0 = 全过）。"""
    path = PROJECT_ROOT / "data" / "processed" / "policies.jsonl"
    if not path.exists():
        print(f"❌ 找不到 {path}，先跑纵切第 1 步")
        return 1

    docs = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    doc = next((d for d in docs if d["doc_id"] == "t20220608_1983869"), None)
    if doc is None:
        print("❌ policies.jsonl 里没有 78 号文")
        return 1

    sections = parse_sections(doc["content"], doc["template_family"])
    failures = check_sections(sections)

    print(f"切出 {len(sections)} 段（family={doc['template_family']!r}）")
    for s in sections[:4]:
        print(f"  span={s['span']}  heading={s['heading']!r}  text={len(s['text'])} 字")
    print("  ...")

    print()
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
        print(f"\n❌ 未通过，{len(failures)} 个问题")
        return 1

    print("  ✅ 断言1：六重叠加段完整（3 个锚串全在）")
    print("  ✅ 断言2：未混入相邻段")
    print(f"  ✅ 断言3：段数 {len(sections)} ≥ 10")
    print("  ✅ 反例：段数 > 1")
    print("\n✅ 全部通过")
    return 0


def _run_fault_injection() -> int:
    """故障注入：把坏输入喂给 `check_sections`，**它必须报错**。

    为什么必须做：本项目刚踩过一条永远不触发的检查（`len(html) < 1000`）。
    **断言跑在好数据上全绿，不能证明它有效；能抓到坏数据才能。**
    """
    good = [
        {"span": (0, 10), "heading": "一、推行先落户后就业。", "text": "先落户后就业的内容"},
        {"span": (10, 20), "heading": "二、减轻租房安居负担。", "text": "按照不高于市场租金的70%…不超过3年…2000元、1500元"},
        {"span": (20, 30), "heading": "三、稳定政策性岗位。", "text": "稳定政策性岗位的内容"},
    ] + [{"span": (30 + i, 31 + i), "heading": f"{i}、其他", "text": "x"} for i in range(8)]

    cases = [
        ("好输入（3 个锚串齐全、10+ 段）", good, 0),
        ("注入：六重叠加段被切开（缺「不超过3年」）",
         [dict(good[0]), {**good[1], "text": "按照不高于市场租金的70%…2000元、1500元"}, *good[2:]], 1),
        ("注入：混入相邻段正文",
         [dict(good[0]), {**good[1], "text": good[1]["text"] + "先落户后就业"}, *good[2:]], 1),
        ("注入：只切出 1 段（把全文当一段）",
         [{"span": (0, 100), "heading": "二、减轻租房安居负担。", "text": "按照不高于市场租金的70%不超过3年2000元、1500元"}], 1),
        ("注入：切漏（只有 3 段）", good[:3], 1),
    ]

    print("=" * 62)
    print("故障注入：断言必须能抓到坏输入")
    print("=" * 62)
    bad = 0
    for label, sections, want_fail in cases:
        fails = check_sections(sections)
        caught = len(fails) > 0
        ok = caught == (want_fail > 0)
        if not ok:
            bad += 1
        mark = "✅" if ok else "🔴"
        print(f"  {mark} {label}")
        print(f"      期望{'报错' if want_fail else '通过'} / 实际{'报错' if caught else '通过'}"
              f"{'  → ' + fails[0] if fails else ''}")
    print()
    if bad:
        print(f"🔴 {bad} 个用例不符合预期 —— 断言有问题")
        return 1
    print("✅ 全部符合预期：断言能抓到 4 类注入的故障，好输入不误报")
    return 0


if __name__ == "__main__":
    code = _run_acceptance()
    print()
    code |= _run_fault_injection()
    raise SystemExit(code)
