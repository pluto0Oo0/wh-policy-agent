"""从政策正文生成逐句编号快照。"""

import json
from pathlib import Path


DOC_ID = "t20220608_1983869"
SOURCE = Path("data/processed/policies.jsonl")
OUTPUT = Path("eval/v3_draft/source_snapshot.txt")
CLOSERS = set("」』”’\"'）】〕〉》")
TERMINATORS = set("。；！？")


def split_sentences(content: str) -> list[str]:
    """按指定中文标点切分，并把闭合引号留在对应句子末尾。"""
    sentences = []
    for paragraph in content.splitlines():
        start = 0
        index = 0
        while index < len(paragraph):
            if paragraph[index] in TERMINATORS:
                end = index + 1
                while end < len(paragraph) and paragraph[end] in CLOSERS:
                    end += 1
                sentence = paragraph[start:end]
                if sentence.strip():
                    sentences.append(sentence)
                start = end
                index = end
            else:
                index += 1
        tail = paragraph[start:]
        if tail.strip():
            sentences.append(tail)
    return sentences


def is_non_clause(sentence: str) -> bool:
    """识别署名、网页控件、责任单位等非条款文本。"""
    compact = "".join(sentence.split())
    markers = (
        "各区人民政府，市人民政府各部门：", "（责任单位：", "武汉市人民政府办公厅",
        "【打印】", "【扫一扫】", "【收藏】", "扫一扫在手机上查看当前页面",
        "武汉市人民政府微信公众号", "附件：", "武政办〔2022〕78号—",
    )
    return compact.startswith(tuple("".join(marker.split()) for marker in markers)) or compact.startswith("2022年6月7日")


def main() -> None:
    """读取政策第 0 条并写出经断言校验的句子快照。"""
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and rows[0].get("doc_id") == DOC_ID, "第 0 条不是目标政策"
    sentences = split_sentences(rows[0]["content"])
    assert len(sentences) >= 50, f"句子数不足 50：{len(sentences)}"
    assert all(sentence.strip() for sentence in sentences), "存在空句"
    percent_ids = [f"S{index:02d}" for index, sentence in enumerate(sentences, 1) if "70%" in sentence]
    assert percent_ids, "未找到含 70% 的句子"
    lines = []
    for index, sentence in enumerate(sentences, 1):
        suffix = "（非条款）" if is_non_clause(sentence) else ""
        lines.append(f"S{index:02d}\t{sentence}{suffix}")
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"句子数：{len(sentences)}")
    print(f"含 70% 的句子编号：{', '.join(percent_ids)}")


if __name__ == "__main__":
    main()
