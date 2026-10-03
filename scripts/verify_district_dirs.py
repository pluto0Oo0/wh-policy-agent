"""P0-3 验证：13 个区是否都有「保障性住房政策」信息公开目录。

背景（wb 的发现）：
    汉阳区有个标准化目录 `/zwgk_XX/xxgkml/ggzypz/zfbz1/bzxzfzc/`，
    一篇就同时含三套规则（老政策 + 新政策 + 区级加码）。

本脚本逐个区试，回答：
    ① 这个路径是否每个区都存在
    ② 内容是否对口（用文号做硬指标，不用关键词命中率）
    ③ 能凑多少条

用法：python scripts/verify_district_dirs.py
"""

import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 13 个区的域名（SPEC §2.5 实测确认过的表）
DISTRICTS = {
    "江岸": "jiangan.gov.cn",
    "江汉": "jianghan.gov.cn",
    "硚口": "qiaokou.gov.cn",
    "汉阳": "hanyang.gov.cn",
    "武昌": "wuchang.gov.cn",
    "青山": "qingshan.gov.cn",
    "洪山": "hongshan.gov.cn",
    "东西湖": "dxh.gov.cn",
    "蔡甸": "caidian.gov.cn",
    "江夏": "jiangxia.gov.cn",
    "黄陂": "huangpi.gov.cn",
    "新洲": "whxinzhou.gov.cn",
    "东湖高新": "wehdz.gov.cn",
}

# 要试的路径模板 —— 汉阳实测可用的那个 + 几个变体
PATH_TEMPLATES = [
    "/zwgk_38/xxgkml/ggzypz/zfbz1/bzxzfzc/",  # 汉阳实测可用
    "/zwgk/xxgkml/ggzypz/zfbz1/bzxzfzc/",     # 去掉区号
    "/xxgkml/ggzypz/zfbz1/bzxzfzc/",
]

# 硬指标：两个关键文号（布尔判断）
HARD_TARGETS = ["武房规", "武政办〔2022〕78"]

# 口径：保障性住房相关词
REL_WORDS = ["保障性住房", "人才租赁房", "安居", "租金", "住房补贴"]


def try_url(url: str) -> tuple[int, str, str]:
    """返回 (状态码, 长度, 文本)。失败返回 (0, 0, 错误)。"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.encoding = "utf-8"
        return r.status_code, len(r.text), r.text
    except Exception as e:
        return 0, 0, f"{type(e).__name__}: {e}"


print("=" * 78)
print("P0-3 · 逐个区试「保障性住房政策」目录")
print("=" * 78)
print()

found_dirs = []

for dist, domain in DISTRICTS.items():
    hit = None

    for tpl in PATH_TEMPLATES:
        url = f"https://www.{domain}{tpl}"
        code, size, text = try_url(url)

        if code == 200 and size > 3000:
            hit = (url, size, text)
            break

        time.sleep(0.3)  # 礼貌

    if not hit:
        print(f"  ❌ {dist:<8} 三个路径模板都没命中")
        continue

    url, size, text = hit

    # ── 内容检查 ──────────────────────────────────────────
    # 硬指标（布尔）
    hard = [t for t in HARD_TARGETS if t in text]

    # 相关词（只作参考，不作判断依据）
    rel = [w for w in REL_WORDS if w in text]

    # 条目数（粗略：数 .shtml 链接）
    links = len(re.findall(r't\d{8}_\d+\.shtml', text))

    found_dirs.append(
        {"dist": dist, "url": url, "size": size, "hard": hard, "rel": rel, "links": links}
    )

    h_mark = "✅" if hard else "⚠️"
    print(f"  ✅ {dist:<8} {size:>7,} 字符 | 条目 {links:>3} | 硬指标{h_mark}{hard or '无'}")
    print(f"      {url}")
    if rel:
        print(f"      相关词：{rel}")

    time.sleep(0.5)

# ── 汇总 ──────────────────────────────────────────────────
print()
print("=" * 78)
print("汇总")
print("=" * 78)
print()

if not found_dirs:
    print("❌ 一个区都没命中 —— 三个路径模板都不对，需要重新找规律")
    sys.exit(1)

with_hard = [d for d in found_dirs if d["hard"]]
print(f"  命中目录：{len(found_dirs)}/13 个区")
print(f"  其中硬指标（武房规 / 武政办〔2022〕78）命中：{len(with_hard)} 个")
print()

if with_hard:
    print("  ✅ 能作为主源的区：")
    for d in with_hard:
        print(f"     {d['dist']}（{d['links']} 条）")
else:
    print("  ⚠️  没有任何区的目录里出现两个关键文号")
    print("     → 注意 wb 的教训：这可能是「翻页/路径不对」，不一定是「源不对」")
