"""条件数据模型 —— 判定引擎的输入契约。

SPEC §5 定义了 `Condition` 的字段，SPEC §2.2 定义了它的来源
（`eval/golden_conditions.jsonl`，人工标注产生）。

════════════════════════════════════════════════════════════════
这个文件为什么值得单独存在（而不是用 dict）
════════════════════════════════════════════════════════════════
条件是这个项目的**核心数据结构**——SPEC §2.2 原话是「全项目最核心的数据结构」。

用 dict 的问题不是"不好看"，是**错误会跑到很远的地方才暴露**：
    写错字段名 `c["filed"]` → 到 engine 判定时才发现，而那时已经跑了 100 条政策。
用 dataclass + 构造时校验：
    **错误在"造出这个对象"的那一刻就炸，离出错的地方最近。**

这是本项目反复出现的同一条原则：**把检查放在最早能发现它的位置。**

════════════════════════════════════════════════════════════════
`applies_to_cohort` 为什么是必填（SPEC §3.2）
════════════════════════════════════════════════════════════════
武汉的安居政策是**合法的 grandfathering 双轨**（不是 bug）：
    老政策（武房规〔2018〕2号）：毕业 3 年内 + 武汉户籍 + 家庭无房
    新政策（武政办〔2022〕78号）：毕业 6 年内 + 社保 + 家庭无房
分界点 2022-06-07。

→ **"取最新版本"是错的。** 每条条件必须带 `applies_to_cohort`，
  判定时先确定用户属于哪个 cohort，再取对应那一套规则。
"""

from dataclasses import dataclass, field
from typing import Any

# ── 合法取值（SPEC §2.2 / §5）────────────────────────────────
# 为什么要把它们写成常量而不是散在代码里：
#   校验、报错信息、以后的文档生成都要用同一份清单。
#   写死两遍就会漂移（本项目已经在"模板族 A~G"上踩过一次）。
COND_TYPES = ("资格", "计算", "材料", "时序互斥")

# ⚠️ **2026-10-13：`<` 和 `>` 是新增的，SPEC §2.2 原文只列了 `>=` `<=` `==` `in` `exists`。**
#
#    加它们的原因：SPEC 漏了，而标注里真的要用。
#      `_01` 原文「年龄**不满**45周岁」→ 语义就是 `<` 45，写成 `<=` 是错的
#      `_09` 原文「本通知公布**前**留汉」→ 语义就是 `<` 2022-06-07
#      （日期写 `<= "2022-06-06"` 更是脆弱，差一天就错，而且看不出来）
#
#    发现方式：本模块的构造校验 + loader 的加载断言。
#    **纸面上讨论了 11 天没发现，写一个会校验的加载器立刻就暴露了。**
#
#    → **这是 SPEC 变更，已报所有者待批。** 若驳回，我改回 5 个并重标那两条。
OPS = (">=", "<=", "==", "in", "exists", "<", ">")

# 计算类条件必须给 formula，其他类给了 formula 说明标错了 —— 两个方向都要管
CALC_TYPE = "计算"

# 政策有效性取值（SPEC §2.1），`policy_status` 用
POLICY_STATUSES = ("现行", "已废止", "部分失效", "未核实")


class ConditionError(ValueError):
    """条件数据本身不合法。

    为什么单独一个异常类：
        调用方能区分「数据坏了」（该停下来修标注）和「程序有 bug」（该改代码）。
        两者的处置完全不同。
    """


@dataclass
class Condition:
    """一条可判定的政策条件。

    字段含义见 SPEC §2.2。**全部必填的字段没有默认值**——
    这样漏填会在构造时就报错，而不是在后面某处变成 None 引发更难查的问题。
    """

    cond_id: str
    doc_id: str
    applies_to_cohort: str
    cond_type: str
    field: str
    op: str
    value: Any
    source_text: str
    formula: str | None = None
    ambiguity: str | None = None

    # ── 豁免条件（2026-10-13 新增，SPEC §2.2 的字段扩展）────────
    # 形如 `{"field": "education", "op": "in", "value": ["硕士", "博士"]}`，
    # 语义：**这个子条件对画像成立时，本条条件跳过（视为满足）**。
    #
    # 为什么必须有它：78 号文原文「年龄不满45周岁（**研究生不受年龄限制**）」——
    #   `age < 45` 这一条**对研究生不适用**，但 SPEC §2.2 原契约里
    #   没有任何字段能表达"某个子条件成立时本条豁免"。
    #
    # 为什么不用 `ambiguity` 代替：ambiguity 的语义是"这条判不了"→ UNKNOWN，
    #   而豁免的语义是"这条对他成立"→ PASS。**两者结果完全相反。**
    #
    # 为什么不用 `applies_to_cohort` 代替：cohort 表达的是 grandfathering 时间轨道
    #   （老政策/新政策），豁免表达的是学历分层。**混用会让 cohort 变成万能字段。**
    exempt_when: dict | None = None

    # ── 核对留痕（D17：AI 起草 + 所有者蜜罐核对）────────────────
    # 为什么这三条要进数据模型、而不是记在别的地方：
    #   SPEC §6 Phase 2 要用 golden set 当 ground truth 去评 LLM 抽取。
    #   如果"这条是谁核的、什么时候核的"没有随数据走，
    #   那份 ground truth 就**无法被追溯**，Phase 2 的数字也就无从辩护。
    verified_by: str = ""
    verified_at: str = ""
    verify_note: str = ""

    # 解析时记下的非致命问题（供 loader 汇总打印，不阻断加载）
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """构造时立刻校验 —— 让错误离出错的地方最近。

        注意这里**只做"格式对不对"的检查**，不做"内容对不对"。
        内容对不对（阈值抄错没有、原文引对没有）只能靠人核对，
        这正是 `verified_by` 三个字段存在的理由。
        """
        if not self.cond_id:
            raise ConditionError("cond_id 不能为空")
        if not self.doc_id:
            raise ConditionError(f"{self.cond_id}: doc_id 不能为空")
        if not self.applies_to_cohort:
            raise ConditionError(
                f"{self.cond_id}: applies_to_cohort 不能为空"
                "（SPEC §3.2：没有它就无法表达 grandfathering 双轨）"
            )
        if self.cond_type not in COND_TYPES:
            raise ConditionError(
                f"{self.cond_id}: cond_type={self.cond_type!r} 不合法，可选 {COND_TYPES}"
            )
        if self.op not in OPS:
            raise ConditionError(f"{self.cond_id}: op={self.op!r} 不合法，可选 {OPS}")
        if not self.source_text:
            raise ConditionError(
                f"{self.cond_id}: source_text 必填"
                "（SPEC §2.2：用于溯源，判定要能输出'依据哪一条'）"
            )

        # formula 与 cond_type 必须一致 —— 两个方向都查
        if self.cond_type == CALC_TYPE and not self.formula:
            self.warnings.append(f"{self.cond_id}: cond_type=计算 但 formula 为空")
        if self.cond_type != CALC_TYPE and self.formula:
            self.warnings.append(
                f"{self.cond_id}: cond_type={self.cond_type} 却给了 formula，是否标错类型？"
            )

        # ── exempt_when 的格式校验 ───────────────────────────────
        # 为什么在构造时就校验：豁免条件写错了（少个 key、op 拼错）
        # **不会报错，只会让豁免静默失效** —— 50 岁的博士又会被判 FAIL，
        # 而输出看起来完全正常。这类"少判了豁免"正是最难发现的。
        if self.exempt_when is not None:
            if not isinstance(self.exempt_when, dict):
                raise ConditionError(f"{self.cond_id}: exempt_when 必须是 dict 或 null")
            lack = {"field", "op", "value"} - set(self.exempt_when)
            if lack:
                raise ConditionError(
                    f"{self.cond_id}: exempt_when 缺字段 {sorted(lack)}"
                    f"（需要 field / op / value 三个）"
                )
            if self.exempt_when["op"] not in OPS:
                raise ConditionError(
                    f"{self.cond_id}: exempt_when 的 op={self.exempt_when['op']!r} 不合法，"
                    f"可选 {OPS}"
                )

    @property
    def is_ambiguous(self) -> bool:
        """含模糊表述的条件。

        SPEC §3.5：**ambiguity 非 null 时，判定必须返回 UNKNOWN 并触发主动追问**，
        不许硬给答案。约 30% 的条件含模糊/需裁量表述（调研报告 §5.2 实测）。
        """
        return bool(self.ambiguity)

    @property
    def is_verified(self) -> bool:
        """这条条件是否已被人工核对过（D17 的留痕要求）。"""
        return bool(self.verified_by and self.verified_at)
