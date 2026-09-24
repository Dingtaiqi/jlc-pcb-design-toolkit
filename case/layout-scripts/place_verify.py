#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
place_verify.py  --  独立的 PCB 摆放"规则验证 + 美观评分"工具（纯离线）

用法
----
    python place_verify.py [placement_new.json路径] [--json 输出路径]

    python place_verify.py                      # 只验证"原始摆放"(comps3.json 基准位置)
    python place_verify.py placement_new.json   # 验证"原始位置 + 位移/旋转方案"
    python place_verify.py placement_new.json --json report.json

可选参数
--------
    --comps PATH   元件基准表 (默认脚本同目录 comps3.json)
    --live  PATH   焊盘实测几何 (默认脚本同目录 live.json)
    --json  PATH   额外输出结构化 JSON (规则计数 + 逐条违规明细 + 美观指标)
    --limit N      文本明细最多打印多少条 (默认 25)
    --strict       有违规时进程退出码 1 (默认始终 0，方便串在流水线里)

约束
----
* 只读输入文件，从不写回输入文件；不联网、不调用任何 HTTP / MCP / EDA 接口。
* 控制台编码安全：输出对无法编码的字符做 replace，不会因 GBK 控制台崩掉。

几何模型（本工具自己的实现，shapely 2.x 矢量运算，非复制既有脚本）
----------------------------------------------------------------
1. 焊盘（R1）：每个焊盘按"关联到哪个元件"跟着该元件平移/旋转，取**中心点**做欧氏中心距
   判定。规则本身就是"中心距"，所以不需要焊盘外接圆；焊盘形状串（RECT/ELLIPSE/OVAL）
   只用于统计与说明。焊盘↔元件归属用"全局最优指派"自行实现，见 assign_pads()。
2. 元件本体（R2/R3/R4/R5）：**旋转矩形多边形**
   rect = rotate( box(cx-Lx/2, cy-Ly/2, cx+Lx/2, cy+Ly/2), angle, origin=(cx,cy) )
   Lx=局部X尺寸、Ly=局部Y尺寸（角度约定经数据反推验证：本坐标系下为数学正向 CCW，
   即 (x,y)->(x cosθ - y sinθ, x sinθ + y cosθ)，已用 rot=0/90/180/-90 的 0603 焊盘
   偏置实测校验通过）。间隙/相交/面积全部由多边形布尔运算得到，不是"包围盒近似"。
3. 电机禁区：圆**按 64 段/象限离散成多边形**（buffer 半径 9.51mm），相交面积由多边形
   交集算出（离散化带来的相对面积误差 < 0.03%）。
4. 旋转角变更 Δθ：焊盘偏置随元件一起转（R(Δθ)·offset），本体也随之改变朝向。

规则参数
--------
R1 不同元件焊盘中心距 >= 1.778mm(70mil)，同网络同样要求（无条件）
R2 不同元件本体间隙 >= 0.20mm（本体=旋转矩形）
R3 微动(封装名含 3JWD-DBHD，13.5 x 6.4mm 旋转矩形)与任何其他元件本体相交即违规
R4 禁区: 滚轮挖槽 x1.14-21.34/y50.80-75.44、天线净空 x84.6-90.5/y31.0-39.0、
        电机区 圆心(10.160, 19.177) R9.51（仅 l==1）、板框 x0-90/y-7.20-82.80 内
R5 本体距板框边界 >= 2.5mm（例外: CN1,USB1,H1,H2,H5,LED1,U7）；另单独输出"出板"
R6 旋转角只允许 0/90/180/270（按 mod 360 归一后判定）
R7 坐标在 0.1mm 栅格上（偏离 > 0.05mm 即违规）
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import sys
import time
from collections import defaultdict

import numpy as np

try:
    from shapely.affinity import rotate as sh_rotate
    from shapely.geometry import Polygon as shapely_Polygon, box as sh_box
    from shapely.geometry import Point as sh_Point
    from shapely.geometry import Polygon as sh_Polygon
except Exception as _e:  # pragma: no cover
    sys.stderr.write("需要 shapely>=2.0: %s\n" % _e)
    raise

MIL = 0.0254
PAD_LIMIT = 70.0 * MIL            # 1.778 mm
BODY_CLEAR = 0.20                 # mm
EDGE_CLEAR = 2.5                  # mm
GRID = 0.1                        # mm
GRID_TOL = 0.05                   # mm

BOARD = (0.0, -7.20, 90.0, 82.80)         # x0,y0,x1,y1
# 滚轮挖槽真实几何：8 点凹多边形（左上/右上两条手臂 + 中间凹口）
# 来源: eda.pcb_PrimitiveFill 'e602'.getState_ComplexPolygon() (单位 mil)
CUTOUT = [(16.360, 75.440), (16.360, 60.580), (21.340, 60.580), (21.340, 50.800), (1.143, 50.800), (1.143, 60.580), (6.430, 60.580), (6.430, 75.440)]
ANT_KEEPOUT = (84.6, 31.0, 90.5, 39.0)
MOTOR_C = (10.922, 14.986)   # = AS5600(U5) 几何中心, python sync_motor_center.py 可同步
MOTOR_R = 9.51

EDGE_EXEMPT = ["CN1", "USB1", "H1", "H2", "H5", "LED1", "U7"]

SW_MARK = "3JWD-DBHD"
SW_L, SW_W = 13.5, 6.4

IC_FP_PREFIX = ("QFN", "SOIC", "TSSOP", "VQFN", "AQFN")
POWER_RE = re.compile(
    r"^(?:\+?\d+(?:V\d*)?V\d*|V\d+(?:V\d*)?|VCC(?:_.*)?|VDD(?:_.*)?|AVDD(?:_.*)?|"
    r"DVDD(?:_.*)?|VBUS.*|VREG_.*|IP\+?\d*V.*|VBAT.*|VIN.*)$", re.I)
GND_RE = re.compile(r"^(?:A?P?GND(?:_.*)?|GND(?:_.*)?|VSS.*)$", re.I)

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------- 基础工具
def _reconf(stream):
    try:
        stream.reconfigure(errors="replace")
    except Exception:
        pass


def n2(x, nd=3):
    """稳定数字格式化（去掉 -0.000）"""
    if x is None:
        return "-"
    v = ("%%.%df" % nd) % (x + 0.0)
    if v.startswith("-") and float(v) == 0.0:
        v = v[1:]
    return v


def fnum(x, nd=3):
    try:
        return float(x)
    except Exception:
        return None


def jfloats(obj):
    """numpy -> python，保证 json 可序列化"""
    if isinstance(obj, dict):
        return {str(k): jfloats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jfloats(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ----------------------------------------------------------------------------- 封装尺寸表
# 取自本项目既有尺寸表（覆盖全部封装名），并额外记录"来源"以便自证覆盖度
TBL = {
    "C0603": (1.6, 0.9), "R0603": (1.6, 0.9), "L0603": (1.6, 0.9), "R1206": (3.2, 1.7),
    "SMA_L4.3-W2.6-LS5.0-BI": (4.3, 2.6), "HDR-TH_3P-P2.54-V-F": (7.7, 2.6),
    "HDR-TH_2P-P2.54-V-F": (5.1, 2.6), "HDR-TH_5P-P2.54-V-M": (12.7, 2.6),
    "HDR-TH_10P-P2.54-V-F": (25.4, 2.6), "OPTO-TH_3P_PT2559B": (5.2, 4.0),
    "AO3401A_SOT-23-3": (3.0, 1.5), "ANT-SMD_L3.1-W1.6": (3.1, 1.6),
    "Key_SMD_3x4x2": (3.0, 4.0), "SW-TH_SHOU-HAN_3JWD-DBHD-13.5": (13.5, 6.4),
    "USB_TYPE-C-16P": (9.0, 7.3), "LED-TH_L4.5-W2.25-P2.54-FD": (4.5, 2.3),
    "CONN-TH_XT30PW-M": (10.0, 7.0),
}


def footprint_size(fp):
    """返回 (Lx, Ly, 来源)。Lx=局部X方向尺寸, Ly=局部Y方向尺寸"""
    if fp in TBL:
        return TBL[fp][0], TBL[fp][1], "table"
    m = re.search(r"_L([0-9.]+)-W([0-9.]+)", fp) or re.search(r"L([0-9.]+)-W([0-9.]+)", fp)
    if m:
        return float(m.group(1)), float(m.group(2)), "regex"
    if re.search(r"^([A-Z]+)-(\d+)", fp):
        return 6.0, 5.0, "fallback-generic"
    return 2.0, 1.5, "fallback-default"


# ----------------------------------------------------------------------------- 数据载入
class Model:
    """元件 + 焊盘 + 焊盘归属（全部只读自输入文件）"""

    def __init__(self, comps_path, live_path):
        self.warnings = []
        self.comps_path, self.live_path = comps_path, live_path
        comps = self._load_comps(comps_path)
        live = self._load_live(live_path)
        self.raw_comp_count = len(comps)
        self.pads = live["pads"]
        self.vias = live.get("vias", [])
        self.lines = live.get("lines", [])

        self.D = []          # designator
        self.info = []       # dict per comp
        for i, c in enumerate(comps):
            d = str(c.get("d", "?%d" % i))
            fp = str(c.get("f", ""))
            if d in self.D:
                self.warnings.append("重复位号 %s（取第一条）" % d)
                continue
            self.D.append(d)
            L, W, src = footprint_size(fp)
            self.info.append({
                "idx": i, "d": d, "f": fp, "x": float(c.get("x", 0.0)), "y": float(c.get("y", 0.0)),
                "r": float(c.get("r", 0.0) or 0.0), "l": int(c.get("l", 1) or 1),
                "npins": len(c.get("p") or []), "L": L, "W": W, "size_src": src,
            })
        # 尺寸表覆盖自证
        self.fp_sizes = {}
        for c in self.info:
            self.fp_sizes[c["f"]] = {"L": c["L"], "W": c["W"], "src": c["size_src"]}
        for fp, s in sorted(self.fp_sizes.items()):
            if s["src"].startswith("fallback"):
                self.warnings.append("封装 %s 未命中尺寸表/正则，使用兜底尺寸 %sx%s mm"
                                     % (fp, s["L"], s["W"]))
        self.byD = {c["d"]: c for c in self.info}
        self.assign_pads()
        self.build_nets()

    # -- 载入 ---------------------------------------------------------------
    @staticmethod
    def _load_comps(path):
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):                      # 容错: {"components":[...]}
            for k in ("components", "comps", "parts", "items"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
            else:
                data = [data]
        if not isinstance(data, list):
            raise ValueError("comps 文件既不是数组也不是含 components 的对象: %s" % path)
        return data

    @staticmethod
    def _load_live(path):
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "pads" not in data:
            raise ValueError("live 文件缺少 pads: %s" % path)
        return data

    # -- 焊盘 -> 元件 归属 -----------------------------------------------------
    def assign_pads(self):
        """全局最优指派（匈牙利算法，scipy.optimize.linear_sum_assignment），
        成本 = 焊盘中心到元件原点的距离；层不匹配加 100mm 硬惩罚（layer=12 为通孔，两层都合法）。
        每个元件恰好拥有 len(p) 个焊盘槽位。相比"贪心就近分配"更稳：
        返回的是全局最小总距离解，不会因为某个近邻抢占而错配。
        无 scipy 时回退到"按距离排序的贪心 + 层约束 + 容量约束"。"""
        n_pads = len(self.pads)
        slots = []
        for ci, c in enumerate(self.info):
            slots.extend([ci] * c["npins"])
        self.pad_src = [None] * n_pads
        self.pad_comp = [-1] * n_pads
        self.assign_cost = [0.0] * n_pads
        self.assign_pen = 0
        if not slots:
            return
        sl = np.array(slots, dtype=np.int64)
        cx = np.array([self.info[i]["x"] for i in sl])
        cy = np.array([self.info[i]["y"] for i in sl])
        cl = np.array([self.info[i]["l"] for i in sl])
        px = np.array([float(p[2]) for p in self.pads])
        py = np.array([float(p[3]) for p in self.pads])
        pl = np.array([int(p[1]) for p in self.pads])
        PEN = 100.0
        dist = np.sqrt((px[:, None] - cx[None, :]) ** 2 + (py[:, None] - cy[None, :]) ** 2)
        lay_bad = (pl[:, None] != 12) & (pl[:, None] != cl[None, :])
        cost = dist + np.where(lay_bad, PEN, 0.0)
        try:
            from scipy.optimize import linear_sum_assignment
            ri, cj = linear_sum_assignment(cost)
            pairs = list(zip(ri.tolist(), cj.tolist()))
            used_pads = set()
            for pi, si in pairs:
                self.pad_comp[pi] = int(sl[si])
                self.assign_cost[pi] = float(dist[pi, si])
                self.assign_pen += int(cost[pi, si] >= PEN)
                used_pads.add(pi)
            if len(used_pads) != n_pads:
                self.warnings.append("指派未覆盖全部焊盘（%d/%d）" % (len(used_pads), n_pads))
        except Exception as e:  # pragma: no cover
            self.warnings.append("scipy 不可用(%s)，回退贪心指派" % e)
            cap = defaultdict(int)
            order = sorted(range(n_pads * max(1, len(slots))), key=lambda k: 0)
            cand = []
            for pi in range(n_pads):
                for si in range(len(sl)):
                    cand.append((float(cost[pi, si]), pi, si))
            cand.sort()
            for c_, pi, si in cand:
                ci = int(sl[si])
                if self.pad_comp[pi] >= 0 or cap[ci] >= self.info[ci]["npins"]:
                    continue
                self.pad_comp[pi] = ci
                cap[ci] += 1
                self.assign_cost[pi] = float(dist[pi, si])
                self.assign_pen += int(c_ >= PEN)
        self.pads_by_comp = defaultdict(list)
        for pi, ci in enumerate(self.pad_comp):
            if ci >= 0:
                self.pads_by_comp[ci].append(pi)
        miss = [self.info[i]["d"] for i in range(len(self.info))
                if len(self.pads_by_comp[i]) != self.info[i]["npins"]]
        if miss:
            self.warnings.append("焊盘数不匹配的元件 %d 个: %s" % (len(miss), ",".join(miss[:8])))
        self.assign_stats = {
            "n_pads": n_pads, "n_slots": len(slots),
            "mean_dist_mm": (sum(self.assign_cost) / n_pads) if n_pads else 0.0,
            "max_dist_mm": max(self.assign_cost) if n_pads else 0.0,
            "layer_penalized": self.assign_pen,
        }

    def build_nets(self):
        self.net_pads = defaultdict(list)       # net -> [pad_index]
        self.net_comps = defaultdict(set)       # net -> {comp_index}
        for pi, p in enumerate(self.pads):
            net = p[0] or ""
            self.net_pads[net].append(pi)
            ci = self.pad_comp[pi]
            if ci >= 0:
                self.net_comps[net].add(ci)
        self.comp_nets = defaultdict(set)
        for net, cs in self.net_comps.items():
            for ci in cs:
                self.comp_nets[ci].add(net)

    def comp_pad_offsets(self, ci):
        c = self.info[ci]
        offs = []
        for pi in self.pads_by_comp.get(ci, []):
            p = self.pads[pi]
            offs.append((pi, float(p[2]) - c["x"], float(p[3]) - c["y"]))
        return offs


# ----------------------------------------------------------------------------- 方案（位移/旋转）
class Plan:
    """把 moves/rot 作用到基准位置上；所有几何都从这里取绝对位置"""

    def __init__(self, model, moves=None, rots=None, name="原始摆放"):
        self.m = model
        self.name = name
        self.moves = dict(moves or {})
        self.rots = dict(rots or {})
        self.drot = {}
        for d, ang in self.rots.items():
            c = model.byD.get(d)
            if c is None:
                continue
            dd = float(ang) - c["r"]
            while dd <= -180.0:
                dd += 360.0
            while dd > 180.0:
                dd -= 360.0
            self.drot[d] = dd

    # -- 位置 ---------------------------------------------------------------
    def delta(self, d):
        dx, dy = self.moves.get(d, (0.0, 0.0))
        return float(dx), float(dy)

    def pos(self, d):
        c = self.m.byD[d]
        dx, dy = self.delta(d)
        return c["x"] + dx, c["y"] + dy

    def angle(self, d):
        c = self.m.byD[d]
        return c["r"] + self.drot.get(d, 0.0)

    def disp(self, d):
        dx, dy = self.delta(d)
        return math.hypot(dx, dy)

    # -- 几何 ---------------------------------------------------------------
    def _c(self, c_or_d):
        if isinstance(c_or_d, str):
            return self.m.byD[c_or_d]
        if isinstance(c_or_d, int):
            return self.m.info[c_or_d]
        return c_or_d

    def body(self, c_or_d):
        c = self._c(c_or_d)
        x, y = self.pos(c["d"])
        L, W = c["L"], c["W"]
        g = sh_box(x - L / 2.0, y - W / 2.0, x + L / 2.0, y + W / 2.0)
        ang = self.angle(c["d"])
        if abs(ang) > 1e-12:
            g = sh_rotate(g, ang, origin=(x, y))
        return g

    def bodies(self):
        return [self.body(c) for c in self.m.info]

    def pad_points(self):
        """返回 (N,2) 数组：焊盘中心随所属元件平移+旋转后的绝对位置"""
        n = len(self.m.pads)
        P = np.zeros((n, 2))
        for ci in range(len(self.m.info)):
            c = self.m.info[ci]
            dx, dy = self.delta(c["d"])
            th = math.radians(self.drot.get(c["d"], 0.0))
            ct, st = math.cos(th), math.sin(th)
            for pi, ox, oy in self.m.comp_pad_offsets(ci):
                if abs(th) > 1e-12:
                    ox, oy = ox * ct - oy * st, ox * st + oy * ct
                P[pi, 0] = c["x"] + ox + dx
                P[pi, 1] = c["y"] + oy + dy
        # 未归属焊盘（理论上没有）：原样保留
        done = np.zeros(n, dtype=bool)
        for ci in range(len(self.m.info)):
            for pi, _a, _b in self.m.comp_pad_offsets(ci):
                done[pi] = True
        for pi in np.where(~done)[0]:
            P[pi, 0] = float(self.m.pads[pi][2])
            P[pi, 1] = float(self.m.pads[pi][3])
        return P

    # -- 位移摘要 ------------------------------------------------------------
    def summary(self):
        moved = []
        for d in self.m.D:
            if d in self.moves:
                disp = self.disp(d)
                dx, dy = self.delta(d)
                if disp > 1e-9:
                    moved.append({"d": d, "dx": dx, "dy": dy, "disp": disp})
        moved.sort(key=lambda r: -r["disp"])
        rot_changed = [{"d": d, "from": self.m.byD[d]["r"], "to": self.m.byD[d]["r"] + self.drot[d]}
                       for d in self.drot if abs(self.drot[d]) > 1e-9]
        total = sum(r["disp"] for r in moved)
        mx = moved[0]["disp"] if moved else 0.0
        return {
            "n_moved": len(moved), "n_rotated": len(rot_changed),
            "total_disp_mm": total, "max_disp_mm": mx,
            "mean_disp_mm": (total / len(moved)) if moved else 0.0,
            "n_sub_0p1mm": sum(1 for r in moved if r["disp"] < 0.1),
            "n_sub_0p01mm": sum(1 for r in moved if r["disp"] < 0.01),
            "negligible": (mx < 0.1),
            "unchanged": (mx < 1e-9),
            "top": moved[:8], "rot_changed": rot_changed[:8],
        }


# ----------------------------------------------------------------------------- 规则检查
def make_rule(rid, title, limit=None, unit="处"):
    return {"id": rid, "title": title, "limit": limit, "unit": unit,
            "count": 0, "status": "pass", "details": [], "notes": [], "sig": set()}


def rule_add(r, detail, sig, sort_key):
    detail["_k"] = sort_key
    r["details"].append(detail)
    r["sig"].add(sig)
    r["count"] += 1


class Checker:
    def __init__(self, model):
        self.m = model
        self.board = sh_box(*BOARD)
        self.cut = shapely_Polygon(CUTOUT)
        self.ant = sh_box(*ANT_KEEPOUT)
        self.motor = sh_Point(*MOTOR_C).buffer(MOTOR_R, quad_segs=64)
        self.sw_idx = [c for c in model.info if SW_MARK in c["f"]]

    # ---- R1 ---------------------------------------------------------------
    def r1(self, plan):
        r = make_rule("R1", "焊盘中心距 >= %.3f mm (70 mil)，不同元件之间，同网络无条件同样要求"
                      % PAD_LIMIT, PAD_LIMIT, "处")
        m = self.m
        P = plan.pad_points()
        comp_of = m.pad_comp
        n = len(P)
        cand = []
        try:
            from scipy.spatial import cKDTree
            tree = cKDTree(P)
            pairs = tree.query_pairs(r=PAD_LIMIT, output_type="ndarray")
            cand = [(int(a), int(b)) for a, b in pairs]
        except Exception:
            for i in range(n):
                for j in range(i + 1, n):
                    if abs(P[i, 0] - P[j, 0]) <= PAD_LIMIT and abs(P[i, 1] - P[j, 1]) <= PAD_LIMIT:
                        cand.append((i, j))
        for i, j in cand:
            ca, cb = comp_of[i], comp_of[j]
            if ca < 0 or cb < 0 or ca == cb:
                continue
            d = math.hypot(P[i, 0] - P[j, 0], P[i, 1] - P[j, 1])
            if d >= PAD_LIMIT - 1e-12:
                continue
            A, B = m.info[ca], m.info[cb]
            na, nb = str(m.pads[i][6]), str(m.pads[j][6])
            aa, bb = "%s#%s" % (A["d"], na), "%s#%s" % (B["d"], nb)
            key = tuple(sorted([(A["d"], na), (B["d"], nb)]))
            detail = {"a": aa, "b": bb, "dist": round(d, 4),
                      "gap_to_limit": round(PAD_LIMIT - d, 4),
                      "net_a": m.pads[i][0] or "", "net_b": m.pads[j][0] or ""}
            rule_add(r, detail, key, (round(d, 5), aa, bb))
        r["details"].sort(key=lambda x: x["_k"])
        return r

    # ---- R2 / R3 ----------------------------------------------------------
    def _body_pairs(self, plan, need):
        """返回 [(i,j,dist)] 距离小于 need 的元件对（先按包围盒粗筛，再多边形精确算）"""
        out = []
        info = self.m.info
        geoms = plan.bodies()
        bnds = [g.bounds for g in geoms]
        byd = defaultdict(list)
        cell = max(need, 0.05)
        for i, b in enumerate(bnds):
            key = (int(math.floor(b[0] / cell)), int(math.floor(b[1] / cell)))
            byd[key].append(i)
        checked = set()
        for i, b in enumerate(bnds):
            kx = int(math.floor(b[0] / cell))
            ky = int(math.floor(b[1] / cell))
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    for j in byd.get((kx + ox, ky + oy), ()):
                        if j <= i:
                            continue
                        p = (i, j)
                        if p in checked:
                            continue
                        checked.add(p)
                        bj = bnds[j]
                        if b[2] + need < bj[0] or bj[2] + need < b[0]:
                            continue
                        if b[3] + need < bj[1] or bj[3] + need < b[1]:
                            continue
                        out.append((i, j, geoms[i].distance(geoms[j])))
        # 兜底：粗筛网格可能漏，用全对再补一次（166 元件 = 13.7k 对，代价可忽略）
        allp = []
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                p = (i, j)
                if p in checked:
                    continue
                checked.add(p)
                allp.append((i, j, geoms[i].distance(geoms[j])))
        out.extend([t for t in allp if t[2] < need])
        return out, geoms

    def r2(self, plan):
        r = make_rule("R2", "不同元件本体矩形间隙 >= %.2f mm" % BODY_CLEAR, BODY_CLEAR, "对")
        pairs, geoms = self._body_pairs(plan, BODY_CLEAR)
        cross = 0
        for i, j, dist in pairs:
            A, B = self.m.info[i], self.m.info[j]
            # 本体按面判定：同一面的元件才会真正干涉；异面（一顶一底）几何上重合也不冲突
            if A["l"] != B["l"]:
                cross += 1
                continue
            if dist >= BODY_CLEAR - 1e-12:
                continue
            key = tuple(sorted([A["d"], B["d"]]))
            detail = {"a": key[0], "b": key[1], "gap": round(dist, 4),
                      "layer": A["l"], "short_by": round(BODY_CLEAR - dist, 4)}
            rule_add(r, detail, key, (round(dist, 5), key[0], key[1]))
        r["details"].sort(key=lambda x: x["_k"])
        if cross:
            r["notes"].append("另有 %d 对元件本体几何上重合/过近但分处顶底两层（3D 不冲突，按面判定不计违规）" % cross)
        r["notes"].append("本体=旋转矩形多边形，距离为两多边形最短距离；顶/底两层分别判定")
        return r

    def r3(self, plan):
        r = make_rule("R3", "微动本体投影（%s: %.1f x %.1fmm 旋转矩形）内不得有其他元件本体"
                      % (SW_MARK, SW_L, SW_W), None, "处")
        geoms = plan.bodies()
        for si in self.sw_idx:
            sg = geoms[si["idx"]]
            for j, c in enumerate(self.m.info):
                if c["idx"] == si["idx"]:
                    continue
                g = geoms[j]
                b1, b2 = sg.bounds, g.bounds
                if b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1]:
                    continue
                if not sg.intersects(g):
                    continue
                area = sg.intersection(g).area
                if area <= 1e-9:
                    continue
                key = tuple(sorted([si["d"], c["d"]]))
                detail = {"switch": si["d"], "other": c["d"], "other_fp": c["f"],
                          "area": round(area, 4), "other_layer": c["l"]}
                rule_add(r, detail, key, (-round(area, 6), si["d"], c["d"]))
        r["details"].sort(key=lambda x: x["_k"])
        r["notes"].append("按题设对全部层判定（机械件投影，与元件所在面无关）")
        return r

    # ---- R4 ---------------------------------------------------------------
    def _zone_rule(self, rid, title, zone_geom, zname, plan, only_top=False):
        r = make_rule(rid, title, None, "处")
        for i, c in enumerate(self.m.info):
            if only_top and c["l"] != 1:
                continue
            g = plan.body(i)
            if not g.intersects(zone_geom):
                continue
            area = g.intersection(zone_geom).area
            if area <= 1e-9:
                continue
            detail = {"d": c["d"], "zone": zname, "area": round(area, 4),
                      "area_frac_of_body": round(area / max(g.area, 1e-12), 4),
                      "layer": c["l"]}
            rule_add(r, detail, c["d"], (-round(area, 6), c["d"]))
        r["details"].sort(key=lambda x: x["_k"])
        return r

    def r4a(self, plan):
        r = self._zone_rule("R4a", "滚轮挖槽 8点多边形 x %.2f-%.2f / y %.2f-%.2f (全层, 真实几何, 非外接矩形)"
                            % (min(_p[0] for _p in CUTOUT), max(_p[0] for _p in CUTOUT), min(_p[1] for _p in CUTOUT), max(_p[1] for _p in CUTOUT)),
                            self.cut, "滚轮挖槽", plan)
        if not r["count"]:
            r["notes"].append("无元件本体与该矩形相交")
        return r

    def r4b(self, plan):
        r = self._zone_rule("R4b", "天线净空矩形 x %.1f-%.1f / y %.1f-%.1f (全层)"
                            % (ANT_KEEPOUT[0], ANT_KEEPOUT[2], ANT_KEEPOUT[1], ANT_KEEPOUT[3]),
                            self.ant, "天线净空", plan)
        if not r["count"]:
            r["notes"].append("无元件本体与该矩形相交")
        return r

    def r4c(self, plan):
        r = self._zone_rule("R4c", "电机区 圆心(%.2f,%.2f) R%.2fmm（仅 l==1 顶层元件）"
                            % (MOTOR_C[0], MOTOR_C[1], MOTOR_R), self.motor, "电机区", plan,
                            only_top=True)
        r["notes"].append("圆按 64 段/象限离散为多边形后求交，面积误差 < 0.03%")
        return r

    def r4d(self, plan):
        r = make_rule("R4d", "板框内 (x %.2f-%.2f / y %.2f-%.2f)：本体必须完全在板框内"
                      % (BOARD[0], BOARD[2], BOARD[1], BOARD[3]), None, "处")
        min_edge = None
        for i, c in enumerate(self.m.info):
            g = plan.body(i)
            if self.board.covers(g):
                dd = g.distance(self.board.boundary)
                min_edge = dd if min_edge is None else min(min_edge, dd)
                continue
            out_area = g.difference(self.board).area
            detail = {"d": c["d"], "outside_area": round(out_area, 4), "layer": c["l"]}
            rule_add(r, detail, c["d"], (-round(out_area, 6), c["d"]))
        r["details"].sort(key=lambda x: x["_k"])
        r["min_edge_dist"] = None if min_edge is None else round(min_edge, 4)
        if min_edge is not None:
            r["notes"].append("完全在板内元件的最小边距 %.3f mm" % min_edge)
        return r

    # ---- R5 ---------------------------------------------------------------
    def r5(self, plan):
        r = make_rule("R5", "元件本体距板框边界 >= %.2f mm（例外: %s）"
                      % (EDGE_CLEAR, ",".join(EDGE_EXEMPT)), EDGE_CLEAR, "处")
        for i, c in enumerate(self.m.info):
            if c["d"] in EDGE_EXEMPT:
                continue
            g = plan.body(i)
            dd = g.distance(self.board.boundary)
            if dd >= EDGE_CLEAR - 1e-12:
                continue
            detail = {"d": c["d"], "edge_dist": round(dd, 4),
                      "short_by": round(EDGE_CLEAR - dd, 4),
                      "outside": (not self.board.covers(g)), "layer": c["l"]}
            rule_add(r, detail, c["d"], (round(dd, 5), c["d"]))
        r["details"].sort(key=lambda x: x["_k"])
        present = [d for d in EDGE_EXEMPT if d in self.m.byD]
        absent = [d for d in EDGE_EXEMPT if d not in self.m.byD]
        r["notes"].append("例外件（已跳过，共 %d 个）: %s" % (len(present), ",".join(present)))
        if absent:
            r["notes"].append("例外清单中不存在的位号（忽略）: %s" % ",".join(absent))
        r["notes"].append("本体穿出板框时距离按 0 计（另见 R4d / 出板检查）")
        return r

    def r6(self, plan):
        r = make_rule("R6", "旋转角只允许 0/90/180/270（mod 360 归一后判定）", None, "处")
        for c in self.m.info:
            a = plan.angle(c["d"])
            a_n = a % 360.0
            if a_n > 360.0 - 1e-6:
                a_n = 0.0
            if min(abs(a_n - t) for t in (0.0, 90.0, 180.0, 270.0)) <= 1e-6:
                continue
            detail = {"d": c["d"], "angle_raw": round(c["r"], 4), "angle_effective": round(a, 4),
                      "angle_mod360": round(a_n, 4)}
            rule_add(r, detail, c["d"], (a_n, c["d"]))
        r["details"].sort(key=lambda x: x["_k"])
        r["notes"].append("原始数据中的 -90 归一为 270，属合法角度")
        return r

    def r7(self, plan):
        r = make_rule("R7", "坐标落在 %.1f mm 栅格上（偏离 > %.2f mm 即违规）" % (GRID, GRID_TOL),
                      GRID_TOL, "处")
        near = []
        for c in self.m.info:
            x, y = plan.pos(c["d"])
            ox = abs(x - round(x / GRID) * GRID)
            oy = abs(y - round(y / GRID) * GRID)
            off = max(ox, oy)
            if off > 1e-12:
                near.append({"d": c["d"], "x": round(x, 4), "y": round(y, 4),
                             "off_max": round(off, 4), "off_x": round(ox, 4),
                             "off_y": round(oy, 4)})
            if off <= GRID_TOL + 1e-12:
                continue
            detail = {"d": c["d"], "x": round(x, 4), "y": round(y, 4),
                      "off_x": round(ox, 4), "off_y": round(oy, 4),
                      "off_max": round(off, 4)}
            rule_add(r, detail, c["d"], (-round(off, 6), c["d"]))
        r["details"].sort(key=lambda x: x["_k"])
        near.sort(key=lambda q: -q["off_max"])
        r["near_miss"] = {">0.025mm": [q for q in near if q["off_max"] > 0.025][:25],
                          "count_gt_0.025": sum(1 for q in near if q["off_max"] > 0.025),
                          "count_gt_0": len(near),
                          "count_zero": len(self.m.info) - len(near),
                          "worst": near[:5]}
        r["notes"].append("判定量: 到最近 0.1mm 倍数的距离; 阈值 %.2fmm" % GRID_TOL)
        r["notes"].append(
            "口径提示: 到最近 0.1mm 倍数的距离数学上最大就是 %.3fmm(栅格半宽)，"
            "所以 '> %.2fmm' 这一题设口径几乎不会触发；为可读性附上更严的观察口径" % (GRID / 2, GRID_TOL))
        r["notes"].append(
            "附加观察(不计违规): 偏离>0.025mm 的元件 %d 个, 偏离>0 的 %d 个, 正好落在栅格上 %d 个；"
            "最差: %s" % (r["near_miss"]["count_gt_0.025"], r["near_miss"]["count_gt_0"],
                          r["near_miss"]["count_zero"],
                          ", ".join("%s=%s" % (q["d"], n2(q["off_max"], 4))
                                    for q in r["near_miss"]["worst"])))
        return r

    # ---- 汇总 --------------------------------------------------------------
    def run(self, plan):
        rules = {}
        for fn in ("r1", "r2", "r3", "r4a", "r4b", "r4c", "r4d", "r5", "r6", "r7"):
            r = getattr(self, fn)(plan)
            r["status"] = "fail" if r["count"] else "pass"
            rules[r["id"]] = r
        return rules


# ----------------------------------------------------------------------------- 美观评分
W_ALIGN, W_SPACING, W_ORIENT = 0.16, 0.14, 0.10
W_CLUSTER, W_DECAP, W_BUS, W_DENSITY = 0.14, 0.10, 0.20, 0.16
SAT_CLUSTER_A0, SAT_DECAP_D0, SAT_BUS_B0, SAT_DENS_S0 = 50.0, 10.0, 2000.0, 3.0


def axis_of(angle):
    """水平/垂直：旋转角按 180 取模；非 90 倍数（非法角）按垂直处理"""
    a = angle % 180.0
    return "H" if abs(a) < 1e-6 or abs(a - 180.0) < 1e-6 else "V"


def _cluster_1d(vals, tol):
    """把一维坐标按 <=tol 单链聚类; 返回 [[idx...], ...]"""
    idx = sorted(range(len(vals)), key=lambda i: vals[i])
    groups, cur = [], [idx[0]] if idx else []
    for k in range(1, len(idx)):
        if vals[idx[k]] - vals[idx[k - 1]] <= tol + 1e-12:
            cur.append(idx[k])
        else:
            groups.append(cur)
            cur = [idx[k]]
    if cur:
        groups.append(cur)
    return groups


def compute_metrics(model, plan):
    info = model.info
    n = len(info)
    m = {}

    # ---- 1) 行/列对齐率 ---------------------------------------------------
    buckets = defaultdict(list)
    for c in info:
        buckets[(c["f"], axis_of(plan.angle(c["d"])))].append(c)
    eligible = 0
    groups_all = []
    bucket_info = []
    for (fp, ax), cs in sorted(buckets.items()):
        if len(cs) >= 2:
            eligible += len(cs)
        if len(cs) < 2:
            continue
        coords = []
        for c in cs:
            x, y = plan.pos(c["d"])
            coords.append(y if ax == "H" else x)
        for g in _cluster_1d(coords, 0.3):
            if len(g) >= 2:
                # 成员按"排列方向"坐标排序（H 件沿 x 排、V 件沿 y 排），便于阅读间距
                a_i = 0 if ax == "H" else 1
                g = sorted(g, key=lambda i: plan.pos(cs[i]["d"])[a_i])
                groups_all.append({"fp": fp, "axis": ax,
                                   "members": [cs[i]["d"] for i in g],
                                   "line_value": round(coords[g[0]], 4),
                                   "dir_values": [round(plan.pos(cs[i]["d"])[a_i], 4) for i in g]})
            bucket_info.append({"fp": fp, "axis": ax, "size": len(g) if len(g) >= 2 else 1})
    groups_all.sort(key=lambda g: -len(g["members"]))
    aligned_comps = sum(len(g["members"]) for g in groups_all)
    m["align"] = {
        "groups": len(groups_all), "comps_in_groups": aligned_comps,
        "eligible_comps": eligible, "total_comps": n,
        "rate": (aligned_comps / eligible) if eligible else 1.0,
        "rate_all": aligned_comps / n if n else 0.0,
        "tol_mm": 0.3, "top_groups": groups_all[:8],
    }

    # ---- 2) 等间距度 ------------------------------------------------------
    # 口径说明: "对齐组"由中心线对齐定义(见上)，一个对齐组可能横跨整块板(例如同列元件
    # 间距 25mm)。这种"同列但不相邻"的间距不能代表排版整齐度，因此等间距度分两口径:
    #   (a) pooled_cv      全部相邻间距 (严格按题设口径)
    #   (b) pooled_cv_local 仅"近邻链"间距 (间距 <= LOCAL_GAP_MM 才算同排/同列相邻)
    # 美观子分使用 (b)，(b) 无样本时回退 (a)。
    LOCAL_GAP_MM = 20.0
    cvs, gaps, ng = [], [], 0
    lgaps = []
    worst = []
    for g in groups_all:
        if len(g["members"]) < 3:
            continue
        v = sorted(g["dir_values"])
        gg = [v[i + 1] - v[i] for i in range(len(v) - 1)]
        if not gg or sum(gg) <= 1e-9:
            continue
        ng += 1
        mean = sum(gg) / len(gg)
        var = sum((x - mean) ** 2 for x in gg) / len(gg)
        cv = math.sqrt(var) / mean if mean > 1e-9 else 0.0
        cvs.append(cv)
        gaps.extend(gg)
        lg = [x for x in gg if x <= LOCAL_GAP_MM]
        lgaps.extend(lg)
        lcv = None
        if len(lg) >= 2:
            lm = sum(lg) / len(lg)
            lv = sum((x - lm) ** 2 for x in lg) / len(lg)
            lcv = math.sqrt(lv) / lm if lm > 1e-9 else 0.0
        worst.append({"fp": g["fp"], "axis": g["axis"], "n": len(v),
                      "cv": round(cv, 4), "mean_gap": round(mean, 3),
                      "sd_gap": round(math.sqrt(var), 4),
                      "local_cv": (round(lcv, 4) if lcv is not None else None),
                      "n_local_gaps": len(lg)})
    worst.sort(key=lambda r: -(r["local_cv"] if r["local_cv"] is not None else r["cv"]))
    if gaps:
        gm = sum(gaps) / len(gaps)
        gsd = math.sqrt(sum((x - gm) ** 2 for x in gaps) / len(gaps))
        pooled = gsd / gm if gm > 1e-9 else 0.0
    else:
        gm, gsd, pooled = 0.0, 0.0, 0.0
    if len(lgaps) >= 2:
        lgm = sum(lgaps) / len(lgaps)
        lgsd = math.sqrt(sum((x - lgm) ** 2 for x in lgaps) / len(lgaps))
        pooled_local = lgsd / lgm if lgm > 1e-9 else 0.0
        local_fb = False
    else:
        pooled_local = pooled          # 无近邻样本 => 回退全间距口径（避免奖励"散得太开"）
        local_fb = True
    m["spacing"] = {"groups_evaluated": ng, "n_gaps": len(gaps),
                    "mean_cv": (sum(cvs) / len(cvs)) if cvs else 0.0,
                    "pooled_cv": pooled, "mean_gap_mm": round(gm, 4),
                    "sd_gap_mm": round(gsd, 4),
                    "local_gap_threshold_mm": LOCAL_GAP_MM,
                    "n_local_gaps": len(lgaps),
                    "pooled_cv_local": pooled_local,
                    "local_fallback": local_fb,
                    "local_mean_gap_mm": round(sum(lgaps) / len(lgaps), 4) if lgaps else 0.0,
                    "spacing_score_cv": pooled_local,
                    "worst_groups": worst[:5]}

    # ---- 3) 朝向一致性 ----------------------------------------------------
    byfp = defaultdict(list)
    for c in info:
        byfp[c["f"]].append(c)
    fp_rows, wsum, wtot = [], 0.0, 0
    for fp, cs in sorted(byfp.items(), key=lambda kv: -len(kv[1])):
        angs = [round((plan.angle(c["d"])) % 360.0, 6) for c in cs]
        cnt = defaultdict(int)
        for a in angs:
            cnt[a] += 1
        distinct = len(cnt)
        dom = max(cnt.values())
        fp_rows.append({"fp": fp, "n": len(cs), "distinct_angles": distinct,
                        "dominant_share": round(dom / len(cs), 4),
                        "angles": {("%g" % k): v for k, v in sorted(cnt.items())}})
        if len(cs) >= 2:
            wsum += dom
            wtot += len(cs)
    m["orientation"] = {"per_footprint": fp_rows,
                        "consistency": (wsum / wtot) if wtot else 1.0,
                        "n_angle_classes_total": sum(r["distinct_angles"] for r in fp_rows
                                                     if r["n"] >= 2),
                        "comps_multi": wtot}

    # ---- 4) 功能聚簇度（网络包围盒面积中位数 + 去耦电容到最近 IC 距离中位数） ----
    bodies = plan.bodies()
    areas = []
    for net, cs in model.net_comps.items():
        if len(cs) < 2:
            continue
        gs = [bodies[i] for i in cs]
        b = [gs[0].bounds]
        for g in gs[1:]:
            bb = g.bounds
            b.append(bb)
        x0 = min(t[0] for t in b)
        y0 = min(t[1] for t in b)
        x1 = max(t[2] for t in b)
        y1 = max(t[3] for t in b)
        areas.append((x1 - x0) * (y1 - y0))
    areas.sort()
    median_area = areas[len(areas) // 2] if areas else 0.0
    if len(areas) >= 2 and len(areas) % 2 == 0:
        median_area = 0.5 * (areas[len(areas) // 2 - 1] + areas[len(areas) // 2])

    ic_idx = [c for c in info if c["f"].startswith(IC_FP_PREFIX)]
    decap_idx = []
    for c in info:
        if not c["d"].startswith("C"):
            continue
        nets = model.comp_nets.get(c["idx"], set())
        if any(POWER_RE.match(x) for x in nets if x) and any(GND_RE.match(x) for x in nets if x):
            decap_idx.append(c)
    decap_src = "功率网+GND 网络的 C* 元件"
    if not decap_idx:
        decap_idx = [c for c in info if c["d"].startswith("C")]
        decap_src = "无功率/GND 判据命中，退化为全部 C* 元件"
    dd = []
    for c in decap_idx:
        if not ic_idx:
            break
        px, py = plan.pos(c["d"])
        dd.append(min(math.hypot(px - plan.pos(ic["d"])[0], py - plan.pos(ic["d"])[1])
                      for ic in ic_idx))
    dd.sort()
    med_dd = (dd[len(dd) // 2] if len(dd) % 2 else
              (0.5 * (dd[len(dd) // 2 - 1] + dd[len(dd) // 2]) if dd else 0.0)) if dd else 0.0
    m["cluster"] = {
        "nets_used": len(areas),
        "median_net_bbox_area_mm2": round(median_area, 3),
        "mean_net_bbox_area_mm2": round(sum(areas) / len(areas), 3) if areas else 0.0,
        "largest_net_bbox_area_mm2": round(areas[-1], 3) if areas else 0.0,
        "n_ic": len(ic_idx), "n_decap": len(decap_idx), "decap_rule": decap_src,
        "median_decap_to_ic_mm": round(med_dd, 4),
        "max_decap_to_ic_mm": round(dd[-1], 4) if dd else 0.0,
    }

    # ---- 5) 估算总线长 ----------------------------------------------------
    P = plan.pad_points()
    tot = 0.0
    rows = []
    for net, pidx in model.net_pads.items():
        if not pidx:
            continue
        xs = P[pidx, 0]
        ys = P[pidx, 1]
        hp = float(xs.max() - xs.min()) + float(ys.max() - ys.min())
        tot += hp
        rows.append({"net": net or "(无网络)", "half_perimeter_mm": round(hp, 3),
                     "n_pads": len(pidx)})
    rows.sort(key=lambda r: -r["half_perimeter_mm"])
    m["bus"] = {"total_half_perimeter_mm": round(tot, 3), "nets": len(rows),
                "top_nets": rows[:5]}

    # ---- 6) 密度均衡 ------------------------------------------------------
    counts = defaultdict(int)
    outside = 0
    for c in info:
        x, y = plan.pos(c["d"])
        gx = int(math.floor((x - BOARD[0]) / 10.0))
        gy = int(math.floor((y - BOARD[1]) / 10.0))
        if x < BOARD[0] or x > BOARD[2] or y < BOARD[1] or y > BOARD[3]:
            outside += 1
            continue
        counts[(gx, gy)] += 1
    nx = int(math.ceil((BOARD[2] - BOARD[0]) / 10.0))
    ny = int(math.ceil((BOARD[3] - BOARD[1]) / 10.0))
    grid = [counts.get((i, j), 0) for i in range(nx) for j in range(ny)]
    mean = sum(grid) / len(grid) if grid else 0.0
    var = sum((v - mean) ** 2 for v in grid) / len(grid) if grid else 0.0
    m["density"] = {"grid_mm": 10, "cells": len(grid), "mean": round(mean, 3),
                    "std": round(math.sqrt(var), 4),
                    "cv": round(math.sqrt(var) / mean, 4) if mean > 1e-9 else 0.0,
                    "max_cell": max(grid) if grid else 0, "empty_cells": sum(1 for v in grid if v == 0),
                    "comps_outside_board": outside}

    # ---- 子分 & 综合 ------------------------------------------------------
    s = {}
    s["align"] = m["align"]["rate"]
    s["spacing"] = 1.0 / (1.0 + min(m["spacing"]["spacing_score_cv"], 5.0))
    s["orientation"] = m["orientation"]["consistency"]
    s["cluster"] = 1.0 / (1.0 + m["cluster"]["median_net_bbox_area_mm2"] / SAT_CLUSTER_A0)
    s["decap"] = (1.0 / (1.0 + m["cluster"]["median_decap_to_ic_mm"] / SAT_DECAP_D0)) \
        if m["cluster"]["n_decap"] else 1.0
    s["bus"] = 1.0 / (1.0 + m["bus"]["total_half_perimeter_mm"] / SAT_BUS_B0)
    s["density"] = 1.0 / (1.0 + m["density"]["std"] / SAT_DENS_S0)
    comp = (W_ALIGN * s["align"] + W_SPACING * s["spacing"] + W_ORIENT * s["orientation"]
            + W_CLUSTER * s["cluster"] + W_DECAP * s["decap"] + W_BUS * s["bus"]
            + W_DENSITY * s["density"])
    m["subscores"] = {k: round(v, 5) for k, v in s.items()}
    m["composite"] = round(100.0 * comp, 3)
    return m


# 指标显示定义: (key path, 名称, 方向, 权重, 单位, 说明)
METRIC_DEFS = [
    ("align.rate", "行/列对齐率 (同封装同朝向, 中心线差<=0.3mm)", "up", W_ALIGN, "%", "同封装同朝向元件落入对齐组的比例"),
    ("spacing.pooled_cv_local", "等间距度 (近邻链相邻间距 标准差/平均)", "down", W_SPACING, "", "仅统计 <=20mm 的同排/同列相邻件"),
    ("orientation.consistency", "朝向一致性 (最大同角类占比)", "up", W_ORIENT, "%", "越大越统一"),
    ("cluster.median_net_bbox_area_mm2", "功能聚簇: 网络包围盒面积中位数", "down", W_CLUSTER, "mm2", "越小越紧凑"),
    ("cluster.median_decap_to_ic_mm", "去耦电容 -> 最近 IC 距离中位数", "down", W_DECAP, "mm", "越小越紧凑"),
    ("bus.total_half_perimeter_mm", "估算总线长 (各网络焊盘包围盒半周长之和)", "down", W_BUS, "mm", "布线长度代理指标"),
    ("density.std", "密度均衡: 10x10mm 格内元件数标准差", "down", W_DENSITY, "", "越小越均衡"),
]

EXTRA_METRIC_DEFS = [
    ("spacing.pooled_cv", "等间距度(全间距口径, 含跨板远距)", "down", 0.0, "", ""),
    ("spacing.n_local_gaps", "等间距近邻样本段数", "up", 0.0, "段", ""),
    ("orientation.n_angle_classes_total", "旋转角种类数(多件封装合计)", "down", 0.0, "", "越小越统一"),
    ("align.groups", "对齐组数量", "up", 0.0, "组", ""),
    ("align.comps_in_groups", "对齐组涉及元件数", "up", 0.0, "个", ""),
    ("align.eligible_comps", "有对齐可能的元件数(同封装同朝向>=2)", "none", 0.0, "个", ""),
    ("cluster.nets_used", "参与聚簇统计的网络数(>=2 元件)", "none", 0.0, "个", ""),
    ("density.max_cell", "最挤格子元件数", "down", 0.0, "个", ""),
    ("density.empty_cells", "空格子数", "down", 0.0, "个", ""),
    ("density.comps_outside_board", "原点在板框外的元件数", "down", 0.0, "个", ""),
]


def dig(d, path):
    cur = d
    for k in path.split("."):
        cur = cur[k]
    return cur


def verdict(a, b, direction, rel_tol=0.005, abs_tol=1e-9):
    if direction == "none":
        return "参考"
    if a is None or b is None:
        return "-"
    if abs(b - a) <= max(abs_tol, abs(a) * rel_tol):
        return "持平"
    if direction == "up":
        return "更好" if b > a else "更差"
    return "更好" if b < a else "更差"


# ----------------------------------------------------------------------------- 文本渲染
def render_text(ctx, limit=25):
    L = []
    A = L.append
    bar = "=" * 100
    sub = "-" * 100
    A(bar)
    A(" PCB 摆放规则验证 + 美观评分   [place_verify.py  独立离线工具]")
    A(" 生成时间: %s" % ctx["time"])
    A(" 元件基准: %s" % ctx["comps_path"])
    A(" 焊盘实测: %s" % ctx["live_path"])
    A(" 验证方案: %s" % ctx["plan_desc"])
    m = ctx["model"]
    A(" 规模: 元件 %d, 焊盘 %d, 网络 %d | 焊盘->元件 全局最优指派: 平均 %.2fmm / 最大 %.2fmm / 层冲突 %d"
      % (len(m.info), len(m.pads), len(m.net_pads), m.assign_stats["mean_dist_mm"],
         m.assign_stats["max_dist_mm"], m.assign_stats["layer_penalized"]))
    A(" 几何模型: 本体=旋转矩形多边形(shapely); 焊盘=中心点; 电机区=64段/象限离散圆; 交点/面积=多边形布尔运算")
    if m.warnings:
        A(" 输入提示: %s" % " | ".join(m.warnings[:6]))
    A(bar)

    ps = ctx["plan_summary"]
    A("[方案概览]")
    if ps["unchanged"]:
        A("  方案为空或全部位移为 0 => 与原始摆放完全一致")
    else:
        A("  位移元件 %d 件 (其中 %d 件位移 < 0.1mm, %d 件 < 0.01mm) | 旋转变更 %d 件"
          % (ps["n_moved"], ps["n_sub_0p1mm"], ps["n_sub_0p01mm"], ps["n_rotated"]))
        A("  最大位移 %.3f mm (%s) | 位移总和 %.3f mm | 平均 %.3f mm"
          % (ps["max_disp_mm"], ps["top"][0]["d"] if ps["top"] else "-",
             ps["total_disp_mm"], ps["mean_disp_mm"]))
        if ps["negligible"]:
            A("  >> 判定: 该方案【几乎没有变化】(最大位移 %.3f mm < 0.10 mm)，规则与美观指标预期基本不变"
              % ps["max_disp_mm"])
        for r in ps["top"][:5]:
            A("     %-6s dx=%+8.4f dy=%+8.4f  |d|=%.4f mm" % (r["d"], r["dx"], r["dy"], r["disp"]))
        for r in ps["rot_changed"][:5]:
            A("     旋转 %-6s %g -> %g 度" % (r["d"], r["from"], r["to"]))
    A("")

    A(bar)
    A(" 一、规则检查 (每节: 结论先行, 明细最多 %d 条, 超出只给总数)" % limit)
    A(bar)
    rules = ctx["rules"]
    order = ["R1", "R2", "R3", "R4a", "R4b", "R4c", "R4d", "R5", "R6", "R7"]
    tot = 0
    for rid in order:
        r = rules[rid]
        tot += r["count"]
        flag = "[通过]" if r["count"] == 0 else "[违规 %d 处]" % r["count"]
        diff = ctx["rule_diff"].get(rid)
        dtxt = ""
        if diff and not ctx["baseline_mode"]:
            dtxt = "   (对比原始: 新增 %d / 消除 %d)" % (diff["added"], diff["removed"])
        A("")
        A("%s %s" % (rid, r["title"]))
        A("  结论: %s%s" % (flag, dtxt))
        for nt in r["notes"]:
            A("  * %s" % nt)
        if r["count"]:
            show = r["details"][:limit]
            A("  明细 (最多 %d 条 / 共 %d 条):" % (limit, r["count"]))
            for k, d in enumerate(show, 1):
                A("   %2d) %s" % (k, _fmt_detail(rid, d)))
            if r["count"] > len(show):
                A("   ... 其余 %d 条见 --json 输出" % (r["count"] - len(show)))
    A("")
    A(" 规则合计违规: %d 处" % tot)

    # 出板单独提示
    ob = ctx["out_of_board"]
    A("")
    A("[单独检查] 是否有元件出板（本体任一部分在板框 x %.2f-%.2f / y %.2f-%.2f 之外）: %s"
      % (BOARD[0], BOARD[2], BOARD[1], BOARD[3],
         "无" if not ob["count"] else "有 %d 个" % ob["count"]))
    if ob["count"]:
        A("   %s" % ", ".join("%s(出板面积 %.2fmm2)" % (x["d"], x["outside_area"])
                              for x in ob["details"][:limit]))
        if ob["count"] > limit:
            A("   ... 其余 %d 个见 --json 输出" % (ob["count"] - limit))
    A("   注: R5 例外件不参与 R5 判距，但出板检查对所有元件无条件执行")

    A("")
    A(bar)
    A(" 二、美观评分 (基于验证后的绝对位置 = 原始位置 + 位移; 同时给出原始摆放对照)")
    A(bar)
    mo, mn = ctx["metrics_orig"], ctx["metrics_new"]
    A("%-46s %14s %14s %8s" % ("指标", "原始摆放", "新方案", "对比"))
    A(sub)
    for path, name, dr, w, unit, _note in METRIC_DEFS:
        a = dig(mo, path) if mo else None
        b = dig(mn, path)
        A("%-46s %14s %14s %8s" % (name[:46], _fmtv(a, unit), _fmtv(b, unit),
                                   verdict(a, b, dr)))
    A(sub)
    for path, name, dr, w, unit, _note in EXTRA_METRIC_DEFS:
        a = dig(mo, path) if mo else None
        b = dig(mn, path)
        A("%-46s %14s %14s %8s" % (name[:46], _fmtv(a, unit), _fmtv(b, unit),
                                   verdict(a, b, dr)))
    A(sub)
    A("%-46s %14s %14s %8s" % ("美观综合分 (0-100, 越大越好)",
                               n2(mo["composite"], 2) if mo else "-", n2(mn["composite"], 2),
                               _cmp_up(mo["composite"] if mo else None, mn["composite"])))
    A("")
    A(" 综合分权重: 对齐 %.2f / 间距均匀 %.2f / 朝向 %.2f / 聚簇 %.2f / 去耦临近 %.2f / 总线长 %.2f / 密度 %.2f"
      % (W_ALIGN, W_SPACING, W_ORIENT, W_CLUSTER, W_DECAP, W_BUS, W_DENSITY))
    A(" 子分(0-1, 越大越好) 原始 %s" % _sub_str(mo))
    A(" 子分(0-1, 越大越好) 新方案 %s" % _sub_str(mn))

    # 明细
    A("")
    A(" 明细: 对齐组 (新方案) / 等间距最差组 / 朝向分布 / 聚簇 / 总线长 / 密度")
    al = mn["align"]
    A("  对齐: 组 %d 个, 涉及 %d 件, 可参与元件 %d 件 (同封装同朝向>=2), 占比 %.1f%% (占全部 %d 件 %.1f%%)"
      % (al["groups"], al["comps_in_groups"], al["eligible_comps"],
         100 * al["rate"], al["total_comps"], 100 * al["rate_all"]))
    for g in al["top_groups"][:6]:
        A("     %-34s %s 线=%-9s 成员(按排列方向): %s"
          % (g["fp"][:34], g["axis"], n2(g["line_value"], 3),
             ", ".join(g["members"][:8]) + (" ..." if len(g["members"]) > 8 else "")))
    sp = mn["spacing"]
    A("  等间距: 评估组 %d 个 / 间距段 %d (其中近邻链 <=%gmm 的 %d 段)"
      % (sp["groups_evaluated"], sp["n_gaps"], sp["local_gap_threshold_mm"], sp["n_local_gaps"]))
    A("          近邻口径 CV=%.4f (间距均值 %.3fmm%s) | 全间距口径 CV=%.4f (间距均值 %.3fmm, 标准差 %.3fmm)"
      % (sp["pooled_cv_local"], sp["local_mean_gap_mm"],
         ", 无近邻样本已回退全间距" if sp["local_fallback"] else "",
         sp["pooled_cv"], sp["mean_gap_mm"], sp["sd_gap_mm"]))
    for w in sp["worst_groups"][:4]:
        A("     最差组 %-30s %s n=%d 近邻CV=%s (近邻 %d 段) 全间距CV=%.4f 均值间距=%.3fmm"
          % (w["fp"][:30], w["axis"], w["n"],
             ("%.4f" % w["local_cv"]) if w["local_cv"] is not None else "无样本",
             w["n_local_gaps"], w["cv"], w["mean_gap"]))
    ori = mn["orientation"]
    A("  朝向: 最大同角类占比(多件封装加权) %.1f%%; 多件封装角度种类合计 %d"
      % (100 * ori["consistency"], ori["n_angle_classes_total"]))
    for r in ori["per_footprint"]:
        if r["n"] >= 2:
            A("     %-34s n=%-3d 角度种类=%d 主角度占比=%.0f%%  %s"
              % (r["fp"][:34], r["n"], r["distinct_angles"], 100 * r["dominant_share"],
                 _angle_str(r["angles"], r["n"])))
    cl = mn["cluster"]
    A("  聚簇: 网络包围盒面积中位数 %.2f mm2 (均值 %.2f, 最大 %.2f, 参与网络 %d 个)"
      % (cl["median_net_bbox_area_mm2"], cl["mean_net_bbox_area_mm2"],
         cl["largest_net_bbox_area_mm2"], cl["nets_used"]))
    A("  去耦: 判据=%s => %d 个; 到最近 IC(%d 个) 距离中位数 %.3f mm (最大 %.3f mm)"
      % (cl["decap_rule"], cl["n_decap"], cl["n_ic"], cl["median_decap_to_ic_mm"],
         cl["max_decap_to_ic_mm"]))
    bu = mn["bus"]
    A("  总线长代理: 全网络焊盘包围盒半周长之和 %.1f mm (网络 %d 个); 最长 5 个: %s"
      % (bu["total_half_perimeter_mm"], bu["nets"],
         ", ".join("%s=%.1f" % (r["net"], r["half_perimeter_mm"]) for r in bu["top_nets"])))
    de = mn["density"]
    A("  密度: %d mm 格 %d 格, 均值 %.2f 个/格, 标准差 %.3f, 最挤 %d 个, 空格 %d 个, 板外原点 %d 个"
      % (de["grid_mm"], de["cells"], de["mean"], de["std"], de["max_cell"],
         de["empty_cells"], de["comps_outside_board"]))
    A("")
    A(bar)
    return "\n".join(L)


def _fmtv(v, unit):
    if v is None:
        return "-"
    if unit == "%":
        return "%.1f%%" % (100.0 * v)
    if unit in ("mm2", "mm"):
        return "%.3f %s" % (v, unit)
    if float(v).is_integer():
        return "%d" % int(v)
    return n2(v, 4)


def _cmp_up(a, b):
    if a is None:
        return "-"
    if abs(b - a) < 1e-9:
        return "持平"
    return "更好" if b > a else "更差"


def _sub_str(m):
    if not m:
        return "(无原始对照)"
    s = m["subscores"]
    return " ".join("%s=%.3f" % (k, s[k]) for k in
                    ("align", "spacing", "orientation", "cluster", "decap", "bus", "density"))


def _angle_str(angles, n):
    items = sorted(angles.items(), key=lambda kv: -kv[1])[:4]
    return " ".join("%s deg x%d" % (k, v) for k, v in items)


def _fmt_detail(rid, d):
    if rid == "R1":
        return "中心距 %s mm (差限 %s)  %-12s <-> %-12s  net %s/%s" % (
            n2(d["dist"], 4), n2(d["gap_to_limit"], 4), d["a"], d["b"],
            d["net_a"] or "-", d["net_b"] or "-")
    if rid == "R2":
        return "本体间隙 %s mm (差 %s, 层%d)  %s <-> %s" % (
            n2(d["gap"], 4), n2(d["short_by"], 4), d["layer"], d["a"], d["b"])
    if rid == "R3":
        return "%s 与 %s 本体相交 %s mm2 (占微动本体 %.1f%%, 对方层%d)" % (
            d["switch"], d["other"], n2(d["area"], 4),
            100.0 * d["area"] / (SW_L * SW_W), d["other_layer"])
    if rid in ("R4a", "R4b", "R4c"):
        return "%s 进入禁区 '%s' %s mm2 (占本体 %.1f%%, 层%d)" % (
            d["d"], d["zone"], n2(d["area"], 4), 100 * d["area_frac_of_body"], d["layer"])
    if rid == "R4d":
        return "%s 出板面积 %s mm2 (层%d)" % (d["d"], n2(d["outside_area"], 4), d["layer"])
    if rid == "R5":
        return "%s 距板边 %s mm (差 %s)%s" % (
            d["d"], n2(d["edge_dist"], 4), n2(d["short_by"], 4),
            "  [已穿出板框]" if d["outside"] else "")
    if rid == "R6":
        return "%s 旋转角 %s 度 (原始 %s, mod360 %s)" % (
            d["d"], n2(d["angle_effective"], 3), n2(d["angle_raw"], 3), n2(d["angle_mod360"], 3))
    if rid == "R7":
        return "%s 位置 (%s, %s) 偏离栅格 %s mm (dx %s, dy %s)" % (
            d["d"], n2(d["x"], 4), n2(d["y"], 4), n2(d["off_max"], 4),
            n2(d["off_x"], 4), n2(d["off_y"], 4))
    return str(d)


# ----------------------------------------------------------------------------- 方案文件解析
def parse_plan_file(path):
    """健壮解析方案 JSON。返回 (moves, rots, notes)"""
    notes = []
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        raw = fh.read()
    data = json.loads(raw)
    moves, rots = {}, {}

    def take_move(d, v):
        if d is None:
            return
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            a, b = fnum(v[0]), fnum(v[1])
        elif isinstance(v, dict):
            a = fnum(v.get("dx", v.get("x", v.get("dxx"))))
            b = fnum(v.get("dy", v.get("y", v.get("dyy"))))
        else:
            a = b = None
        if a is None or b is None:
            notes.append("位移项 %s=%r 无法解析，已忽略" % (d, v))
            return
        moves[str(d)] = (a, b)

    def take_rot(d, v):
        if d is None:
            return
        a = fnum(v)
        if a is None and isinstance(v, dict):
            a = fnum(v.get("r", v.get("rot", v.get("angle"))))
        if a is None:
            notes.append("旋转项 %s=%r 无法解析，已忽略" % (d, v))
            return
        rots[str(d)] = a

    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            for row in data:
                d = row.get("d", row.get("designator", row.get("ref")))
                if "r" in row or "rot" in row or "angle" in row:
                    take_rot(d, row.get("r", row.get("rot", row.get("angle"))))
                if any(k in row for k in ("dx", "dy", "x", "y")):
                    take_move(d, row)
        else:
            notes.append("方案文件是数组但元素不是对象，已按空方案处理")
    elif isinstance(data, dict):
        found = False
        for k in ("moves", "move", "deltas", "delta", "offsets"):
            if isinstance(data.get(k), dict):
                for d, v in data[k].items():
                    take_move(d, v)
                found = True
            elif isinstance(data.get(k), list):
                for row in data[k]:
                    if isinstance(row, dict):
                        take_move(row.get("d"), row)
                found = True
        for k in ("rot", "rots", "rotation", "rotations", "angles"):
            if isinstance(data.get(k), dict):
                for d, v in data[k].items():
                    take_rot(d, v)
                found = True
        if not found:
            # 可能是 {"C1":[0.1,0.2], "U1":{"dx":..,"dy":..}}
            for d, v in data.items():
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    take_move(d, v)
                elif isinstance(v, dict) and any(x in v for x in ("dx", "dy", "x", "y")):
                    take_move(d, v)
                else:
                    notes.append("未知字段 %s 已忽略" % d)
        else:
            known = set(["moves", "move", "deltas", "delta", "offsets", "rot", "rots",
                         "rotation", "rotations", "angles"])
            for d in data:
                if d not in known:
                    notes.append("未知字段 %s 已忽略" % d)
    else:
        notes.append("方案文件顶层既不是对象也不是数组，已按空方案处理")
    return moves, rots, notes


# ----------------------------------------------------------------------------- 主流程
def verify(model, plan, baseline=None):
    checker = Checker(model)
    rules = checker.run(plan)
    metrics = compute_metrics(model, plan)
    out = {"rules": rules, "metrics": metrics}
    if baseline is not None:
        out["rule_diff"] = {rid: {"added": len(rules[rid]["sig"] - baseline["rules"][rid]["sig"]),
                                  "removed": len(baseline["rules"][rid]["sig"] - rules[rid]["sig"])}
                            for rid in rules}
    return out


def rule_json(r, limit_detail=None):
    det = r["details"]
    if limit_detail:
        det = det[:limit_detail]
    out = {"id": r["id"], "title": r["title"], "limit": r["limit"], "unit": r["unit"],
           "count": r["count"], "status": r["status"], "notes": r["notes"],
           "violations": jfloats([{k: v for k, v in d.items() if not k.startswith("_")}
                                  for d in det]),
           "violations_truncated": max(0, r["count"] - len(det))}
    if "near_miss" in r:
        out["near_miss"] = jfloats(r["near_miss"])
    if r.get("min_edge_dist") is not None:
        out["min_edge_dist"] = r["min_edge_dist"]
    return out


def main(argv=None):
    _reconf(sys.stdout)
    _reconf(sys.stderr)
    ap = argparse.ArgumentParser(
        description="独立的 PCB 摆放规则验证 + 美观评分 (纯离线, 只读输入)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("placement", nargs="?", default=None,
                    help="待验证方案 JSON (moves/rot)；省略则只验证原始摆放")
    ap.add_argument("--json", dest="json_out", default=None, help="结构化结果输出 JSON 路径")
    ap.add_argument("--comps", default=os.path.join(HERE, "comps3.json"))
    ap.add_argument("--live", default=os.path.join(HERE, "live.json"))
    ap.add_argument("--limit", type=int, default=25, help="文本明细上限 (默认 25)")
    ap.add_argument("--strict", action="store_true", help="有违规时退出码 1")
    ap.add_argument("--quiet", action="store_true", help="不打印文本 (配合 --json)")
    args = ap.parse_args(argv)

    t0 = time.time()
    if not os.path.isfile(args.comps):
        sys.stderr.write("找不到元件基准文件: %s\n" % args.comps)
        return 2
    if not os.path.isfile(args.live):
        sys.stderr.write("找不到焊盘几何文件: %s\n" % args.live)
        return 2
    model = Model(args.comps, args.live)

    baseline = verify(model, Plan(model, name="原始摆放"))
    baseline_mode = True
    plan = Plan(model, name="原始摆放")
    plan_notes = []
    if args.placement:
        if not os.path.isfile(args.placement):
            globals()["_INPUT_ERR"] = True
            sys.stderr.write("[错误] 方案文件不存在: %s => 退化为只验证原始摆放 (退出码 2)\n" % args.placement)
            plan_notes.append("方案文件不存在，已退化为原始摆放")
            baseline_mode = True
        else:
            try:
                mv, rt, plan_notes = parse_plan_file(args.placement)
                unknown = [d for d in list(mv) + list(rt) if d not in model.byD]
                if unknown:
                    plan_notes.append("方案中 %d 个位号不在板上，已忽略: %s"
                                      % (len(unknown), ",".join(sorted(set(unknown))[:10])))
                    for d in unknown:
                        mv.pop(d, None)
                        rt.pop(d, None)
                plan = Plan(model, mv, rt, name=os.path.basename(args.placement))
                baseline_mode = False
                plan_notes.append("已解析: 位移项 %d 个, 旋转项 %d 个" % (len(mv), len(rt)))
            except Exception as e:
                globals()["_INPUT_ERR"] = True
                sys.stderr.write("[错误] 方案文件解析失败(%s) => 退化为只验证原始摆放 (退出码 2)\n" % e)
                plan_notes = ["方案文件解析失败: %s" % e]
    else:
        plan_notes.append("未指定方案文件 => 只验证原始摆放")

    cur = verify(model, plan, baseline=baseline)
    rules = cur["rules"]
    out_of_board = rules["R4d"]

    ctx = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model,
        "comps_path": args.comps, "live_path": args.live,
        "plan_desc": ("无方案文件（原始摆放 baseline）" if not args.placement
                      else "%s%s" % (args.placement, "" if not baseline_mode else "（未生效）")),
        "plan_notes": plan_notes,
        "rules": rules, "rule_diff": cur.get("rule_diff", {}),
        "baseline_mode": baseline_mode, "out_of_board": out_of_board,
        "metrics_orig": baseline["metrics"], "metrics_new": cur["metrics"],
        "plan_summary": plan.summary(),
    }

    if not args.quiet:
        txt = render_text(ctx, limit=args.limit)
        if plan_notes and args.placement and not baseline_mode:
            txt = txt.replace("[方案概览]", "[方案概览]\n  解析: %s" % " | ".join(plan_notes), 1)
        print(txt)

    if args.json_out:
        payload = {
            "tool": "place_verify.py",
            "generated": ctx["time"],
            "inputs": {"comps": args.comps, "live": args.live,
                       "placement": args.placement, "baseline_mode": baseline_mode},
            "model": {"n_components": len(model.info), "n_pads": len(model.pads),
                      "n_nets": len(model.net_pads),
                      "pad_assignment": jfloats(model.assign_stats),
                      "footprint_sizes": jfloats(model.fp_sizes),
                      "warnings": model.warnings},
            "plan": {"path": args.placement, "notes": plan_notes,
                     "summary": jfloats(plan.summary())},
            "rules": {rid: rule_json(rules[rid]) for rid in rules},
            "rules_summary": {rid: rules[rid]["count"] for rid in rules},
            "rule_total": sum(rules[rid]["count"] for rid in rules),
            "rule_diff": jfloats(cur.get("rule_diff", {})),
            "out_of_board": {"count": out_of_board["count"],
                             "components": jfloats([{k: v for k, v in d.items()
                                                     if not k.startswith("_")}
                                                    for d in out_of_board["details"]])},
            "aesthetics": {
                "original": jfloats(baseline["metrics"]),
                "new": jfloats(cur["metrics"]),
                "composite": {"original": baseline["metrics"]["composite"],
                              "new": cur["metrics"]["composite"],
                              "delta": round(cur["metrics"]["composite"]
                                             - baseline["metrics"]["composite"], 4),
                              "other_is_better": cur["metrics"]["composite"]
                              < baseline["metrics"]["composite"]},
                "verdict": {path: verdict(dig(baseline["metrics"], path),
                                         dig(cur["metrics"], path), dr)
                            for path, name, dr, w, unit, note in METRIC_DEFS},
                "weights": {"align": W_ALIGN, "spacing": W_SPACING, "orientation": W_ORIENT,
                            "cluster": W_CLUSTER, "decap": W_DECAP, "bus": W_BUS,
                            "density": W_DENSITY},
                "metric_defs": [{"path": p, "name": nm, "direction": dr, "weight": w,
                                 "unit": u, "note": nt}
                                for p, nm, dr, w, u, nt in METRIC_DEFS + EXTRA_METRIC_DEFS],
                "subscores_original": baseline["metrics"]["subscores"],
                "subscores_new": cur["metrics"]["subscores"],
            },
            "geometry_model": {
                "body": "旋转矩形多边形 rotate(box(Lx,Ly),angle,origin=comp_origin), shapely 2.x",
                "pad": "焊盘中心点(随所属元件平移/旋转), R1 为中心距规则",
                "motor_zone": "Point(10.160, 19.177).buffer(9.51, quad_segs=64) 离散多边形",
                "pad_to_comp": "全局最优指派(scipy linear_sum_assignment), 层约束 penalty=100mm",
                "footprint_size_source": "内置尺寸表(覆盖本项目全部封装名); 未命中用 _L..-W.. 正则, 再兜底",
                "aesthetics": "对齐=中心线<=0.3mm 单链聚类; 间距=组内相邻间距 std/mean; "
                              "聚簇=网络内元件本体包围盒面积中位数; 总线长=各网络焊盘包围盒半周长之和; "
                              "密度=10x10mm 格计数标准差",
            },
        }
        d = os.path.dirname(os.path.abspath(args.json_out))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with io.open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(jfloats(payload), ensure_ascii=False, indent=1))
        if not args.quiet:
            print("\n结构化结果已写入: %s" % args.json_out)

    if not args.quiet and not args.json_out:
        print("\n(用 --json <路径> 可导出结构化结果: 规则计数 + 每条违规明细 + 美观指标)")

    total = sum(rules[rid]["count"] for rid in rules)
    # 退出码: 0=无违规  1=有规则违规  2=输入错误(方案文件缺失/解析失败)
    if globals().get("_INPUT_ERR"):
        return 2
    if total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
