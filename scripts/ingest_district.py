"""区级政策源抓取入口 —— 把 12 个官方区级源抓成候选记录。

用法：
    .venv/Scripts/python.exe scripts/ingest_district.py

输出：
    data/raw/district/<key>.html                 原始 HTML（落盘，不入库）
    data/processed/district_candidates.jsonl     候选记录（字段与 policies.jsonl 一致）

断言（任何一条失败即报错退出，不静默）：
    1. 每个 URL 必须 HTTP 200
    2. 每个正文必须能用标题锚点定位到
    3. 正文长度不少于 MIN_BODY_CHARS
    4. 失败源数不得超过 MAX_FAILURES
"""

import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest.district_sources import (  # noqa: E402
    SOURCES,
    doc_id_from_url,
    extract_body,
    extract_date,
)

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "district"
OUT_JSONL = PROJECT_ROOT / "data" / "processed" / "district_candidates.jsonl"

# 允许失败的源数。取 0：这 12 个都是人工挑选、已实测可达的官网源，
# 任何一条失败都说明网络或站点变了，必须看见，不能被"允许 N 条失败"盖住。
MAX_FAILURES = 0
MIN_BODY_CHARS = 500
REQUEST_INTERVAL_SEC = 1.0
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; wh-policy-agent/0.1)"}


def fetch(url: str) -> str:
    """请求一个 URL，返回解码后的 HTML。

    为什么只接受 200：区级站点的失效页返回真 404（见 CONTEXT §3.2 第 11 条），
    其他状态码一律视为抓取失败，不解析。
    """
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    resp.encoding = resp.apparent_encoding
    return resp.text


def build_record(src, html: str) -> dict:
    """把一个源的 HTML 转成 SPEC §2.1 字段结构的候选记录。

    为什么 `policy_status` 固定为「未核实」：区级源的有效性需要人工或后续流程核实，
    在这里假定"现行"就是编造。`status_evidence` 留空，符合 ALLOWED_EMPTY_FIELDS。
    """
    body = extract_body(html, src.title_anchor, src.anchor_pos)
    if len(body) < MIN_BODY_CHARS:
        raise ValueError(f"正文只有 {len(body)} 字，低于 {MIN_BODY_CHARS}，疑似抽到导航页")
    return {
        "doc_id": doc_id_from_url(src.url),
        "url": src.url,
        "title": src.title_anchor,
        "doc_number": "",
        "publish_date": extract_date(html),
        "region": src.region,
        "template_family": "未分类",
        "content": body,
        "crawled_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "policy_status": "未核实",
        "status_verified_at": "",
        "status_evidence": "",
        "superseded_by": None,
        "source_role": "content",
        "attachments": [],
        # 区分政策原文/新闻稿：合并进正式库时必须保留（审核 2026-11-08 找回）
        "is_policy_text": src.is_policy_text,
        "note": src.note,
    }


def main() -> int:
    """跑完 12 个源，写候选文件，打印结果。返回退出码。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    failures: list[str] = []

    for src in SOURCES:
        try:
            html = fetch(src.url)
            raw_path = RAW_DIR / f"{src.region}_{doc_id_from_url(src.url)}.html"
            raw_path.write_text(html, encoding="utf-8")
            records.append(build_record(src, html))
            print(f"OK   {src.key:20} {src.region}")
        except Exception as exc:  # 记录后继续，最后统一判定，不静默
            failures.append(f"{src.key}: {type(exc).__name__}: {exc}")
            print(f"FAIL {src.key:20} {type(exc).__name__}: {exc}")
        time.sleep(REQUEST_INTERVAL_SEC)

    print(f"\n成功 {len(records)} 条，失败 {len(failures)} 条")
    if len(failures) > MAX_FAILURES:
        for f in failures:
            print("  -", f)
        print("退出码 1：失败数超过上限")
        return 1

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"已写入 {OUT_JSONL.relative_to(PROJECT_ROOT)}（{len(records)} 行）")

    # 抽样必须随机（任务书 §四.5"随机抽 2 条"）：确定性取前 2 条会系统性
    # 漏掉列表尾部模板的缺陷——2026-11-08 审核：污染最重的蔡甸恰好从未被抽中。
    print("\n随机抽样（2 条，人工核对）：")
    sample = random.sample(records, min(2, len(records)))
    for rec in sample:
        print(f"  [{rec['region']}] {rec['title']}")
        print(f"    日期：{rec['publish_date'] or '（空）'}  是否政策原文：{rec['is_policy_text']}")
        print(f"    正文前 200 字：{rec['content'][:200]!r}")
        print(f"    正文后 120 字：{rec['content'][-120:]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
