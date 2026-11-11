"""为区级及市级政策生成逐句编号快照。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/processed/policies.jsonl"
OUTPUT_DIR = ROOT / "eval/t04_draft"
BASE_DOC_ID = "t20220608_1983869"
# 部分抓取正文用 ASCII 分号分隔编号步骤，需保留与中文分号相同的切分边界。
TERMINATORS = set("。；！？;")
CLOSERS = set("」』”’\"'）】〕〉》")
KEYWORDS = ("人才租赁房", "租赁房", "人才公寓", "配租", "租金", "高校毕业生", "住房", "资格", "免租", "申请", "退出")


def split_sentences(content: str) -> list[str]:
    """按中文句末标点切句，并将闭合引号留在原句内。"""
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


def main() -> None:
    """读取19条政策，校验每份快照并写入编号文本。"""
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = [row for row in rows if row.get("is_policy_text") is True and row.get("doc_id") != BASE_DOC_ID]
    assert len(targets) == 19, f"目标政策数应为19，实际为{len(targets)}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for row in targets:
        doc_id = row.get("doc_id")
        content = row.get("content", "")
        assert doc_id and content.strip(), f"政策缺少 doc_id 或正文：{doc_id}"
        sentences = split_sentences(content)
        assert len(sentences) >= 10, f"{doc_id} 句子数不足10：{len(sentences)}"
        assert all(sentence.strip() for sentence in sentences), f"{doc_id} 存在空句"
        found = [keyword for keyword in KEYWORDS if keyword in content]
        assert found, f"{doc_id} 未命中政策关键词"
        lines = [f"Q{index:02d}\t{sentence}" for index, sentence in enumerate(sentences, 1)]
        (OUTPUT_DIR / f"{doc_id}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{doc_id}\t句数={len(sentences)}\t关键词={'、'.join(found)}")


if __name__ == "__main__":
    main()
