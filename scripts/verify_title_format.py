"""核实：详情页 <title> 是否统一带站点后缀。

背景（wb 的方案 A）：
    为了验证"列表页抽出的标题"是对的，要用**第二条独立路径**去比对——
    直接打开详情页，读它 <head> 里的 <title>。
    两条路径物理上不可能互相抄（一个在列表页 script，一个在详情页 head）。

本脚本回答：详情页 <title> 长什么样？要不要先剥站点后缀？
    如果带后缀（如 "……的通知 - 武汉市人民政府门户网站"），
    比对前必须先剥掉，否则会全部假失败。

用法：python scripts/verify_title_format.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# 取 3 个不同栏目的详情页 —— 看 <title> 格式是否一致
SAMPLES = [
    ("bgtwj", "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/bgtwj/202608/t20260805_2830143.shtml"),
    ("szfwj", "https://www.wuhan.gov.cn/zwgk/xxgk/zfwj/szfwj/202609/t20260917_2849324.shtml"),
    ("jzwh（死源，但页面还在）",
     "https://www.wuhan.gov.cn/ztzl/23zt/jzwh/zcqd/zf/202308/t20230802_2241617.shtml"),
]

# 可能的后缀分隔符
SEPARATORS = [" - ", " — ", "－", "_", "|", "｜"]


def fetch(url: str, max_retry: int = 3) -> str:
    """带重试的请求（实测遇到过 SSLError 抖动）。"""
    last = None
    for i in range(1, max_retry + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.encoding = "utf-8"
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last = e
            if i < max_retry:
                import time

                time.sleep(2 ** i)
    raise last


print("=" * 76)
print("核实：详情页 <title> 的格式")
print("=" * 76)
print()

results = []

for label, url in SAMPLES:
    print(f"── {label}")
    try:
        html = fetch(url)
    except Exception as e:
        print(f"   ❌ 抓取失败：{type(e).__name__}: {e}")
        print()
        continue

    # 提取 <title>
    m = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if not m:
        print("   ❌ 未找到 <title> 标签")
        print()
        continue

    raw_title = m.group(1).strip()
    # 标题里的实体字符
    raw_title = (
        raw_title.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    )

    # 找分隔符
    suffix = None
    core = raw_title
    for sep in SEPARATORS:
        if sep in raw_title:
            idx = raw_title.rfind(sep)
            suffix = raw_title[idx:]
            core = raw_title[:idx].strip()
            break

    results.append({"label": label, "raw": raw_title, "core": core, "suffix": suffix})

    print(f"   原始 <title>：{raw_title}")
    print(f"   剥后缀后    ：{core}")
    print(f"   后缀        ：{suffix!r}")
    print(f"   长度        ：{len(raw_title)} → {len(core)}")
    print()

# ── 汇总判断 ──────────────────────────────────────────────
print("=" * 76)
print("判断")
print("=" * 76)
print()

# ⚠️ 必须先检查"有没有抓到东西" —— 实测踩过：
#    第一版没做这个检查，3 个样本全部抓取失败时，
#    代码照样走到下面，输出了"✅ 无后缀"这个**完全错误**的结论。
#    这是"程序不报错但结果是错的"的教科书案例。
if not results:
    print("❌ 没有一个样本抓取成功 —— 无法得出结论。")
    print()
    print("   常见原因（按概率）：")
    print("   ① 代理/VPN 仍在接管 DNS（解析结果会是 28.0.0.x 这种假 IP）")
    print("   ② 网络瞬时故障")
    print()
    print("   排查：先跑 `python -c \"import socket; print(socket.gethostbyname('www.wuhan.gov.cn'))\"`")
    print("         如果返回 28.0.0.x，说明代理在拦截，需先关闭")
    sys.exit(1)

suffixes = [r["suffix"] for r in results if r["suffix"]]
if len(suffixes) == len(results) and len(set(suffixes)) == 1:
    print(f"✅ 所有样本后缀一致：{suffixes[0]!r}")
    print("   → 方案 A 可以安全地用 rfind(分隔符) 剥后缀")
elif suffixes:
    print(f"⚠️  后缀不完全一致：{set(suffixes)}")
    print("   → 剥后缀逻辑要能处理多种分隔符")
else:
    print("✅ 无后缀 —— 详情页 <title> 就是标题本身")
    print("   → 方案 A 可直接比对，不需要剥")

print()
print(f"（本次成功样本数：{len(results)}/3）")
print("注意：这是 3 个样本，不是全量。实际实现时应")
print("      ① 先跑几条看输出  ② 再定「要不要剥」的判断逻辑  ③ 别一上来就写死")
