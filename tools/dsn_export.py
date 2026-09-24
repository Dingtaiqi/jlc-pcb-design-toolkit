# -*- coding: utf-8 -*-
"""dsn_export.py —— 从 EasyEDA Pro 导出 Specctra DSN，喂给 Freerouting

为什么要专门写一个导出器（踩过的坑都在这）：
  1) ★ 层名补丁：EasyEDA 头部声明层名 TopLayer/BottomLayer，但走线却写成 (path 1 …)/(path 2 …)。
     FR 按数字找不到层名 → 把已有铜全丢掉（等于从头布线）。导出器自动补丁成层名。
  2) DSN 有几 MB，桥接单次响应放不下 → 用 window.__dsn 暂存 + substr 分块取回（50KB/块）。
  3) 导出后做体检：层定义 / 走线段数 / 元件与放置数 / 板框点数，异常早发现。

用法:
    python tools/dsn_export.py                        # 默认写 work/board.dsn
    python tools/dsn_export.py --out work/board.dsn
    python tools/dsn_export.py --no-patch             # 只看原始导出(不补层名), 用于对比
    python tools/dsn_export.py --check-only           # 只体检不落盘

注意：DSN 里没有禁布区（挖空/天线净空/电机圆）。正式跑 FR 之前，确认这些禁区已经在
DSN 或规则里体现，否则 FR 会往禁区铺线。
"""
import io, json, os, re, sys, urllib.request

BRIDGE = os.environ.get("EDA_BRIDGE", "http://localhost:49620/execute")
CHUNK = 50000


def q(js, timeout=300, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(BRIDGE, data=json.dumps({"code": js}).encode(),
                                         headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
            if r.get("success"):
                return r.get("result")
            last = str(r)[:200]
        except Exception as e:
            last = str(e)[:200]
    raise RuntimeError("桥接调用失败: " + str(last))


def main():
    args = sys.argv[1:]
    out = os.path.join("work", "board.dsn")
    patch, check_only = True, False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args): out = args[i + 1]; i += 2; continue
        if a == "--no-patch": patch = False; i += 1; continue
        if a == "--check-only": check_only = True; i += 1; continue
        print("未知参数:", a); print(__doc__); return 1

    # ---- 1) 拿原始 DSN（分块） ----
    n = int(q("const f=await eda.pcb_ManufactureData.getDsnFile(); const t=await f.text();"
              " window.__dsn=t; return String(t.length);"))
    print("DSN 原始长度:", n, "字符")
    parts = [q("return window.__dsn.substr(%d,%d);" % (i, CHUNK)) for i in range(0, n, CHUNK)]
    dsn = "".join(parts)
    if len(dsn) != n:
        print("!! 分块取回长度不一致: %d != %d" % (len(dsn), n))

    # ---- 2) 体检 ----
    layers = sorted(set(re.findall(r"\(layer\s+([A-Za-z0-9_]+)", dsn)))
    wires = dsn.count("(wire")
    paths_num = len(re.findall(r"\(path\s+\d+\s", dsn))
    paths_name = len(re.findall(r"\(path\s+[A-Za-z_]\w*\s", dsn))
    comps = dsn.count("(component")
    places = dsn.count("(place")
    outline = re.search(r"\(boundary\s*\(path\s+[^\s]+\s+([\d\s.\-]+)\)", dsn)
    outline_pts = len(re.findall(r"[\d.\-]+", outline.group(1))) // 2 if outline else -1
    print("层定义:", layers[:12])
    print("走线段(wire):", wires, " | (path 数字层):", paths_num, " | (path 层名):", paths_name)
    print("元件:", comps, " 放置:", places, " 板框顶点数:", outline_pts)
    if paths_num and not paths_name:
        print("★ 检测到 (path 数字层) —— 必须补层名，否则 Freerouting 会丢掉已有铜")
    if outline_pts >= 0 and outline_pts < 8:
        print("!! 板框只有 %d 个顶点，可能退化成自交多边形，需补点重排" % outline_pts)

    # ---- 3) 层名补丁 ----
    if patch and paths_num:
        before = paths_num
        dsn2 = re.sub(r"\(path\s+1\s", "(path TopLayer ", dsn)
        dsn2 = re.sub(r"\(path\s+2\s", "(path BottomLayer ", dsn2)
        now = len(re.findall(r"\(path\s+[A-Za-z_]\w*\s", dsn2))
        print("层名补丁: %d 条数字层 → 层名（现在层名 path = %d）" % (before, now))
        dsn = dsn2

    if check_only:
        print("(--check-only: 不落盘)")
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    io.open(out, "w", encoding="utf-8", newline="\n").write(dsn)
    print("已写出:", out, len(dsn), "字符")
    print("\n下一步:")
    print("  python tools/freerouting.py run --dsn %s --ses work/board.ses --passes 30 --oi 0.25 --poll" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
