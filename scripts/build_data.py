"""建数据：抓取政策列表 → 落盘。

用法：
    python scripts/build_data.py --pages 3           # 两个源各抓 3 页
    python scripts/build_data.py --pages 1 --source bgtwj

自检要求（见 docs/抓取自检清单.md）：
  1. 每页断言条数
  2. 抓完打印年份分布，检查新鲜度
  3. 抽 2 条完整内容人工看
  4. 原始 HTML 落盘
  5. 未知字段不猜 —— 缺日期就留空，不编造
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# 让脚本能 import 到 src 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest import crawl, storage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIST_JSONL = PROJECT_ROOT / "data" / "processed" / "list.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取武汉市政府政策列表")
    parser.add_argument("--pages", type=int, default=3, help="每个源抓几页（默认 3）")
    parser.add_argument(
        "--source",
        default=None,
        help=f"只抓指定源，可选：{list(crawl.SOURCES)}；不传则全抓",
    )
    args = parser.parse_args()

    sources = [args.source] if args.source else list(crawl.SOURCES)

    for key in sources:
        if key not in crawl.SOURCES:
            print(f"❌ 未知源：{key}，可选：{list(crawl.SOURCES)}")
            return 1

    print("=" * 72)
    print(f"抓取政策列表 | 源：{sources} | 每源 {args.pages} 页")
    print("=" * 72)
    print()

    all_records = []
    total_new = 0
    total_dup = 0

    for key in sources:
        name = crawl.SOURCES[key]["name"]
        print(f"── {name} ──")

        for page in range(1, args.pages + 1):
            url = crawl.page_url(key, page)

            # 抓 + 解析（内部已含条数断言，失败会抛 CrawlError）
            html = crawl.fetch_html(url)
            records = crawl.parse_list(html, url)

            if len(records) < crawl.MIN_RECORDS_PER_PAGE:
                print(
                    f"  ❌ 第 {page} 页只抽到 {len(records)} 条"
                    f"（预期 ≥{crawl.MIN_RECORDS_PER_PAGE}）"
                )
                print(f"     地址：{url}")
                return 1

            # 原始 HTML 落盘
            raw_path = storage.save_raw_html(html, key, page)

            for r in records:
                r["source"] = key
                r["page"] = page

            all_records.extend(records)
            print(f"  第 {page} 页 → {len(records)} 条  (原始HTML: {raw_path.name})")

            if page < args.pages:
                import time

                time.sleep(crawl.REQUEST_DELAY)

        print()

    # ── 落盘（幂等）────────────────────────────────────────
    new_count, dup_count = storage.append_records(all_records, LIST_JSONL)
    total_new += new_count
    total_dup += dup_count

    print("=" * 72)
    print(f"本次抓到 {len(all_records)} 条 | 新增 {new_count} 条 | 已存在跳过 {dup_count} 条")
    print(f"累计文件：{LIST_JSONL}")
    print("=" * 72)
    print()

    # ── 自检 1：时间戳年份分布（新鲜度）────────────────────
    years = []
    for r in all_records:
        m = re.search(r"t(20\d{2})\d{4}_", r["path"])
        if m:
            years.append(m.group(1))

    if years:
        dist = Counter(years)
        print("自检 · 年份分布：")
        for y, n in sorted(dist.items(), reverse=True):
            print(f"   {y}: {n} 条")

        newest = int(max(dist))
        if newest < 2025:
            print(f"   ⚠️  警告：最新内容 {newest} 年，距今超过 1 年，疑似死数据")
        else:
            print(f"   ✅ 新鲜度合格（最新 {newest} 年）")
    else:
        print("⚠️  自检 · 未能从 URL 提取年份，无法判断新鲜度")
    print()

    # ── 自检 2：抽 2 条完整打印，人工确认 ─────────────────
    print("自检 · 抽样 2 条完整记录（人工确认内容是否正确）：")
    for i, r in enumerate(all_records[:2], 1):
        print(f"   ── 样本 {i} ──")
        print(f"   来源：{crawl.SOURCES[r['source']]['name']}  第 {r['page']} 页")
        print(f"   标题：{r['title']}")
        print(f"   链接：{r['url']}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
