#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
元件摆放求解器  (EasyEDA Pro PCB, Python + OR-Tools CP-SAT)
==========================================================
纯离线任务: 只读 comps3.json / live.json / parts_now.json, 只写 placement_new.json。
不联网、不调用任何 MCP/HTTP 接口、不修改输入文件。

用法:
    python place_cpsat.py [超时秒数] [逃逸模式]   # 默认 150 秒, 逃逸模式 m/u (m=含可动件互斥, 默认)

输出 placement_new.json: {"moves": {位号: [dx_mm, dy_mm]}, "rot": {}, "before": N, "after": N}
  moves 只包含需要移动的元件(相对当前位置); rot 为空 => 旋转未改变(R6)

硬约束 (R1-R7)
  R1 任意两个不同元件的焊盘中心距 >= 70mil = 1.778mm (同网络同样要求, 无条件)
  R2 任意两个不同元件本体矩形间隙 >= 0.20mm
  R3 微动开关(封装名含 3JWD-DBHD)本体 13.5x6.4 不得被任何其它元件本体侵占
  R4 禁区: 滚轮挖槽矩形 / 天线净空矩形 / 电机圆(仅顶层 l==1) / 板框
  R5 本体(含焊盘包络) 距板框边界 >= 2.5mm   (CN1 USB1 H1 H2 H5 LED1 U7 豁免)
  R6 旋转保持 0/90/180/270 (本脚本不改旋转, 仅在模型里按当前角度锁死)
  R7 可动件最终坐标落在 0.1mm 栅格上

不可移动(绝对锁死): SW1..SW13 H1 H2 H5 CN1 USB1 U5 U7 LED1
                    + 天线匹配网络 L7 C65 C66 C67 C68 L6 R28

建模要点
  * 旋转只有 90 度倍数 => 本体与焊盘包络都是轴对齐矩形, 全部用解析几何(不需 shapely)
  * 决策变量 = 每个可动件在 0.1mm 绝对栅格上的整数索引 (i,j)
  * 单件约束 (R4/R5 + 与锁定件的 R1/R2) => 预计算合法栅格掩码, 用"矩形精确覆盖+布尔或"编码
  * 成对约束 (可动-可动): R2/R3 用 4 向分离析取(精确); R1 用 (di,dj) 差值禁止表(栅格上精确)
  * 目标分两阶段: ①最小总位移 ②位移锁定后最大化美观(成行成列/聚簇/线长)
  * 兜底: 窗口逐级放大重解(保留位移最小的可行解); 全部失败则输出空位移 + 残余违规清单

已知前提/局限
  * 焊盘归属: 用 parts_now.json 的"每元件引脚网络多重集"(与位置无关的拓扑)做硬约束,
    在 live.json 的 650 个焊盘上按网络做 Hungarian 运输分配; 分配后用"同封装局部焊盘布局
    一致性"自检, 异常会打印出来。
  * 锁定件若本身违反规则(例如天线匹配网络焊盘互相太近、结构件落在禁区/贴板边),
    其残差不可通过移动其它元件消除, 会单独归类为"仅由锁定件导致的不可解残差"。
  * 目标量化为 0.01mm, 与真实浮点坐标的差异 <= 0.01mm/件; 所有 R1-R7 判定另有独立浮点检查。
"""

import collections
import io
import json
import math
import os
import re
import sys
import time

T0 = time.time()
BASE = os.path.dirname(os.path.abspath(__file__))
MIL = 0.0254
PAD_CC = 70 * MIL                     # 1.778 mm   R1
BODY_CLEAR = 0.20                     # R2
EDGE_CLEAR = 2.50                     # R5
MARGIN = 0.02                         # 内部量化安全余量 (<0.015mm 量化误差)
SW_L, SW_W = 13.5, 6.4                # R3 微动本体
BX0, BX1, BY0, BY1 = 0.0, 90.0, -7.20, 82.80       # 板框
CUT = (1.14, 50.80, 21.34, 75.44)                  # 滚轮挖槽
ANT = (84.6, 31.0, 90.5, 39.0)                     # 天线净空
MOT_X, MOT_Y, MOT_R = 11.56, 27.75, 9.51           # 电机区(仅顶层)

LOCK = set("SW1 SW2 SW3 SW4 SW5 SW6 SW7 SW8 SW9 SW10 SW11 SW12 SW13 "
           "H1 H2 H5 CN1 USB1 U5 U7 LED1".split())
ANTNET = set("L7 C65 C66 C67 C68 L6 R28".split())
FIXED = LOCK | ANTNET
NOEDGE = set("CN1 USB1 H1 H2 H5 LED1 U7".split())

UN = 0.01        # 内部长度单位 = 0.01mm
GRID = 10        # R7 栅格 = 0.1mm = 10 单位

TBL = {"C0603": (1.6, 0.9), "R0603": (1.6, 0.9), "L0603": (1.6, 0.9), "R1206": (3.2, 1.7),
       "SMA_L4.3-W2.6-LS5.0-BI": (4.3, 2.6), "HDR-TH_3P-P2.54-V-F": (7.7, 2.6),
       "HDR-TH_2P-P2.54-V-F": (5.1, 2.6), "HDR-TH_5P-P2.54-V-M": (12.7, 2.6),
       "HDR-TH_10P-P2.54-V-F": (25.4, 2.6), "OPTO-TH_3P_PT2559B": (5.2, 4.0),
       "AO3401A_SOT-23-3": (3.0, 1.5), "ANT-SMD_L3.1-W1.6": (3.1, 1.6),
       "Key_SMD_3x4x2": (3.0, 4.0), "SW-TH_SHOU-HAN_3JWD-DBHD-13.5": (13.5, 6.4),
       "USB_TYPE-C-16P": (9.0, 7.3), "LED-TH_L4.5-W2.25-P2.54-FD": (4.5, 2.3),
       "CONN-TH_XT30PW-M": (10.0, 7.0)}


def size(fp):
    """封装名 -> 本体 (长L, 宽W) mm  [沿用 place_fix70b.py 的尺寸表]"""
    if fp in TBL:
        return TBL[fp]
    m = re.search(r"_L([0-9.]+)-W([0-9.]+)", fp) or re.search(r"L([0-9.]+)-W([0-9.]+)", fp)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    if re.search(r"^([A-Z]+)-(\d+)", fp):
        return (6.0, 5.0)
    return (2.0, 1.5)


# ======================================================================= 数据
def _rcap(fp, L, W):
    """焊盘相对元件原点的合理半径上限(mm), 用于焊盘->元件分配"""
    m = re.search(r"LS([0-9.]+)", fp)
    ls = float(m.group(1)) if m else 0.0
    return max(ls / 2 + 1.2, max(L, W) / 2 + 3.0)


def assign_pads(comps, pads, demand, verbose=True):
    """焊盘 -> 元件 分配。
    以 parts_now.json 的"每元件引脚网络多重集"(与位置无关的拓扑)为硬约束,
    每个网络内部做一次运输问题(Hungarian): 代价 = 焊盘中心距, 超半径上限加惩罚。
    返回 {d: [pad index...]} 或 (None, 诊断), 诊断见第二个返回值。
    """
    byD = {c["d"]: c for c in comps}
    note = []
    assign = {c["d"]: [] for c in comps}
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
    except Exception as e:
        return None, ["无 numpy/scipy (%s), 退回贪心分配" % e]
    bynet = collections.defaultdict(list)
    for i, p in enumerate(pads):
        bynet[p["net"]].append(i)
    for net, idxs in sorted(bynet.items()):
        dem = [(c["d"], demand[c["d"]].get(net, 0)) for c in comps if demand[c["d"]].get(net, 0) > 0]
        if sum(k for _, k in dem) != len(idxs):
            return None, ["网络 %s: 焊盘 %d 个 / 需求 %d 个不一致, 退回贪心"
                          % (net, len(idxs), sum(k for _, k in dem))]
        cols = [b for b, (d, k) in enumerate(dem) for _ in range(k)]
        C = np.zeros((len(idxs), len(cols)))
        for a, pi in enumerate(idxs):
            px, py = pads[pi]["x"], pads[pi]["y"]
            for b in range(len(cols)):
                d = dem[cols[b]][0]
                cc = byD[d]
                dist = math.hypot(px - cc["x"], py - cc["y"])
                C[a, b] = dist + (1000.0 if dist > cc["rcap"] else 0.0)
        r, c2 = linear_sum_assignment(C)
        for a, b in zip(r, c2):
            d = dem[cols[b]][0]
            assign[d].append(idxs[a])
            if C[a, b] >= 1000.0:
                note.append("半径超限: %s <- pad%d (距离 %.2f > rcap %.2f)"
                            % (d, idxs[a],
                               math.hypot(pads[idxs[a]]["x"] - byD[d]["x"], pads[idxs[a]]["y"] - byD[d]["y"]),
                               byD[d]["rcap"]))
    for c in comps:
        lst = assign[c["d"]]
        if len(lst) != c["np"]:
            note.append("%s 焊盘数 %d != 引脚数 %d" % (c["d"], len(lst), c["np"]))
        if len(set(lst)) != len(lst):
            note.append("%s 焊盘重复" % c["d"])
        c["pads"] = sorted(lst)
    return assign, note


def load_data(verbose=True):
    comps3 = json.load(io.open(os.path.join(BASE, "comps3.json"), encoding="utf-8"))
    live = json.load(io.open(os.path.join(BASE, "live.json"), encoding="utf-8"))

    pads = []
    for p in live["pads"]:
        net, lay, x, y, ps, hs, num, rot = p
        w = h = 0.4
        try:
            a = ps.split(",")
            if ps.startswith("ROUND") and len(a) >= 2:
                w = h = max(0.4, float(a[1]) * MIL)
            elif len(a) >= 3:
                w = max(0.4, float(a[1]) * MIL)
                h = max(0.4, float(a[2]) * MIL)
        except Exception:
            pass
        try:
            prot = float(rot)
        except Exception:
            prot = 0.0
        pads.append({"net": net or "", "lay": lay, "x": x, "y": y, "num": num,
                     "w": w, "h": h, "prot": prot, "comp": None})

    comps = []
    for c in comps3:
        L, W = size(c["f"])
        comps.append({"d": c["d"], "f": c["f"], "x": c["x"], "y": c["y"], "l": c["l"],
                      "rot": c["r"] % 360, "L": L, "W": W, "np": len(c["p"]), "pads": [],
                      "rcap": _rcap(c["f"], L, W)})
    byD = {c["d"]: c for c in comps}

    # ---- 每个元件的引脚网络多重集 (parts_now.json 的拓扑, 与位置无关) ----
    demand, src, diag = None, "贪心最近分配", []
    pn = os.path.join(BASE, "parts_now.json")
    if os.path.exists(pn):
        try:
            P = json.load(io.open(pn, encoding="utf-8"))
            if {p["d"] for p in P} == set(byD):
                dem = {p["d"]: collections.Counter(n or "" for _, _, n in p["pins"]) for p in P}
                tot_d = collections.Counter()
                for d, cnt in dem.items():
                    tot_d.update(cnt)
                tot_l = collections.Counter(p["net"] for p in pads)
                if tot_d == tot_l and sum(len(p["pins"]) for p in P) == len(pads):
                    demand = dem
                    src = "按网络运输分配 Hungarian (parts_now 拓扑)"
                else:
                    diag.append("parts_now 网络多重集与 live.json 不符, 退回贪心")
        except Exception as e:
            diag.append("parts_now 不可用: %s" % e)

    if demand is not None:
        a2, note = assign_pads(comps, pads, demand)
        diag += note
        if a2 is None:
            demand = None
    if demand is None:
        pairs = []
        for ci, c in enumerate(comps):
            for pi, p in enumerate(pads):
                dd = math.hypot(p["x"] - c["x"], p["y"] - c["y"])
                if dd < c["rcap"]:
                    pairs.append((dd, ci, pi))
        pairs.sort()
        cnt = [0] * len(comps)
        for dd, ci, pi in pairs:
            if pads[pi]["comp"] is None and cnt[ci] < comps[ci]["np"]:
                pads[pi]["comp"] = ci
                cnt[ci] += 1
        for pi, p in enumerate(pads):
            if p["comp"] is None:
                p["comp"] = min(range(len(comps)),
                                key=lambda k: math.hypot(p["x"] - comps[k]["x"], p["y"] - comps[k]["y"]))
        for ci, c in enumerate(comps):
            c["pads"] = sorted(i for i in range(len(pads)) if pads[i]["comp"] == ci)
    for c in comps:
        for i in c["pads"]:
            pads[i]["comp"] = c["d"]

    # ---- 局部几何 ----
    for c in comps:
        aa = (c["rot"] % 180) == 0
        c["hx"] = (c["L"] if aa else c["W"]) / 2.0
        c["hy"] = (c["W"] if aa else c["L"]) / 2.0
        c["sw"] = "3JWD-DBHD" in c["f"]
        if c["sw"]:
            c["hx"], c["hy"] = (SW_L / 2, SW_W / 2) if aa else (SW_W / 2, SW_L / 2)
        rel, e = [], None
        for i in c["pads"]:
            p = pads[i]
            ux, uy = p["x"] - c["x"], p["y"] - c["y"]
            pr = math.degrees(p["prot"]) + c["rot"]
            hw, hh = (p["w"] / 2, p["h"] / 2) if abs(pr % 180) < 1e-6 else (p["h"] / 2, p["w"] / 2)
            rel.append((ux, uy))
            b = (ux - hw, uy - hh, ux + hw, uy + hh)
            e = b if e is None else (min(e[0], b[0]), min(e[1], b[1]), max(e[2], b[2]), max(e[3], b[3]))
        c["rel"] = rel
        c["penv"] = e if e else (-c["hx"], -c["hy"], c["hx"], c["hy"])
        c["ex"] = (min(-c["hx"], c["penv"][0]), max(c["hx"], c["penv"][2]),
                   min(-c["hy"], c["penv"][1]), max(c["hy"], c["penv"][3]))
        c["fix"] = c["d"] in FIXED

    # ---- 数据自检: 同封装+同引脚数的"局部坐标系"焊盘布局应完全一致 ----
    tmpl = collections.defaultdict(list)
    for c in comps:
        r = math.radians(-c["rot"])
        ca, sa = math.cos(r), math.sin(r)
        loc = tuple(sorted((round(ca * ux - sa * uy, 2), round(sa * ux + ca * uy, 2))
                           for (ux, uy) in c["rel"]))
        tmpl[(c["f"], len(c["rel"]))].append((loc, c["d"]))
    odd = 0
    for key, lst in tmpl.items():
        cnt = collections.Counter(l for l, _ in lst)
        if len(cnt) > 1:
            mode, n = cnt.most_common(1)[0]
            who = [d for l, d in lst if l != mode]
            odd += len(who)
            diag.append("封装 %s 局部焊盘布局不一致: 多数 %d 件一致, 异常 %d 件 %s"
                        % (key[0], n, len(who), who[:8]))
    if verbose:
        print("[数据] %d 元件 (%d 锁定) / %d 焊盘 ; 归属: %s"
              % (len(comps), len(FIXED), len(pads), src), flush=True)
        print("[数据] 焊盘布局自检: %d 组(封装/引脚数), 布局异常元件 %d" % (len(tmpl), odd), flush=True)
        for s in diag:
            print("[数据] 注: " + s, flush=True)
    return comps, pads


# ======================================================================= 规则检查
def body(c, x=None, y=None):
    x = c["x"] if x is None else x
    y = c["y"] if y is None else y
    return (x - c["hx"], y - c["hy"], x + c["hx"], y + c["hy"])


def check(comps, pads, pos, tag=None):
    """R1-R7 检查(纯浮点精确几何)。pos: {designator: (x,y)}"""
    V = {"R1": [], "R2": [], "R3": [], "R4": [], "R5": [], "R7": []}

    def P(c):
        return pos.get(c["d"], (c["x"], c["y"]))

    pp = []
    for c in comps:
        x, y = P(c)
        for (ux, uy) in c["rel"]:
            pp.append((x + ux, y + uy, c["d"]))
    cell = collections.defaultdict(list)
    for i, (x, y, d) in enumerate(pp):
        cell[(int(math.floor(x / 2.0)), int(math.floor(y / 2.0)))].append(i)
    for k, lst in cell.items():
        near = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                near.extend(cell.get((k[0] + dx, k[1] + dy), ()))
        for i in lst:
            a = pp[i]
            for j in near:
                if j <= i:
                    continue
                b = pp[j]
                if a[2] == b[2]:
                    continue
                dd = math.hypot(a[0] - b[0], a[1] - b[1])
                if dd < PAD_CC:
                    V["R1"].append((dd, a[2], b[2], (a[0], a[1]), (b[0], b[1])))

    n = len(comps)
    for i in range(n):
        a = comps[i]
        ax, ay = P(a)
        for j in range(i + 1, n):
            b = comps[j]
            bx, by = P(b)
            dx, dy = abs(ax - bx), abs(ay - by)
            gx, gy = a["hx"] + b["hx"], a["hy"] + b["hy"]
            if dx < gx + BODY_CLEAR and dy < gy + BODY_CLEAR:
                if dx >= gx and dy >= gy:
                    sep = math.hypot(dx - gx, dy - gy)
                elif dx >= gx:
                    sep = dx - gx
                elif dy >= gy:
                    sep = dy - gy
                else:
                    sep = -min(gx - dx, gy - dy)
                V["R2"].append((sep, a["d"], b["d"]))
                if (a["sw"] or b["sw"]) and dx < gx and dy < gy:
                    V["R3"].append((a["d"] if a["sw"] else b["d"], b["d"] if a["sw"] else a["d"]))

    for c in comps:
        x, y = P(c)
        bx0, by0, bx1, by1 = body(c, x, y)
        for nm, (rx0, ry0, rx1, ry1) in (("滚轮挖槽", CUT), ("天线净空", ANT)):
            if bx1 > rx0 and bx0 < rx1 and by1 > ry0 and by0 < ry1:
                V["R4"].append((nm, c["d"]))
        if bx1 < BX0 or bx0 > BX1 or by1 < BY0 or by0 > BY1:
            V["R4"].append(("板框外", c["d"]))
        if c["l"] == 1:
            ddx = max(bx0 - MOT_X, 0.0, MOT_X - bx1)
            ddy = max(by0 - MOT_Y, 0.0, MOT_Y - by1)
            if math.hypot(ddx, ddy) < MOT_R:
                V["R4"].append(("电机区", c["d"]))
        if c["d"] not in NOEDGE:
            e = min(bx0 - BX0, BX1 - bx1, by0 - BY0, BY1 - by1)
            if e < EDGE_CLEAR:
                V["R5"].append((e, c["d"]))
        if not c["fix"] and (abs(x / 0.1 - round(x / 0.1)) > 1e-6 or abs(y / 0.1 - round(y / 0.1)) > 1e-6):
            V["R7"].append(c["d"])
    if tag:
        print("[%s] 违规 %d  (R1=%d R2=%d R3=%d R4=%d R5=%d R7=%d)"
              % (tag, sum(len(v) for v in V.values()), len(V["R1"]), len(V["R2"]),
                 len(V["R3"]), len(V["R4"]), len(V["R5"]), len(V["R7"])), flush=True)
    return V


def fmt_viol(V):
    out = []
    for dd, a, b, pa, pb in sorted(V["R1"]):
        out.append(("R1 焊盘中心距 %.3fmm < 1.778" % dd, "%s <-> %s" % (a, b), a, b))
    for g, a, b in sorted(V["R2"]):
        out.append(("R2 本体间隙 %.3fmm < 0.20" % g, "%s <-> %s" % (a, b), a, b))
    for a, b in V["R3"]:
        out.append(("R3 微动本体被侵占", "%s <-> %s" % (a, b), a, b))
    for nm, d in V["R4"]:
        out.append(("R4 禁区[%s]" % nm, d, d, ""))
    for e, d in sorted(V["R5"]):
        out.append(("R5 板边距 %.2fmm < 2.5" % e, d, d, ""))
    for d in V["R7"]:
        out.append(("R7 不在 0.1mm 栅格", d, d, ""))
    return out


# ======================================================================= 求解
AESC = "m"          # 逃逸点搜索模式: "m" 含可动件互斥 / "u" 仅单件+锁定件


def solve(comps, pads, budget, verbose=True, max_rounds=2):
    """CP-SAT 摆放求解。返回 (pos, 诊断dict)。
    pos: {可动件 designator: (x, y)}; None 表示无解。"""
    from ortools.sat.python import cp_model
    import numpy as np

    mov = [c for c in comps if not c["fix"]]
    fix = [c for c in comps if c["fix"]]
    diag = {}
    if verbose:
        print("[求解] 可动 %d / 锁定 %d, 时间预算 %.0fs" % (len(mov), len(fix), budget), flush=True)

    D0 = int(round((PAD_CC + MARGIN) / UN))            # R1 下限(0.01mm 单位)
    fixnear = {c["d"]: [f for f in fix if abs(f["x"] - c["x"]) < 40 and abs(f["y"] - c["y"]) < 40]
               for c in mov}

    # ---------------------------------------------------------------- 单件合法性
    def unary(c, X, Y):
        """R4/R5 + 与全部锁定件的 R1/R2 合法掩码(X,Y 单位 mm, 可广播)"""
        elo, ehi, flo, fhi = c["ex"]
        ok = np.ones(np.broadcast(X, Y).shape, dtype=bool)
        if c["d"] not in NOEDGE:
            ok &= (X + elo >= BX0 + EDGE_CLEAR + MARGIN) & (X + ehi <= BX1 - EDGE_CLEAR - MARGIN) \
                & (Y + flo >= BY0 + EDGE_CLEAR + MARGIN) & (Y + fhi <= BY1 - EDGE_CLEAR - MARGIN)
        else:
            ok &= (X + elo >= BX0 + 0.05) & (X + ehi <= BX1 - 0.05) \
                & (Y + flo >= BY0 + 0.05) & (Y + fhi <= BY1 - 0.05)
        for (rx0, ry0, rx1, ry1) in (CUT, ANT):
            ok &= ~((X + ehi > rx0 - MARGIN) & (X + elo < rx1 + MARGIN)
                    & (Y + fhi > ry0 - MARGIN) & (Y + flo < ry1 + MARGIN))
        if c["l"] == 1:
            ddx = np.maximum(np.maximum(X + elo - MOT_X, MOT_X - (X + ehi)), 0.0)
            ddy = np.maximum(np.maximum(Y + flo - MOT_Y, MOT_Y - (Y + fhi)), 0.0)
            ok &= (ddx * ddx + ddy * ddy) >= (MOT_R + MARGIN) ** 2
        for f in fixnear[c["d"]]:
            ok &= (np.abs(X - f["x"]) >= c["hx"] + f["hx"] + BODY_CLEAR + MARGIN) | \
                  (np.abs(Y - f["y"]) >= c["hy"] + f["hy"] + BODY_CLEAR + MARGIN)
            for (ux, uy) in f["rel"]:
                for (vx, vy) in c["rel"]:
                    ddx, ddy = X + vx - f["x"] - ux, Y + vy - f["y"] - uy
                    ok &= (ddx * ddx + ddy * ddy) >= (PAD_CC + MARGIN) ** 2
        return ok

    # ------------------------------------------- 1) 逃逸点: 迭代松弛(可动件互斥)
    gs, R = 0.5, 30.0
    base = np.arange(-R, R + 1e-9, gs)
    movnear = {c["d"]: [o for o in mov if o is not c
                        and abs(o["x"] - c["x"]) < 2 * R and abs(o["y"] - c["y"]) < 2 * R]
               for c in mov}

    def ok_mov(c, X, Y, pos):
        m = np.ones(np.broadcast(X, Y).shape, dtype=bool)
        for o in movnear[c["d"]]:
            ox, oy = pos[o["d"]]
            if abs(ox - c["x"]) > R or abs(oy - c["y"]) > R:
                continue
            m &= (np.abs(X - ox) >= c["hx"] + o["hx"] + BODY_CLEAR + MARGIN) | \
                 (np.abs(Y - oy) >= c["hy"] + o["hy"] + BODY_CLEAR + MARGIN)
            for (vx, vy) in c["rel"]:
                for (ux, uy) in o["rel"]:
                    m &= ((X + vx - ox - ux) ** 2 + (Y + vy - oy - uy) ** 2) >= (PAD_CC + MARGIN) ** 2
        return m

    pos = {c["d"]: (c["x"], c["y"]) for c in mov}
    esc = {}
    used_full = 0
    npass = 4 if budget >= 90 else (2 if budget >= 45 else 1)
    for it in range(npass):
        for c in mov:
            if AESC == "u" and it > 0:
                break
            X = c["x"] + base[:, None]
            Y = c["y"] + base[None, :]
            m = unary(c, X, Y)
            if AESC == "m":
                m = m & ok_mov(c, X, Y, pos)
            if m.any():
                d2 = base[:, None] ** 2 + base[None, :] ** 2
                k = int(np.argmin(np.where(m, d2, 1e18)))
                i, j = divmod(k, base.size)
            else:
                gx = np.arange(BX0, BX1 + 1e-9, 1.0)
                gy = np.arange(BY0, BY1 + 1e-9, 1.0)
                M = unary(c, gx[:, None], gy[None, :])
                if AESC == "m":
                    M = M & ok_mov(c, gx[:, None], gy[None, :], pos)
                k = int(np.argmin(np.where(M, (gx[:, None] - c["x"]) ** 2
                                     + (gy[None, :] - c["y"]) ** 2, 1e18)))
                i, j = divmod(k, gx.size)
                used_full += 1
                pos[c["d"]] = (float(gx[i]), float(gy[j]))
                continue
            pos[c["d"]] = (float(c["x"] + base[i]), float(c["y"] + base[j]))
            if it == 0:
                esc[c["d"]] = pos[c["d"]]
    for c in mov:
        esc.setdefault(c["d"], pos[c["d"]])
    diag["pre_moved"] = sum(1 for c in mov
                            if abs(esc[c["d"]][0] - c["x"]) > 0.25 or abs(esc[c["d"]][1] - c["y"]) > 0.25)
    if verbose:
        print("[求解] 预铺(含可动件互斥)需挪位件 %d ; 粗搜兜底 %d" % (diag["pre_moved"], used_full),
              flush=True)

    # ---------------------------------------------------------------- 窗口
    def build(extra):
        win = {}
        for c in mov:
            ex, ey = esc[c["d"]]
            x0 = min(c["x"], ex) - 0.5 - extra
            x1 = max(c["x"], ex) + 0.5 + extra
            y0 = min(c["y"], ey) - 0.5 - extra
            y1 = max(c["y"], ey) + 0.5 + extra
            elo, ehi, flo, fhi = c["ex"]
            x0 = max(x0, BX0 - elo + 0.05)
            x1 = min(x1, BX1 - ehi - 0.05)
            y0 = max(y0, BY0 - flo + 0.05)
            y1 = min(y1, BY1 - fhi - 0.05)
            win[c["d"]] = (int(math.ceil(x0 / 0.1 - 1e-9)), int(math.floor(x1 / 0.1 + 1e-9)),
                           int(math.ceil(y0 / 0.1 - 1e-9)), int(math.floor(y1 / 0.1 + 1e-9)))
        return win

    def cover_rects(mask):
        """把 True 区域精确覆盖成不相交矩形 [(i0,i1,j0,j1)] (索引为窗口内相对下标)"""
        rem = mask.copy()
        nx, ny = rem.shape
        out = []
        for i in range(nx):
            j = 0
            row = rem[i]
            while j < ny:
                if not row[j]:
                    j += 1
                    continue
                e = j
                while e + 1 < ny and row[e + 1]:
                    e += 1
                h = 1
                while i + h < nx and rem[i + h, j:e + 1].all():
                    h += 1
                out.append((i, i + h - 1, j, e))
                rem[i:i + h, j:e + 1] = False
                j = e + 1
        return out

    def make_model(win):
        """建 CP-SAT 模型; 返回 (model, I, J, disp, stat) 或 (None, 原因)"""
        masks = {}
        for c in mov:
            ilo, ihi, jlo, jhi = win[c["d"]]
            X = np.arange(ilo, ihi + 1) * 0.1
            Y = np.arange(jlo, jhi + 1) * 0.1
            masks[c["d"]] = unary(c, X[:, None], Y[None, :])
        bad = [d for d, m in masks.items() if not m.any()]
        if bad:
            return None, "窗口内无合法位置: %s" % bad[:6]
        model = cp_model.CpModel()
        I = {c["d"]: model.NewIntVar(win[c["d"]][0], win[c["d"]][1], "i_%s" % c["d"]) for c in mov}
        J = {c["d"]: model.NewIntVar(win[c["d"]][2], win[c["d"]][3], "j_%s" % c["d"]) for c in mov}

        nrect = 0
        for c in mov:
            m = masks[c["d"]]
            ilo, ihi, jlo, jhi = win[c["d"]]
            rects = cover_rects(m)
            nrect += len(rects)
            if len(rects) == 1 and rects[0] == (0, m.shape[0] - 1, 0, m.shape[1] - 1):
                continue
            bl = []
            for (a, b, cc, dd) in rects:
                bo = model.NewBoolVar("u%s_%d" % (c["d"], len(bl)))
                model.Add(I[c["d"]] >= ilo + a).OnlyEnforceIf(bo)
                model.Add(I[c["d"]] <= ilo + b).OnlyEnforceIf(bo)
                model.Add(J[c["d"]] >= jlo + cc).OnlyEnforceIf(bo)
                model.Add(J[c["d"]] <= jlo + dd).OnlyEnforceIf(bo)
                bl.append(bo)
            model.AddBoolOr(bl)

        U = {c["d"]: (10 * win[c["d"]][0], 10 * win[c["d"]][1],
                      10 * win[c["d"]][2], 10 * win[c["d"]][3]) for c in mov}   # 0.01mm
        EU = {c["d"]: tuple(int(round(v / UN)) for v in c["ex"]) for c in mov}    # 0.01mm
        np2 = np1 = ntup = 0
        for ai in range(len(mov)):
            a = mov[ai]
            ax0, ax1, ay0, ay1 = U[a["d"]]
            ae = EU[a["d"]]
            for bi in range(ai + 1, len(mov)):
                b = mov[bi]
                bx0, bx1, by0, by1 = U[b["d"]]
                be = EU[b["d"]]
                gx = int(round((a["hx"] + b["hx"] + BODY_CLEAR + MARGIN) / UN))
                gy = int(round((a["hy"] + b["hy"] + BODY_CLEAR + MARGIN) / UN))
                dxmn, dxmx = ax0 - bx1, ax1 - bx0
                dymn, dymx = ay0 - by1, ay1 - by0
                clauses = []
                if (dxmn < gx and dxmx > -gx) and (dymn < gy and dymx > -gy):
                    np2 += 1
                    opts = []
                    if ax1 - bx0 >= gx:
                        opts.append((1, I[a["d"]], I[b["d"]], gx))
                    if bx1 - ax0 >= gx:
                        opts.append((-1, I[b["d"]], I[a["d"]], gx))
                    if ay1 - by0 >= gy:
                        opts.append((2, J[a["d"]], J[b["d"]], gy))
                    if by1 - ay0 >= gy:
                        opts.append((-2, J[b["d"]], J[a["d"]], gy))
                    if not opts:
                        return None, "R2 无解对 %s<->%s" % (a["d"], b["d"])
                    for (k, v1, v2, lim) in opts:
                        bo = model.NewBoolVar("p%s_%s_%d" % (a["d"], b["d"], k))
                        model.Add(10 * v1 - 10 * v2 >= lim).OnlyEnforceIf(bo)
                        clauses.append(bo)
                # ---- R1: 焊盘中心距 (栅格上精确的 (di,dj) 禁止表) ----
                gapx = max(0, bx0 + be[0] - (ax1 + ae[1]), ax0 + ae[0] - (bx1 + be[1]))
                gapy = max(0, by0 + be[2] - (ay1 + ae[3]), ay0 + ae[2] - (by1 + be[3]))
                if gapx * gapx + gapy * gapy < D0 * D0:
                    dimn, dimx = win[a["d"]][0] - win[b["d"]][1], win[a["d"]][1] - win[b["d"]][0]
                    djmn, djmx = win[a["d"]][2] - win[b["d"]][3], win[a["d"]][3] - win[b["d"]][2]
                    forb = None
                    for (vx, vy) in a["rel"]:
                        for (ux, uy) in b["rel"]:
                            cx = int(round(vx / UN)) - int(round(ux / UN))
                            cy = int(round(vy / UN)) - int(round(uy / UN))
                            ox0, ox1 = dxmn + cx, dxmx + cx
                            oy0, oy1 = dymn + cy, dymx + cy
                            ddx = 0 if (ox0 <= 0 <= ox1) else min(abs(ox0), abs(ox1))
                            ddy = 0 if (oy0 <= 0 <= oy1) else min(abs(oy0), abs(oy1))
                            if ddx * ddx + ddy * ddy >= D0 * D0:
                                continue
                            if forb is None:
                                forb = set()
                            i0 = max(dimn, int(math.ceil((-D0 - cx) / GRID - 1e-9)))
                            i1 = min(dimx, int(math.floor((D0 - cx) / GRID + 1e-9)))
                            j0 = max(djmn, int(math.ceil((-D0 - cy) / GRID - 1e-9)))
                            j1 = min(djmx, int(math.floor((D0 - cy) / GRID + 1e-9)))
                            for di in range(i0, i1 + 1):
                                bxp = GRID * di + cx
                                for dj in range(j0, j1 + 1):
                                    byp = GRID * dj + cy
                                    if bxp * bxp + byp * byp < D0 * D0:
                                        forb.add((di, dj))
                    if forb:
                        np1 += 1
                        ntup += len(forb)
                        di = model.NewIntVar(dimn, dimx, "dx%s_%s" % (a["d"], b["d"]))
                        dj = model.NewIntVar(djmn, djmx, "dy%s_%s" % (a["d"], b["d"]))
                        model.Add(di == I[a["d"]] - I[b["d"]])
                        model.Add(dj == J[a["d"]] - J[b["d"]])
                        model.AddForbiddenAssignments([di, dj], sorted(forb))
                if clauses:
                    if len(clauses) == 1:
                        model.Add(clauses[0] == 1)
                    else:
                        model.AddBoolOr(clauses)
        # 目标一: 最小总位移
        disp = []
        for c in mov:
            px, py = int(round(c["x"] / UN)), int(round(c["y"] / UN))
            da = model.NewIntVar(0, 2 * 10 ** 6, "da_%s" % c["d"])
            db = model.NewIntVar(0, 2 * 10 ** 6, "db_%s" % c["d"])
            model.Add(da >= 10 * I[c["d"]] - px)
            model.Add(da >= px - 10 * I[c["d"]])
            model.Add(db >= 10 * J[c["d"]] - py)
            model.Add(db >= py - 10 * J[c["d"]])
            disp += [da, db]
        model.Minimize(sum(disp))
        st = {"nrect": nrect, "np2": np2, "np1": np1, "ntup": ntup}
        return (model, I, J, disp, st), None

    # ------------------------------------------- 2) 窗口逐级放大, 保留最优
    t_end = T0 + budget
    sched = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 28.0)
    best = None          # (D, extra, model, I, J, disp, pos)
    rounds_done = 0
    ok_rounds = 0
    for extra in sched:
        left = t_end - time.time()
        if left < 12:
            break
        if best is not None and ok_rounds >= max_rounds:
            break
        win = build(extra)
        if verbose:
            print("[求解] 窗口 extra=%.1f ..." % extra, flush=True)
        built, why = make_model(win)
        if built is None:
            if verbose:
                print("[求解]   跳过: %s" % why, flush=True)
            continue
        model, I, J, disp, st = built
        lim = cp_model.CpSolver()
        frac = 0.45 if best is None else 0.60
        lim.parameters.max_time_in_seconds = max(8.0, (t_end - time.time()) * frac)
        lim.parameters.num_search_workers = 8
        lim.parameters.random_seed = 12345
        t1 = time.time()
        s = lim.Solve(model)
        rounds_done += 1
        if s not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if verbose:
                print("[求解]   extra=%.1f 不可行 (%s), 放大窗口" % (extra, lim.StatusName(s)), flush=True)
            continue
        ok_rounds += 1
        D = int(round(lim.ObjectiveValue()))
        p2 = {c["d"]: (lim.Value(I[c["d"]]) * 0.1, lim.Value(J[c["d"]]) * 0.1) for c in mov}
        dtot = sum(abs(p2[c["d"]][0] - c["x"]) + abs(p2[c["d"]][1] - c["y"]) for c in mov)
        if verbose:
            print("[求解]   extra=%.1f %s: 总位移 %.2fmm (%.1fs) R2=%d R1表=%d 禁止元组=%d 单件矩形=%d"
                  % (extra, lim.StatusName(s), dtot, time.time() - t1,
                     st["np2"], st["np1"], st["ntup"], st["nrect"]), flush=True)
        if best is None or D < best[0]:
            best = (D, extra, model, I, J, disp, p2, win)
            if verbose:
                print("[求解]   -> 目前最优 (位移 %.2fmm)" % dtot, flush=True)
    if best is None:
        # 兜底: 预铺解(单件+锁定件+可动件互斥松弛)量化到 0.1mm 栅格后作为最接近的可行解
        fb = {d: (round(x / 0.1) * 0.1, round(y / 0.1) * 0.1) for d, (x, y) in pos.items()}
        diag["fallback"] = True
        diag["rounds"] = rounds_done
        diag["disp"] = sum(abs(fb[c["d"]][0] - c["x"]) + abs(fb[c["d"]][1] - c["y"]) for c in mov)
        if verbose:
            print("[求解] 所有 CP-SAT 轮次均未得到可行解 -> 使用预铺解兜底 (总位移 %.2fmm)"
                  % diag["disp"], flush=True)
        return fb, diag
    D, extra, model, I, J, disp, pos, wins = best
    diag["extra"] = extra
    diag["disp01"] = D
    diag["rounds"] = rounds_done

    # ------------------------------------------- 3) 阶段二: 位移基本锁定后优化美观
    # 允许 SLACK(<=3mm, 约 4%) 的额外位移用于换取"成行成列/聚簇",
    # 同时对位移加单位权重惩罚: 只有美观收益 >= 位移代价 时才会真的挪。
    model.Add(sum(disp) <= D)
    for c in mov:                      # 提示: 用阶段一解加速
        model.AddHint(I[c["d"]], int(round(pos[c["d"]][0] / 0.1)))
        model.AddHint(J[c["d"]], int(round(pos[c["d"]][1] / 0.1)))
    obj, cnt = build_aesthetics(model, I, J, comps, mov, pads, wins)
    if obj is not None:
        model.Maximize(obj - sum(disp))
        s2 = cp_model.CpSolver()
        s2.parameters.max_time_in_seconds = max(12.0, t_end - time.time())
        s2.parameters.num_search_workers = 8
        s2.parameters.random_seed = 777
        s = s2.Solve(model)
        if s in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            p3 = {c["d"]: (s2.Value(I[c["d"]]) * 0.1, s2.Value(J[c["d"]]) * 0.1) for c in mov}
            d3 = sum(abs(p3[c["d"]][0] - c["x"]) + abs(p3[c["d"]][1] - c["y"]) for c in mov)
            pos = p3
            diag["aes"] = cnt
            diag["phase2"] = s2.StatusName(s)
            if verbose:
                print("[求解] 阶段二(美观) %s: 总位移 %.2fmm, 对齐对 %d 聚簇 %d 网络 %d"
                      % (s2.StatusName(s), d3, cnt[0], cnt[1], cnt[2]), flush=True)
        else:
            if verbose:
                print("[求解] 阶段二无可行解, 保留阶段一解", flush=True)
    diag["disp"] = sum(abs(pos[c["d"]][0] - c["x"]) + abs(pos[c["d"]][1] - c["y"]) for c in mov)
    return pos, diag


# ======================================================================= 美观目标
def build_aesthetics(model, I, J, comps, mov, pads, wins):
    """美观目标(最大化): 成行成列 + 功能聚簇 - 网络包围盒线长
    权重设计: 位移是硬优先级(阶段二已把总位移钉在最优值 D*),
    因此这里只需在 D* 不变的前提下挑更好看的解。"""
    byD = {c["d"]: c for c in comps}
    expr = []

    def axis(c):
        return "H" if abs(c["rot"] % 180) < 1e-6 else "V"

    gg = collections.defaultdict(list)
    for c in mov:
        gg[(c["f"], axis(c))].append(c["d"])
    nal = 0
    for key, ds in gg.items():
        if len(ds) < 2 or len(ds) > 60:
            continue
        par = list(range(len(ds)))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, b = byD[ds[i]], byD[ds[j]]
                if abs(a["x"] - b["x"]) < 12 and abs(a["y"] - b["y"]) < 12:
                    x, y = find(i), find(j)
                    if x != y:
                        par[x] = y
        cl = collections.defaultdict(list)
        for i, d in enumerate(ds):
            cl[find(i)].append(d)
        for _, grp in cl.items():
            if len(grp) < 2 or len(grp) > 12:
                continue
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    a, b = grp[i], grp[j]
                    bo = model.NewBoolVar("al%s_%s" % (a, b))
                    if key[1] == "H":
                        model.Add(J[a] == J[b]).OnlyEnforceIf(bo)
                    else:
                        model.Add(I[a] == I[b]).OnlyEnforceIf(bo)
                    expr.append(12 * bo)
                    nal += 1

    netof = collections.defaultdict(set)
    for p in pads:
        if p.get("comp"):
            netof[p["net"]].add(p["comp"])
    ics = [c for c in comps if len(c["pads"]) >= 8]
    share = collections.Counter()
    for net, ds in netof.items():
        dl = list(ds)
        for i in range(len(dl)):
            for j in range(i + 1, len(dl)):
                share[(dl[i], dl[j])] += 1
                share[(dl[j], dl[i])] += 1
    ncl = 0
    for c in mov:
        if len(c["pads"]) > 4:
            continue
        best, bs = None, 1
        for ic in ics:
            s = share.get((c["d"], ic["d"]), 0)
            if s > bs:
                bs, best = s, ic
        if best is None:
            continue
        rad = int(round((c["hx"] + c["hy"] + best["hx"] + best["hy"] + 2.0) / UN))
        ax = 10 * I[best["d"]] if best["d"] in I else int(round(best["x"] / UN))
        ay = 10 * J[best["d"]] if best["d"] in J else int(round(best["y"] / UN))
        ddx = model.NewIntVar(0, 10 ** 6, "cx%s" % c["d"])
        ddy = model.NewIntVar(0, 10 ** 6, "cy%s" % c["d"])
        model.Add(ddx >= 10 * I[c["d"]] - ax)
        model.Add(ddx >= ax - 10 * I[c["d"]])
        model.Add(ddy >= 10 * J[c["d"]] - ay)
        model.Add(ddy >= ay - 10 * J[c["d"]])
        bo = model.NewBoolVar("cl%s" % c["d"])
        model.Add(ddx + ddy <= rad).OnlyEnforceIf(bo)
        expr.append(6 * bo)
        ncl += 1

    nwire = 0
    for net, ds in netof.items():
        dl = [d for d in ds if d in byD]
        if len(dl) < 2:
            continue
        xs, ys, lox, hix, loy, hiy = [], [], [], [], [], []
        for d in dl:
            if d in I:
                xs.append(10 * I[d])
                ys.append(10 * J[d])
                lox.append(10 * wins[d][0])
                hix.append(10 * wins[d][1])
                loy.append(10 * wins[d][2])
                hiy.append(10 * wins[d][3])
            else:
                vx = int(round(byD[d]["x"] / UN))
                vy = int(round(byD[d]["y"] / UN))
                xs.append(vx)
                ys.append(vy)
                lox.append(vx)
                hix.append(vx)
                loy.append(vy)
                hiy.append(vy)
        nm = "".join(ch for ch in net if ch.isalnum())[:5] or "n"
        mx = model.NewIntVar(min(hix), max(hix), "mx%s%d" % (nm, nwire))
        mn = model.NewIntVar(min(lox), max(lox), "mn%s%d" % (nm, nwire))
        my = model.NewIntVar(min(hiy), max(hiy), "my%s%d" % (nm, nwire))
        mm = model.NewIntVar(min(loy), max(loy), "mm%s%d" % (nm, nwire))
        for v in xs:
            model.Add(mx >= v)
            model.Add(mn <= v)
        for v in ys:
            model.Add(my >= v)
            model.Add(mm <= v)
        expr.append(mn - mx + mm - my)
        nwire += 1
    return sum(expr), (nal, ncl, nwire)


def align_metric(comps, pos):
    """对齐度: 同封装同朝向、空间邻近(<=12mm)的组里, 落在同一坐标线上的最多件数之和"""
    def axis(c):
        return "H" if abs(c["rot"] % 180) < 1e-6 else "V"
    gg = collections.defaultdict(list)
    for c in comps:
        if not c["fix"]:
            gg[(c["f"], axis(c))].append(c["d"])
    tot = 0
    for key, ds in gg.items():
        if len(ds) < 2:
            continue
        par = list(range(len(ds)))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, b = pos[ds[i]], pos[ds[j]]
                if abs(a[0] - b[0]) < 12 and abs(a[1] - b[1]) < 12:
                    x, y = find(i), find(j)
                    if x != y:
                        par[x] = y
        cl = collections.defaultdict(list)
        for i, d in enumerate(ds):
            cl[find(i)].append(d)
        for _, grp in cl.items():
            if len(grp) < 2:
                continue
            cc = [(pos[d][1] if key[1] == "H" else pos[d][0]) for d in grp]
            tot += max(collections.Counter(round(v, 1) for v in cc).values())
    return tot


def wire_metric(pads, pos):
    """估算总线长: 每网络包围盒周长之和 (与求解器目标一致的代理指标)"""
    netof = collections.defaultdict(set)
    for p in pads:
        if p.get("comp"):
            netof[p["net"]].add(p["comp"])
    s = 0.0
    for net, ds in netof.items():
        if len(ds) < 2:
            continue
        xs = [pos[d][0] for d in ds]
        ys = [pos[d][1] for d in ds]
        s += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return s


# ======================================================================= main
def align_metric(comps, pos):
    def axis(c):
        return "H" if abs(c["rot"] % 180) < 1e-6 else "V"
    gg = collections.defaultdict(list)
    for c in comps:
        if not c["fix"]:
            gg[(c["f"], axis(c))].append(c["d"])
    tot = 0
    for key, ds in gg.items():
        if len(ds) < 2:
            continue
        par = list(range(len(ds)))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, b = pos[ds[i]], pos[ds[j]]
                if abs(a[0] - b[0]) < 12 and abs(a[1] - b[1]) < 12:
                    x, y = find(i), find(j)
                    if x != y:
                        par[x] = y
        cl = collections.defaultdict(list)
        for i, d in enumerate(ds):
            cl[find(i)].append(d)
        for _, grp in cl.items():
            if len(grp) < 2:
                continue
            cc = [(pos[d][1] if key[1] == "H" else pos[d][0]) for d in grp]
            tot += max(collections.Counter(round(v, 1) for v in cc).values())
    return tot


def wire_metric(pads, pos):
    netof = collections.defaultdict(set)
    for p in pads:
        if p.get("comp"):
            netof[p["net"]].add(p["comp"])
    s = 0.0
    for net, ds in netof.items():
        if len(ds) < 2:
            continue
        xs = [pos[d][0] for d in ds]
        ys = [pos[d][1] for d in ds]
        s += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return s


def fingerprint():
    """输入文件 md5, 用于确认结果对应哪个快照"""
    import hashlib
    out = []
    for f in ("comps3.json", "live.json"):
        try:
            out.append(hashlib.md5(io.open(os.path.join(BASE, f), "rb").read()).hexdigest())
        except Exception:
            out.append("?")
    return tuple(out)


def align_pairs(comps, pos):
    """严格对齐对数: 同封装+同朝向+空间邻近(<=12mm) 且坐标完全相同的元件对"""
    def axis(c):
        return "H" if abs(c["rot"] % 180) < 1e-6 else "V"
    gg = collections.defaultdict(list)
    for c in comps:
        if not c["fix"]:
            gg[(c["f"], axis(c))].append(c["d"])
    n = 0
    for key, ds in gg.items():
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, b = pos[ds[i]], pos[ds[j]]
                if abs(a[0] - b[0]) < 12 and abs(a[1] - b[1]) < 12:
                    if key[1] == "H" and abs(a[1] - b[1]) < 1e-6:
                        n += 1
                    elif key[1] == "V" and abs(a[0] - b[0]) < 1e-6:
                        n += 1
    return n


def main():
    global AESC
    budget = 150.0
    if len(sys.argv) > 1:
        budget = float(sys.argv[1])
    if len(sys.argv) > 2:
        AESC = sys.argv[2]
    fp0 = fingerprint()
    print("[数据] 输入指纹 md5: comps3=%s live=%s" % (fp0[0][:12], fp0[1][:12]), flush=True)
    comps, pads = load_data()
    cur = {c["d"]: (c["x"], c["y"]) for c in comps}
    V0 = check(comps, pads, cur, "初始")
    before = sum(len(v) for v in V0.values())

    sol, sdiag = solve(comps, pads, budget)

    if sol is None:
        print("[结果] 完全无解且无预铺兜底 -> 输出空位移(保持原位), 并列出全部残余违规")
        sol = {}
    elif sdiag.get("fallback"):
        print("[结果] 注意: 本次为兜底解(预铺松弛结果, 非 CP-SAT 最优解), 建议加大超时秒数重跑")
    newp = dict(cur)
    for d, (x, y) in sol.items():
        newp[d] = (x, y)
    moves = {}
    for d, (x, y) in sol.items():
        dx, dy = round(x - cur[d][0], 4), round(y - cur[d][1], 4)
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            moves[d] = [dx, dy]

    V1 = check(comps, pads, newp, "结果")
    after = sum(len(v) for v in V1.values())
    tot = sum(abs(v[0]) + abs(v[1]) for v in moves.values())

    lockres, movres = [], []
    for txt, pair, a, b in fmt_viol(V1):
        if a in FIXED and (b == "" or b in FIXED):
            lockres.append("%s | %s" % (txt, pair))
        else:
            movres.append("%s | %s" % (txt, pair))

    a0, a1 = align_metric(comps, cur), align_metric(comps, newp)
    w0, w1 = wire_metric(pads, cur), wire_metric(pads, newp)

    print("\n==================== 结果 ====================")
    print("求解耗时         : %.1f s" % (time.time() - T0))
    print("移动元件数       : %d / %d 可动件" % (len(moves), sum(1 for c in comps if not c["fix"])))
    print("窗口档位/轮次    : extra=%.1f, 求解轮次 %d" % (sdiag.get("extra", -1), sdiag.get("rounds", 0)))
    print("总位移           : %.2f mm   (求解器找到的最小位移 %.2f mm)"
          % (tot, sdiag.get("disp01", 0) / 100.0))
    print("违规数           : 初始 %d -> 结果 %d" % (before, after))
    for k in ("R1", "R2", "R3", "R4", "R5", "R7"):
        if len(V0[k]) or len(V1[k]):
            print("    %s: %d -> %d" % (k, len(V0[k]), len(V1[k])))
    ap0, ap1 = align_pairs(comps, cur), align_pairs(comps, newp)
    print("美观: 成行成列(同线最多件数之和) %d -> %d ; 严格对齐对数 %d -> %d" % (a0, a1, ap0, ap1))
    print("      估算总线长(各网络包围盒之和) %.1f -> %.1f mm" % (w0, w1))
    print("\n-- 涉及可动件的残余违规 (%d) --" % len(movres))
    for s in movres:
        print("   " + s)
    print("\n-- 仅由锁定件导致的不可解残差 (%d) --" % len(lockres))
    for s in lockres:
        print("   " + s)
    if moves:
        print("\n-- 位移明细 --")
        for d in sorted(moves, key=lambda k: -abs(moves[k][0]) - abs(moves[k][1])):
            print("   %-6s (%7.3f,%7.3f) -> (%7.3f,%7.3f)  d=(%+.2f,%+.2f) |d|=%.2f"
                  % (d, cur[d][0], cur[d][1], newp[d][0], newp[d][1],
                     moves[d][0], moves[d][1], abs(moves[d][0]) + abs(moves[d][1])))

    out = {"moves": {k: moves[k] for k in sorted(moves)}, "rot": {},
           "before": before, "after": after}
    with io.open(os.path.join(BASE, "placement_new.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("\n[输出] %s  moves=%d before=%d after=%d" % (
        os.path.join(BASE, "placement_new.json"), len(moves), before, after))
    fp1 = fingerprint()
    if fp1 != fp0:
        print("[警告] 运行期间输入文件发生了变化(comps3/live md5 改变): 本结果对应运行起始快照")
    else:
        print("[校验] 运行期间输入文件未变化: 结果与磁盘上的输入一致")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as _e:
        sys.stderr.write("[错误] 求解失败: %s\n" % _e)
        sys.exit(2)
    try:
        sys.exit(0 if (after == 0) else 1)
    except NameError:
        sys.exit(0)
