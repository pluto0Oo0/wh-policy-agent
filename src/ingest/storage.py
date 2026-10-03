"""把爬到的列表存下来。

两个职责：
  1. 原始 HTML 落盘到 data/raw/  —— 页面改版后可用历史数据回归测试解析逻辑
  2. 列表记录落盘到 data/processed/list.jsonl —— 供下一步（抓详情页）使用

幂等设计：按 url 去重，重复运行不会产生重复记录。
"""

import json
import sys
from pathlib import Path

# 项目根目录（本文件在 src/ingest/ 下，往上三层）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def save_raw_html(html: str, source_key: str, page: int) -> Path:
    """保存原始 HTML。

    为什么必须存：
        解析逻辑改错了可以拿历史 HTML 重跑，
        不用重新爬一遍（既慢又给对方服务器增加压力）。
    """
    raw_dir = PROJECT_ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    path = raw_dir / f"{source_key}_page{page}.html"
    path.write_text(html, encoding="utf-8")
    return path


def load_existing_urls(jsonl_path: Path) -> set[str]:
    """读已有的 JSONL，返回已抓过的 url 集合（用于幂等去重）。"""
    if not jsonl_path.exists():
        return set()

    urls = set()
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                urls.add(json.loads(line)["url"])
            except (json.JSONDecodeError, KeyError):
                # 单行坏了不影响整体 —— 但要警告，不能静默跳过
                print(f"  ⚠️  跳过损坏行：{line[:80]}")
    return urls


def append_records(records: list[dict], jsonl_path: Path) -> int:
    """追加记录到 JSONL，返回实际新增条数。

    幂等：已存在的 url 跳过。
    """
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing_urls(jsonl_path)

    new_records = [r for r in records if r["url"] not in existing]

    if new_records:
        # 用追加模式，不覆盖历史数据
        with jsonl_path.open("a", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return len(new_records), len(records) - len(new_records)
