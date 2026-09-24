#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
place_elec.py  --  PCB 摆放「电气性能评分器」（纯离线 / 只读输入 / 不联网）

用法
----
    python place_elec.py [方案.json] [--json out.json] [--limit N]

    python place_elec.py                          # 评分 comps3.json 当前摆放
    python place_elec.py placement_new.json       # 评分"当前摆放 + moves/rot"方案, 并与当前对照
    python place_elec.py placement_new.json --json elec.json --limit 40

只读文件:
    comps3.json   元件基准表  {"d":位号,"f":封装,"x":mm,"y":mm,"r":deg,"l":层,"p":[...]}
    live.json     焊盘实测    pads: [net, layer, x_mm, y_mm, "RECT,w,h,c"|..., hole, padnum, rot_rad]
                              vias: [uuid, net, x, y, dia, drill]
                              (尺寸单位 mil, 1mil = 0.0254mm, layer=12 为通孔/两层皆可)
本脚本从不写回上述任何文件, 也不写 placement_new.json。输出只走 stdout / --json 指定的路径。

与 place_verify.py 的一致性（硬要求）
------------------------------------
1) 焊盘 -> 元件归属: 直接复用 place_verify.Model（其 assign_pads() 用
   scipy.optimize.linear_sum_assignment 做**全局最优指派**，代价 = 焊盘中心到元件原点距离，
   层不匹配 +100mm 硬惩罚，layer=12 两层合法）。本文件另存一份同口径的迷你实现
   (MiniModel) 作为 import 失败时的兜底，并在运行时**逐焊盘比对**两者的归属与总代价，
   把比对结果写进报告与 --json（consistency 段），任何不一致都会显式报出。
   之所以绝不用贪心归属: 贪心会被近邻抢槽导致错配，历史上产生过"幻影违规"。
2) 元件本体几何: 直接用 place_verify.Plan.body() 旋转矩形多边形
   rotate(box(cx±Lx/2, cy±Wy/2), angle, origin=(cx,cy))，
   焊盘点用 place_verify.Plan.pad_points()（焊盘随所属元件平移/旋转），
   不另写一套近似几何。
3) 板框/天线净空/禁区常量取自 place_verify（BOARD / ANT_KEEPOUT），避免两套坐标口径。

七项指标的分级阈值与工程依据
----------------------------
（报告里每节开头会重复打印同样的依据文本，代码里注释在对应函数上方）

[1] 去耦有效性   ≤3mm 绿 / 3–5mm 黄 / >5mm 红, 同网络无电容 = 红
    依据: 去耦回路的有效性由「IC 电源脚 → 电容 → 地」回路电感决定; 1mm 走线约 0.6–1nH,
    3mm ≈ 2–3nH, 与 0402/0603 陶瓷电容自身 ESL(≈0.6–1nH)同量级, 尚可接受; >5mm 时引线
    电感主导, 10MHz 以上 PDN 阻抗抬升并把谐振点推低, 判红。业界常用做法是"电容放在
    电源脚 2–3mm 内"(TI/ADI 电源布局指南、IPC-7351 焊盘/走线实践)。
    注: 判定对象只取"电源脚网络"——网络名命中 VCC/VDD/AVDD/PVDD/+5V/1V1/VBUS/VREG/IP+5V…
    的, 或"该脚网络非地且网络上有电容(^C\\d+$)且不是晶振/RF/信号网"的; 晶振负载电容、
    RF 匹配电容不算去耦(否则会把 XIN 这类高阻节点误判成电源脚, 产生假红)。

[2] IC 地脚就近性  ≤3mm 绿 / 3–5mm 黄 / >5mm 红
    依据: 4 层板叠层规划 INNER_1 = 完整 GND 平面, 地回流靠"地脚 → 就近过孔 → 内层平面"。
    地脚到最近过孔/其它元件地焊盘的距离就是回流路径长度; ≤3mm 时回流可认为经平面就近返回,
    >5mm 时地电流被迫在外层长距离流动, 抬高共地阻抗并形成辐射环(与开关/大电流回路耦合)。

[3] DC-DC 热环路  MST 总长 / 理论下界 比值: ≤1.6 绿 / 1.6–2.6 黄 / >2.6 红
    依据: buck-boost 的输入环(Cin→开关→电感→地)面积决定辐射 EMI(E ∝ f²·A·I)与开关噪声注入,
    元件越紧凑、MST 越小, 环路面积越小。理论下界取"全部两两距离中最小的 n-1 条之和"
    (任何 n-1 条边构成连通结构的下界松弛, 因为生成树每条边都必须在这些距离里选);
    比值→1 表示接近理想紧凑排布; 1.6 以内可认为是"贴在一起"的环路; >2.6 表示元件被串开、
    环路面积成倍放大。点集按题面 = {U8, L2, L3, L4} ∪ 电气实测开关电感 L8 ∪ 它们(非地)网络上的电容。
    数据修正: 实测 U8 的开关电感是 L8(LX 网络), L2/L3/L4 是 U6 的电源滤波电感; 两者都保留,
    并在明细里给出"电气本地环路核心 {U8,L8,C71..C77}"的补充口径。

[4] 晶振位置
    (a) 晶振中心 → 同网络 IC 引脚距离: ≤10mm 绿 / 10–15mm 黄 / >15mm 红
    (b) 两个负载电容到晶振对应焊盘的距离之差: ≤1mm 绿 / 1–2mm 黄 / >2mm 红
    (c) 晶振到最近开关节点焊盘 / 电感本体: ≥5mm 绿 / 3–5mm 黄 / <3mm 红
    依据: XIN/XOUT 是高阻、低电平节点, 寄生电容/串扰直接牵引频率(牵引系数 ~几 ppm/pF)并恶化
    相噪与起振裕度; 晶振应紧贴 IC 且走线短直包地。两个负载电容不对称 → XIN/XOUT 负载不等 →
    共模/差模转换、占空比失真(32MHz 有源晶振与 24MHz 晶体都受影响)。开关节点/电感是板级
    最强 dV/dt/dI/dt 源, <3mm 时近场磁场耦合 ∝1/r³ 会在晶体/走线上直接感应电压。

[5] 敏感件与噪声源隔离  ≥10mm 绿 / 6–10mm 黄 / <6mm 红（本体间隙, 相交=0）
    依据: AS5600 磁编码器(X2 处电机轴下)对磁场最敏感——功率电感漏磁直接转成角度误差;
    晶振/ADC 网络对电场-磁场耦合敏感。源是 U8/U4 及其电感(L2/L3/L4/L8)。近场耦合随距离
    快速衰减(磁场 ∝1/r³, 电场 ∝1/r²), ≥10mm 在无屏蔽时通常已压到可忽略, <6mm 判红。
    注: 噪声源自身、以及与噪声源 IC 共 ADC 网的随行 RC(R22/R23/R24 这类 ADCx.1)从敏感集
    里剔除——它们物理上必须紧贴源 IC, 计入必然恒红, 属于规则伪影。

[6] 地拓扑分区
    AGND 组与 PGND 组包围盒重叠面积 >0 且重叠区内同时存在两组元件 → 红(模拟/功率地混区);
    重叠 >0 但无混区 → 黄; 无重叠 → 绿。
    net-tie(R12/R13/R14)到"它连接的两组质心连线"的距离: ≤5mm 绿 / 5–10mm 黄 / >10mm 红。
    依据: 模拟地与功率地必须"单点/小面积"汇合; 混区会让电机/开关大电流在地平面产生 ΔV,
    经参考地串入 ADC/编码器。net-tie 的物理含义就是两条地电流路径的唯一汇合点, 因此它应落在
    两组交界(质心连线上/附近), 5mm 内视为"单点汇合"。

[7] RF 匹配链  U6 ANT/RF 脚 → 匹配元件 → 天线焊盘的折线长: ≤8mm 绿 / 8–12mm 黄 / >12mm 红
               天线本体到板边天线净空区距离: 在区内(≈0) 绿 / ≤3mm 黄 / >3mm 红
    依据: 2.4GHz 上 1mm 走线 ≈0.7nH ≈ 10Ω 感性阻抗, 任何支节长度都会破坏匹配、抬高插损与
    VSWR; 匹配链应紧凑到 8mm 量级。天线必须处于板边净空区(无铜、无器件、无电池)内, 否则
    辐射效率/方向图被破坏。
    数据修正: 题面写 C65~C68 是匹配网络, 实测 C67/C68 是 +5V 去耦(在 USB1 附近), 匹配链是
    U6 --RF-- L6 --$1N19735-- L7(ANT-SMD, 天线本体), 并联件 C65/C66/C55/C56/C57; 报告按实测。

输出与评分
------------
* 文本报告: 每项一节 = 结论(红/黄/绿) + 关键数字 + [依据](工程依据) + [说明] + 明细(默认 ≤25 条,
  可用 --limit 调整) ; 之后是"重点关注"(全部红项按严重度排序) 和 7 项总表; 若评分的是方案,
  总表后附"与『当前摆放』对照"(逐项得分 + 总分变化)。
* --json: 结构化结果 = 每项 分级/得分/绿黄红计数/明细(全部检查项)/关键指标(metrics) + 总分,
  另含 consistency(与 place_verify 的归属/几何一致性自证)、input_fingerprint(输入文件
  sha256+mtime, 因为本项目里 comps3.json/live.json 正被其它进程持续重写)、thresholds、compare。
* 评分: 7 项等权, 每项得分 = 100×(绿 + 0.5×黄)/检查项数 (红=0, 黄=0.5, 绿=1), 总分 = 7 项均值。
  单项结论: 无红且得分 ≥90 → 绿; 红项占比 ≥50% 或 (有红且得分<60) → 红; 其余 → 黄。
  总表结论: ≥85 绿 / 65–85 黄 / <65 红。
* 若某一项在本板上没有适用对象(检查项数 0), 该项记"灰"且不计入扣分(得分 100)。
* 检查项就是"一个可判定的物理事实"(一个电源脚/一个地脚/一颗晶振的一个判据/一个 net-tie…),
  因此"红黄绿比例"就是"出问题的脚/件的比例"。

本脚本遇到的数据实况(与题面不一致处, 报告里都会显式说明)
--------------------------------------------------------
* 实测 U8 的开关电感是 L8(LX 网络); L2/L3/L4 是 U6 的电源滤波电感 —— 第 3 项两者都收进点集。
* 实测 C67/C68 不在 RF 网络上(是 USB1 旁 +5V 去耦), 第 7 项按实测网络 U6-RF-L6-$1N19735-L7 走链。
* comps3.json / live.json 会被其它进程重写(例如 live.json 的 vias/lines 可能暂时为空),
  报告头会打印输入指纹; 第 2 项在 vias 为空时会显式提示"只能用其它元件地焊盘判"。
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
from collections import defaultdict, deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

try:
    from shapely.affinity import rotate as sh_rotate
    from shapely.geometry import Point as sh_Point
    from shapely.geometry import box as sh_box
except Exception as _e:                                        # pragma: no cover
    sys.stderr.write("需要 shapely>=2.0: %s\n" % _e)
    raise

MIL = 0.0254

# ------------------------------------------------------------------ 分类/常量
# 与 place_verify.py 完全一致的口径
IC_FP_PREFIX = ("QFN", "SOIC", "TSSOP", "VQFN", "AQFN")
POWER_RE = re.compile(
    r"^(?:\+?\d+(?:V\d*)?V\d*|V\d+(?:V\d*)?|VCC(?:_.*)?|VDD(?:_.*)?|AVDD(?:_.*)?|"
    r"DVDD(?:_.*)?|VBUS.*|VREG_.*|IP\+?\d*V.*|VBAT.*|VIN.*)$", re.I)
GND_RE = re.compile(r"^(?:A?P?GND(?:_.*)?|GND(?:_.*)?|VSS.*)$", re.I)
CAP_RE = re.compile(r"^C\d+$", re.I)          # 电容位号: C1..C99（CN1 等连接器不算电容）
# 信号/晶振/RF 网络关键词: 这些网络上的电容不是去耦电容, 不参与第 1 项判定
SIGNAL_NET_RE = re.compile(
    r"(XIN|XOUT|XL\d|RF|ANT|NFC|ADC|PWM|SCL|SDA|^SW|SWCLK|SWDIO|USB_|_DM$|_DP$|^CC\d|QSPI|"
    r"UART|SCLK|^SDI$|^SDO$|CS$|PSRAM|VBUSG|NSLEEP|^PL$|^DIR$|^CP1$|DRV_OFF|^Q\d|^PT\d)", re.I)

# 4 层板叠层: TOP / INNER_1=完整 GND / INNER_2=VCC 平面 / BOTTOM, 外层铺 GND
LAYER_PLANE = {1: "TOP", 2: "BOTTOM", 12: "通孔(两层皆可)"}

# 板边天线净空 / 板框（与 place_verify.py 同口径）
BOARD = (0.0, -7.20, 90.0, 82.80)
ANT_KEEPOUT = (84.6, 31.0, 90.5, 39.0)

GND_GROUPS = ("GND", "AGND", "PGND", "GND_BK")
NET_TIES = ("R12", "R13", "R14")
NOISE_SRC = ("U8", "U4", "L2", "L3", "L4", "L8")     # 开关电源 + 电机驱动 + 功率电感
SENSITIVE_FIXED = ("U5", "X1", "X2", "X3")           # AS5600 + 晶振
CRYSTAL_SPEC = {                                     # 晶振: (网络1, 网络2, 对应 IC)
    "X1": ("XIN", "XOUT", "U1"),
    "X2": ("XL1", "XL2", "U6"),
    "X3": ("$1N17981", "$1N17987", "U6"),
}
RF_NAMED = ("C65", "C66", "C67", "C68", "L6", "L7")  # 题面点名的 RF 匹配件（判定按实测网络）

# 分级阈值（全部来自上面 docstring 的工程依据）
TH_DECAP = (3.0, 5.0)          # <= 绿, <= 黄, 否则红
TH_ICGND = (3.0, 5.0)
TH_LOOP_RATIO = (1.6, 2.6)
TH_XTAL_IC = (10.0, 15.0)
TH_XTAL_CAP_SKEW = (1.0, 2.0)
TH_XTAL_SW = (5.0, 3.0)        # 反向指标: >=5 绿, 3–5 黄, <3 红
TH_ISO = (10.0, 6.0)           # 反向: >=10 绿, 6–10 黄, <6 红
TH_TIE_LINE = (5.0, 10.0)
TH_RF_CHAIN = (8.0, 12.0)
TH_ANT_KEEPOUT = (0.5, 3.0)

# 与 place_verify.py TBL 完全一致（import 失败时兜底用；成功时仍用于一致性比对）
FP_TBL = {
    "C0603": (1.6, 0.9), "R0603": (1.6, 0.9), "L0603": (1.6, 0.9), "R1206": (3.2, 1.7),
    "SMA_L4.3-W2.6-LS5.0-BI": (4.3, 2.6), "HDR-TH_3P-P2.54-V-F": (7.7, 2.6),
    "HDR-TH_2P-P2.54-V-F": (5.1, 2.6), "HDR-TH_5P-P2.54-V-P-M": (12.7, 2.6),
    "HDR-TH_5P-P2.54-V-M": (12.7, 2.6), "HDR-TH_10P-P2.54-V-F": (25.4, 2.6),
    "OPTO-TH_3P_PT2559B": (5.2, 4.0), "AO3401A_SOT-23-3": (3.0, 1.5),
    "ANT-SMD_L3.1-W1.6": (3.1, 1.6), "Key_SMD_3x4x2": (3.0, 4.0),
    "SW-TH_SHOU-HAN_3JWD-DBHD-13.5": (13.5, 6.4), "USB_TYPE-C-16P": (9.0, 7.3),
    "LED-TH_L4.5-W2.25-P2.54-FD": (4.5, 2.3), "CONN-TH_XT30PW-M": (10.0, 7.0),
}


def fp_size(fp):
    """与 place_verify.footprint_size 同口径: 返回 (Lx, Ly, 来源)"""
    if fp in FP_TBL:
        return FP_TBL[fp][0], FP_TBL[fp][1], "table"
    m = re.search(r"_L([0-9.]+)-W([0-9.]+)", fp) or re.search(r"L([0-9.]+)-W([0-9.]+)", fp)
    if m:
        return float(m.group(1)), float(m.group(2)), "regex"
    if re.search(r"^([A-Z]+)-(\d+)", fp):
        return 6.0, 5.0, "fallback-generic"
    return 2.0, 1.5, "fallback-default"


# ==================================================================== 几何后端
class MiniModel(object):
    """place_verify.Model 的同口径迷你实现（仅 import 失败时兜底 + 一致性比对用）。

    焊盘归属: scipy.optimize.linear_sum_assignment 全局最优指派,
    代价 = 焊盘中心到元件原点欧氏距离, 层不匹配 +100mm 惩罚, layer=12 (通孔) 两层合法。
    此实现与 place_verify.Model.assign_pads() 逐项一致（同一代价矩阵、同一求解器）。
    """

    PEN = 100.0

    def __init__(self, comps_path, live_path):
        self.warnings = []
        with io.open(comps_path, "r", encoding="utf-8-sig") as fh:
            comps = json.load(fh)
        if isinstance(comps, dict):
            for k in ("components", "comps", "parts", "items"):
                if isinstance(comps.get(k), list):
                    comps = comps[k]
                    break
            else:
                comps = [comps]
        with io.open(live_path, "r", encoding="utf-8-sig") as fh:
            live = json.load(fh)
        self.pads = live["pads"]
        self.vias = live.get("vias", [])
        self.lines = live.get("lines", [])
        self.D, self.info = [], []
        for i, c in enumerate(comps):
            d = str(c.get("d", "?%d" % i))
            if d in self.D:
                continue
            fp = str(c.get("f", ""))
            L, W, src = fp_size(fp)
            self.D.append(d)
            self.info.append({"idx": i, "d": d, "f": fp, "x": float(c.get("x", 0.0)),
                              "y": float(c.get("y", 0.0)), "r": float(c.get("r", 0.0) or 0.0),
                              "l": int(c.get("l", 1) or 1), "npins": len(c.get("p") or []),
                              "L": L, "W": W, "size_src": src})
        self.byD = {c["d"]: c for c in self.info}
        self.assign_pads()
        self.build_nets()

    def assign_pads(self):
        n_pads = len(self.pads)
        slots = []
        for ci, c in enumerate(self.info):
            slots.extend([ci] * c["npins"])
        self.pad_comp = [-1] * n_pads
        self.assign_cost = [0.0] * n_pads
        self.assign_pen = 0
        if not slots:
            self.pads_by_comp = defaultdict(list)
            return
        sl = np.array(slots, dtype=np.int64)
        cx = np.array([self.info[i]["x"] for i in sl])
        cy = np.array([self.info[i]["y"] for i in sl])
        cl = np.array([self.info[i]["l"] for i in sl])
        px = np.array([float(p[2]) for p in self.pads])
        py = np.array([float(p[3]) for p in self.pads])
        pl = np.array([int(p[1]) for p in self.pads])
        dist = np.sqrt((px[:, None] - cx[None, :]) ** 2 + (py[:, None] - cy[None, :]) ** 2)
        cost = dist + np.where((pl[:, None] != 12) & (pl[:, None] != cl[None, :]), self.PEN, 0.0)
        from scipy.optimize import linear_sum_assignment
        ri, cj = linear_sum_assignment(cost)
        for pi, si in zip(ri.tolist(), cj.tolist()):
            self.pad_comp[pi] = int(sl[si])
            self.assign_cost[pi] = float(dist[pi, si])
            self.assign_pen += int(cost[pi, si] >= self.PEN)
        self.pads_by_comp = defaultdict(list)
        for pi, ci in enumerate(self.pad_comp):
            if ci >= 0:
                self.pads_by_comp[ci].append(pi)
        self.assign_stats = {
            "n_pads": n_pads, "n_slots": len(slots),
            "mean_dist_mm": (sum(self.assign_cost) / n_pads) if n_pads else 0.0,
            "max_dist_mm": max(self.assign_cost) if n_pads else 0.0,
            "layer_penalized": self.assign_pen,
        }

    def build_nets(self):
        self.net_pads = defaultdict(list)
        self.net_comps = defaultdict(set)
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
        return [(pi, float(self.pads[pi][2]) - c["x"], float(self.pads[pi][3]) - c["y"])
                for pi in self.pads_by_comp.get(ci, [])]


class MiniPlan(object):
    """place_verify.Plan 的同口径迷你实现：旋转矩形本体 + 焊盘随属主刚体变换"""

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

    def body(self, c_or_d):
        c = self.m.byD[c_or_d] if isinstance(c_or_d, str) else c_or_d
        x, y = self.pos(c["d"])
        L, W = c["L"], c["W"]
        g = sh_box(x - L / 2.0, y - W / 2.0, x + L / 2.0, y + W / 2.0)
        ang = self.angle(c["d"])
        if abs(ang) > 1e-12:
            g = sh_rotate(g, ang, origin=(x, y))
        return g

    def pad_points(self):
        n = len(self.m.pads)
        P = np.zeros((n, 2))
        for ci, c in enumerate(self.m.info):
            dx, dy = self.delta(c["d"])
            th = math.radians(self.drot.get(c["d"], 0.0))
            ct, st = math.cos(th), math.sin(th)
            for pi, ox, oy in self.m.comp_pad_offsets(ci):
                if abs(th) > 1e-12:
                    ox, oy = ox * ct - oy * st, ox * st + oy * ct
                P[pi, 0] = c["x"] + ox + dx
                P[pi, 1] = c["y"] + oy + dy
        return P


def load_backends(comps_path, live_path):
    """优先 import place_verify；返回 (Model, Plan, backend_name, pv_module|None)"""
    pv_mod = None
    try:
        import place_verify as pv_mod          # noqa: F401  (同目录 1528 行已验证模块)
        Model, Plan, name = pv_mod.Model, pv_mod.Plan, "place_verify"
    except Exception as e:
        sys.stderr.write("[warn] 无法 import place_verify(%s); 使用内置同口径实现\n" % e)
        Model, Plan, name = MiniModel, MiniPlan, "builtin-mini"
    return Model, Plan, name, pv_mod, MiniModel, MiniPlan


# ==================================================================== 通用工具
def reconf(stream):
    try:
        stream.reconfigure(errors="replace")
    except Exception:
        pass


def fingerprint(path):
    """输入文件指纹: 这些文件可能被其它进程持续重写(本项目实测如此), 记录 sha256+mtime 便于追溯"""
    try:
        import hashlib
        import time as _t
        with open(path, "rb") as fh:
            raw = fh.read()
        return {"path": os.path.abspath(path), "bytes": len(raw),
                "sha256_16": hashlib.sha256(raw).hexdigest()[:16],
                "mtime": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(os.path.getmtime(path)))}
    except Exception as e:                                     # pragma: no cover
        return {"path": os.path.abspath(path), "error": str(e)}


def f2(x, nd=2):
    if x is None:
        return "-"
    v = ("%%.%df" % nd) % (x + 0.0)
    return v[1:] if v.startswith("-") and float(v) == 0.0 else v


def band(v, th, reverse=False):
    """两段阈值分级。reverse=True 用于"越大越好"的指标(如隔离距离)。
    返回 (grade, 说明)。grade ∈ {绿, 黄, 红}"""
    if v is None:
        return "红", "无可用对象"
    a, b = th
    if reverse:
        return ("绿", "≥%.1f" % a) if v >= a else (("黄", "%.1f–%.1f" % (b, a))
                                                  if v >= b else ("红", "<%.1f" % b))
    return ("绿", "≤%.1f" % a) if v <= a else (("黄", "%.1f–%.1f" % (a, b))
                                               if v <= b else ("红", ">%.1f" % b))


def mk_check(label, value, grade, unit="mm", note="", **extra):
    c = {"label": label, "value": (None if value is None else round(value, 4)),
         "unit": unit, "grade": grade, "note": note}
    c.update(extra)
    return c


class Item(object):
    def __init__(self, iid, key, title, rationale):
        self.id = iid
        self.key = key
        self.title = title
        self.rationale = rationale
        self.checks = []
        self.metrics = {}
        self.notes = []

    def add(self, c):
        self.checks.append(c)

    def finalize(self):
        n = len(self.checks)
        g = sum(1 for c in self.checks if c["grade"] == "绿")
        y = sum(1 for c in self.checks if c["grade"] == "黄")
        r = sum(1 for c in self.checks if c["grade"] == "红")
        score = 100.0 * (g + 0.5 * y) / n if n else 100.0
        # 单项结论: 绿 = 无红且得分≥90; 红 = 红项占比≥50% 或 (有红且得分<60);
        # 其余为黄（这样"只有 1 个检查项且为黄"的单项不会被 50 分硬压成红, 保持自洽）
        if n == 0:
            grade = "灰"
        elif r == 0 and score >= 90.0:
            grade = "绿"
        elif (r / float(n)) >= 0.5 or (r > 0 and score < 60.0):
            grade = "红"
        else:
            grade = "黄"
        return {"id": self.id, "key": self.key, "title": self.title, "rationale": self.rationale,
                "n_checks": n, "counts": {"green": g, "yellow": y, "red": r},
                "score": round(score, 2), "grade": grade, "checks": self.checks,
                "metrics": self.metrics, "notes": self.notes}


def grade_key(grade):
    return {"红": 0, "黄": 1, "绿": 2, "灰": 3}.get(grade, 2)


def sorted_checks(checks, limit):
    """文本明细: 先按严重度(红->黄->绿), 同级按数值从差到好"""
    def keyf(c):
        v = c["value"]
        return (grade_key(c["grade"]), -(v if v is not None else 1e9))
    return sorted(checks, key=keyf)[:limit]


# ==================================================================== 上下文
class Ctx(object):
    def __init__(self, comps_path, live_path, Model, Plan):
        self.d = os.path.basename(comps_path)
        self.l = os.path.basename(live_path)
        self.model = Model(comps_path, live_path)
        self.PlanCls = Plan
        m = self.model
        self.byD = m.byD
        self.info = m.info
        self.ics = [c for c in m.info if c["f"].startswith(IC_FP_PREFIX)]
        self.caps = [c for c in m.info if CAP_RE.match(c["d"])]
        self.net_has_cap = defaultdict(bool)
        for c in self.caps:
            for n in m.comp_nets.get(c["idx"], set()):
                if n:
                    self.net_has_cap[n] = True
        self.crystal_nets = set()
        for d in CRYSTAL_SPEC:
            c = m.byD.get(d)
            if c:
                self.crystal_nets |= set(x for x in m.comp_nets.get(c["idx"], set()) if x)
        # 天线/RF 件
        self.antenna = [c for c in m.info if c["f"].upper().startswith("ANT")]
        # 开关节点网络(与 place_verify 口径无关, 仅本评分器用来定位 dV/dt·dI/dt 源):
        #   LX/SW_BK 这类明确的开关节点  ∪  与开关电源/电机驱动/功率电感(U8/U4/L2/L3/L4/L8)
        #   同网络的"局部网络"(非地、非电源名、非信号名)。按键矩阵 SW3..SW13、SWCLK_NRF、
        #   PWM/ADC/CC 等信号网络必须排除, 否则会把"开关"误读成开关节点。
        SW_EXCLUDE_RE = re.compile(
            r"(SWCLK|SWDIO|^SW\d+$|ADC|^CC\d|^CP|^PWM|^U$|^V$|^W$|DIR|NSLEEP|DRV|SCLK|SCS|"
            r"^SDI$|^SDO$|QSPI|UART|PSRAM|^Q\d|^PT\d|NFC|XIN|XOUT|XL\d|ANT|^RF$)", re.I)
        parts = {"U8", "U4", "L2", "L3", "L4", "L8"}
        self.sw_nets = set()
        for n, cs in m.net_comps.items():
            if not n or GND_RE.match(n) or POWER_RE.match(n):
                continue
            ds = set(m.info[i]["d"] for i in cs)
            if not (ds & parts) or SW_EXCLUDE_RE.search(n):
                continue
            self.sw_nets.add(n)
        self.sw_pads = [p for n in self.sw_nets for p in m.net_pads.get(n, [])]

    def plan(self, moves=None, rots=None, name="原始摆放"):
        return self.PlanCls(self.model, moves or {}, rots or {}, name)


# ==================================================================== [1] 去耦
def item1_decap(ctx, plan):
    """[1] 去耦有效性
    判定: 每个 IC(QFN/SOIC/TSSOP/VQFN/AQFN) 的每个"电源脚网络"上的引脚, 取到同网络最近电容
    焊盘(中心点)距离; 同一网络多脚时取最差引脚(约束来自最薄弱的那个脚)。
    阈值 ≤3mm 绿 / 3–5mm 黄 / >5mm 红; 网络上没有电容 → 红(该电源脚没有局部去耦)。
    工程依据见文件头 [1]。"""
    it = Item(1, "decap", "去耦有效性",
              ["阈值 ≤3mm 绿 / 3–5mm 黄 / >5mm 红; 同网络无电容=红",
               "依据: 回路电感随'电源脚→电容→地'距离线性增长(1mm≈0.6–1nH), 3mm≈2–3nH 与 0402/0603 "
               "电容自身 ESL 同量级仍有效; >5mm 引线电感主导, PDN 高频阻抗抬升、谐振点下移",
               "业界做法: 去耦电容放在电源脚 2–3mm 内 (TI/ADI 电源布局指南, IPC-7351 实践)",
               "电源脚识别: 网络名命中 VCC/VDD/AVDD/PVDD/+5V/1V1/VBUS/VREG/IP+5V… 或 "
               "'该脚网络非地且网络上有电容'——但排除晶振/RF/信号网络(其上的电容是负载/匹配电容)"])
    P = plan.pad_points()
    m = ctx.model
    per_net_sum = []
    for ic in ctx.ics:
        per_net = defaultdict(list)
        for pi in m.pads_by_comp.get(ic["idx"], []):
            net = m.pads[pi][0] or ""
            if net:
                per_net[net].append(pi)
        for net, pids in sorted(per_net.items()):
            if GND_RE.match(net):
                continue
            if POWER_RE.match(net):
                reason = "网络名(电源)"
            elif (ctx.net_has_cap.get(net) and net not in ctx.crystal_nets
                  and not SIGNAL_NET_RE.search(net)):
                reason = "非地+网络上有电容"
            else:
                continue
            cap_pads = [qi for qi in m.net_pads.get(net, [])
                        if m.pad_comp[qi] >= 0 and CAP_RE.match(m.info[m.pad_comp[qi]]["d"])]
            worst = None
            for pi in pids:
                b = None
                for qi in cap_pads:
                    dd = float(math.dist(P[pi], P[qi]))
                    if b is None or dd < b[0]:
                        b = (dd, m.info[m.pad_comp[qi]]["d"], m.pads[qi][6])
                # 逐引脚判定（题面口径: "该脚到同网络上最近的电容焊盘的距离"）
                label = "%s pad%s %s" % (ic["d"], m.pads[pi][6], net)
                if b is None:
                    it.add(mk_check(label, None, "红", unit="mm",
                                    note="红: 该电源网络上没有电容(无局部去耦); 电源脚识别=%s" % reason,
                                    ic=ic["d"], net=net, pad=str(m.pads[pi][6]), reason=reason))
                else:
                    gr, why = band(b[0], TH_DECAP)
                    it.add(mk_check(label, b[0], gr, unit="mm",
                                    note="%s: 最近去耦电容 %s(pad%s); 电源脚识别=%s"
                                         % (why, b[1], b[2], reason),
                                    ic=ic["d"], net=net, pad=str(m.pads[pi][6]),
                                    nearest_cap=b[1], nearest_cap_pad=str(b[2]), reason=reason))
                    if worst is None or b[0] > worst:
                        worst = b[0]
            per_net_sum.append({"ic": ic["d"], "net": net, "n_pins": len(pids),
                                "worst_pin_mm": (round(worst, 3) if worst is not None else None)})
    it.metrics = {"n_ic": len(ctx.ics), "n_power_pin_checks": len(it.checks),
                  "per_net": per_net_sum}
    # 按网络汇总(取网络内最差脚) —— 便于看清"是某个 IC 的整条电源网络缺去耦"还是"个别脚偏"
    for row in per_net_sum:
        gr, _ = band(row["worst_pin_mm"], TH_DECAP)
        row["grade_worst_pin"] = gr if row["worst_pin_mm"] is not None else "红"
    cnt = {"绿": 0, "黄": 0, "红": 0}
    for row in per_net_sum:
        cnt[row["grade_worst_pin"]] += 1
    it.notes.append("按电源网络汇总(网络内取最差脚) %d 个网络: 绿%d/黄%d/红%d"
                    % (len(per_net_sum), cnt["绿"], cnt["黄"], cnt["红"]))
    n_red_nocap = sum(1 for c in it.checks if c["value"] is None)
    if n_red_nocap:
        it.notes.append("有 %d 个电源网络上完全没有电容(判红): %s"
                        % (n_red_nocap, ",".join(c["label"] for c in it.checks
                                                if c["value"] is None)[:200]))
    reds = sum(1 for c in it.checks if c["grade"] == "红")
    if reds:
        it.notes.append("红项最多的 IC: " + "、".join(
            "%s(%d红)" % (d, n) for d, n in
            sorted(((ic, sum(1 for c in it.checks if c.get("ic") == ic and c["grade"] == "红"))
                    for ic in set(c.get("ic") for c in it.checks)), key=lambda t: -t[1])[:5]
            if n)) if reds else ""
    return it.finalize()


# ==================================================================== [2] IC 地脚
def item2_ic_gnd(ctx, plan):
    """[2] IC 地引脚就近性
    每个 IC 的 GND/PGND/AGND/VSS 脚 → 同网络最近过孔焊盘 或 其它元件的同网络(地)焊盘。
    阈值 ≤3mm 绿 / 3–5mm 黄 / >5mm 红。工程依据见文件头 [2]（4 层板靠过孔下 INNER_1 完整地平面）。"""
    it = Item(2, "ic_gnd", "IC 地引脚就近性",
              ["阈值 ≤3mm 绿 / 3–5mm 黄 / >5mm 红",
               "依据: 4 层板 INNER_1 = 完整 GND 平面, 地回流 = '地脚→就近过孔→平面'; "
               "该距离就是回流路径长度, >5mm 时地电流被迫在外层长距离流动, 抬高共地阻抗并形成辐射环",
               "判定对象: 同网络的过孔(live.json vias) 或 其它元件的同网络(地)焊盘"])
    P = plan.pad_points()
    m = ctx.model
    for ic in ctx.ics:
        for pi in m.pads_by_comp.get(ic["idx"], []):
            net = m.pads[pi][0] or ""
            if not GND_RE.match(net):
                continue
            best = None
            for v in m.vias:
                if (v[1] or "") != net:
                    continue
                dd = float(math.dist(P[pi], (v[2], v[3])))
                if best is None or dd < best[0]:
                    best = (dd, "过孔", "via", (v[2], v[3]))
            for qi in m.net_pads.get(net, []):
                if qi == pi:
                    continue
                ci = m.pad_comp[qi]
                if ci < 0 or ci == ic["idx"]:
                    continue
                dd = float(math.dist(P[pi], P[qi]))
                if best is None or dd < best[0]:
                    best = (dd, m.info[ci]["d"], "pad", (float(m.pads[qi][2]), float(m.pads[qi][3])))
            padnum = m.pads[pi][6]
            label = "%s pad%s %s" % (ic["d"], padnum, net)
            if best is None:
                it.add(mk_check(label, None, "红", unit="mm", note="红: 同网络无任何过孔/其它地焊盘",
                                ic=ic["d"], net=net, pad=str(padnum)))
            else:
                gr, why = band(best[0], TH_ICGND)
                it.add(mk_check(label, best[0], gr, unit="mm",
                                note="%s: 最近 %s(%s)" % (why, best[1],
                                                        "过孔" if best[2] == "via" else "元件地焊盘"),
                                ic=ic["d"], net=net, pad=str(padnum), target=best[1],
                                target_kind=best[2]))
    nvia = len(ctx.model.vias)
    n_via_hit = sum(1 for c in it.checks if c.get("target_kind") == "via")
    it.metrics = {"n_vias": nvia, "n_ics": len(ctx.ics), "n_pads_targeting_via": n_via_hit,
                  "n_checks": len(it.checks)}
    if nvia == 0:
        it.notes.append("注意: 当前 live.json 的 vias 为空(该文件正被其它进程重写), 第 2 项只能用"
                        "'其它元件的同网络地焊盘'作目标; 真实过孔导出后判定会更严格/更准。")
    else:
        it.notes.append("判定目标: 过孔命中 %d/%d 个地脚, 其余用其它元件的同网络地焊盘。"
                        % (n_via_hit, len(it.checks)))
    return it.finalize()


# ==================================================================== [3] 热环路
def _mst_and_lb(pts):
    """返回 (MST 总长, 下界, 边列表[(i,j,len)])。
    下界 = 全部两两距离中最小的 n-1 个之和（任何生成结构的松弛下界）。"""
    n = len(pts)
    if n < 2:
        return 0.0, 0.0, []
    D = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1))
    INF = 1e18
    inT = [False] * n
    key = [INF] * n
    par = [-1] * n
    key[0] = 0.0
    edges = []
    for _ in range(n):
        u = min((k for k in range(n) if not inT[k]), key=lambda k: key[k])
        inT[u] = True
        if par[u] >= 0:
            edges.append((par[u], u, float(key[u])))
        for v in range(n):
            if not inT[v] and D[u][v] < key[v]:
                key[v] = float(D[u][v])
                par[v] = u
    ds = sorted(float(D[i][j]) for i in range(n) for j in range(i + 1, n))
    return sum(e[2] for e in edges), sum(ds[:n - 1]), edges


def item3_hotloop(ctx, plan):
    """[3] DC-DC 热环路近似
    点集 = {U8, L2, L3, L4} ∪ {L8(实测 U8 开关电感, LX 网络)} ∪ 这些点(非地)网络上的电容(^C\\d+$)。
    MST 总长作为环路面积代理; 与理论下界(最小 n-1 条两两距离之和, 生成结构的下界松弛)比。
    阈值 比值 ≤1.6 绿 / 1.6–2.6 黄 / >2.6 红。工程依据见文件头 [3]。"""
    it = Item(3, "hotloop", "DC-DC 热环路近似(MST)",
              ["阈值: MST/理论下界 ≤1.6 绿 / 1.6–2.6 黄 / >2.6 红",
               "依据: buck-boost 输入环(Cin→开关→电感→地)面积决定辐射 EMI(E∝f²·A·I)与开关噪声注入; "
               "MST 总长是环路面积/散布程度的代理, 越小越紧凑",
               "理论下界 = 全部两两距离中最小的 n-1 条之和(任何 n-1 条边构成连通结构的松弛下界); "
               "比值→1 = 接近理想紧凑排布, >2.6 = 元件被串开、环路面积成倍放大",
               "点集按题面 = {U8, L2, L3, L4} ∪ {L8} ∪ 它们非地网络上的电容; 数据修正: 实测 U8 的开关"
               "电感是 L8(LX 网), L2/L3/L4 是 U6 的电源滤波电感, 两者都保留"])
    m = ctx.model
    base = ["U8", "L2", "L3", "L4"]
    base = [d for d in base if d in ctx.byD]
    if "L8" in ctx.byD:
        base.append("L8")
    shared = set()
    for d in base:
        shared |= set(x for x in m.comp_nets.get(ctx.byD[d]["idx"], set()) if x)
    ptset = list(base)
    capset = set()
    for n in sorted(shared):
        if GND_RE.match(n):
            continue
        for i in m.net_comps.get(n, []):
            dd = m.info[i]["d"]
            if CAP_RE.match(dd):
                capset.add(dd)
    ptset += sorted(capset)
    pts = np.array([plan.pos(d) for d in ptset], dtype=float)
    tot, lb, edges = _mst_and_lb(pts)
    ratio = (tot / lb) if lb > 1e-9 else 0.0
    gr, why = band(ratio, TH_LOOP_RATIO)
    it.add(mk_check("热环路 MST / 下界 比值(%d 点)" % len(ptset), ratio, gr, unit="",
                    note="%s: MST=%.2fmm, 下界=%.2fmm" % (why, tot, lb), mst_mm=round(tot, 3),
                    lb_mm=round(lb, 3), n_points=len(ptset)))
    edge_rows = sorted(edges, key=lambda e: -e[2])
    it.metrics = {"points": ptset, "n_points": len(ptset), "mst_mm": round(tot, 3),
                  "lower_bound_mm": round(lb, 3), "ratio": round(ratio, 3),
                  "top_edges": [{"a": ptset[e[0]], "b": ptset[e[1]], "mm": round(e[2], 3)}
                                for e in edge_rows[:8]]}
    long_edges = [(ptset[e[0]], ptset[e[1]], e[2]) for e in edge_rows if e[2] > 8.0]
    if long_edges:
        it.notes.append("MST 长边(>8mm): " + "; ".join("%s-%s %.1fmm" % t for t in long_edges[:5]))
        rails = set()
        for a, b, _mm in long_edges[:5]:
            for d in (a, b):
                for n in m.comp_nets.get(ctx.byD[d]["idx"], set()):
                    if n and POWER_RE.match(n):
                        rails.add(n)
        it.notes.append("注: 长边中跨越多半是同一条电源轨(%s)上分散布置的去耦电容之间的连接——"
                        "平面/轨上分布式去耦属于正常做法, 不构成开关环路本身; 判定应以比值与下面"
                        "'电气本地环路核心'口径为准。" % (",".join(sorted(rails)) or "电源"))
    # 补充口径: 电气本地环路核心 = U8 + L8 + 距 U8 8mm 内、且在 U8 自身网络上的电容
    loc = ["U8"] + (["L8"] if "L8" in ctx.byD else [])
    u8nets = set(x for x in m.comp_nets.get(ctx.byD["U8"]["idx"], set())
                 if x and not GND_RE.match(x))
    u8x, u8y = plan.pos("U8")
    for n in sorted(u8nets):
        for i in m.net_comps.get(n, []):
            dd = m.info[i]["d"]
            if CAP_RE.match(dd):
                px, py = plan.pos(dd)
                if math.hypot(px - u8x, py - u8y) <= 8.0 and dd not in loc:
                    loc.append(dd)
    if len(loc) >= 3:
        lp = np.array([plan.pos(d) for d in loc], dtype=float)
        lt, llb, _ = _mst_and_lb(lp)
        it.metrics["local_core"] = {"points": sorted(set(loc)), "mst_mm": round(lt, 3),
                                    "lb_mm": round(llb, 3),
                                    "ratio": round(lt / llb, 3) if llb > 1e-9 else None}
        it.notes.append("补充口径『电气本地环路核心』%s: MST=%.2fmm, 下界=%.2fmm, 比值=%.2f"
                        % (",".join(sorted(set(loc))), lt, llb, (lt / llb) if llb > 1e-9 else 0.0))
    return it.finalize()


# ==================================================================== [4] 晶振
def item4_xtal(ctx, plan):
    """[4] 晶振位置: (a) 晶振→同网络 IC 引脚 ≤10/10–15/>15mm
                    (b) 两负载电容到晶振焊盘距离之差 ≤1/1–2/>2mm
                    (c) 晶振→最近开关节点焊盘/电感本体 ≥5/3–5/<3mm
    工程依据见文件头 [4]。"""
    it = Item(4, "xtal", "晶振位置(X1/X2/X3)",
              ["(a) 晶振→同网络 IC 引脚: ≤10mm 绿 / 10–15mm 黄 / >15mm 红",
               "(b) 两负载电容到晶振焊盘距离之差: ≤1mm 绿 / 1–2mm 黄 / >2mm 红",
               "(c) 晶振→最近开关节点焊盘/电感本体: ≥5mm 绿 / 3–5mm 黄 / <3mm 红",
               "依据: XIN/XOUT 是高阻低电平节点, 寄生电容/串扰直接牵引频率(几 ppm/pF)并恶化相噪与"
               "起振裕度, 应紧贴 IC 短直包地; 两个负载电容不对称 → XIN/XOUT 负载不等 → 共模/差模"
               "转换与占空比失真; 开关节点/电感是最强 dV/dt·dI/dt 源, <3mm 时近场磁场 ∝1/r³ 直接感应",
               "开关节点网络 = LX/SW* 以及 电感(L2/L3/L4/L8) 与驱动 IC(U8/U4) 共用(非地非电源名)的网络, "
               "按 live.json pads 网络判定"])
    P = plan.pad_points()
    m = ctx.model
    ind_bodies = {}
    for d in ("L2", "L3", "L4", "L8"):
        if d in ctx.byD:
            ind_bodies[d] = plan.body(d)
    for dx, (n1, n2, uic) in CRYSTAL_SPEC.items():
        c = ctx.byD.get(dx)
        if c is None:
            continue
        xpads = list(m.pads_by_comp.get(c["idx"], []))
        ic_d = {}
        cap_d = {}
        cap_pad_d = {}
        for net in (n1, n2):
            xp = [p for p in xpads if (m.pads[p][0] or "") == net]
            uq = [p for p in m.net_pads.get(net, [])
                  if m.pad_comp[p] >= 0 and m.info[m.pad_comp[p]]["d"] == uic]
            cq = [p for p in m.net_pads.get(net, [])
                  if m.pad_comp[p] >= 0 and CAP_RE.match(m.info[m.pad_comp[p]]["d"])]
            ic_d[net] = min((float(math.dist(P[p], plan.pos(dx))) for p in uq), default=None)
            cap_d[net] = min((float(math.dist(P[q], plan.pos(dx))) for q in cq), default=None)
            cg = [(float(math.dist(P[q], P[p])), m.info[m.pad_comp[q]]["d"])
                  for q in cq for p in xp]
            cap_pad_d[net] = min(cg) if cg else None
        # (a) 到 IC 引脚距离(取两条网络中最差)
        vals = [v for v in ic_d.values() if v is not None]
        va = max(vals) if vals else None
        gr, why = band(va, TH_XTAL_IC)
        it.add(mk_check("%s→%s 晶振脚距离" % (dx, uic), va, gr,
                        note="%s: %s" % (why, ", ".join("%s=%.2f" % (k, v) for k, v in ic_d.items()
                                                        if v is not None)),
                        xtal=dx, ic=uic))
        # (b) 负载电容对称度
        ds = [(net, cap_pad_d[net][0], cap_pad_d[net][1]) for net in (n1, n2)
              if cap_pad_d[net] is not None]
        if len(ds) == 2:
            skew = abs(ds[0][1] - ds[1][1])
            gr, why = band(skew, TH_XTAL_CAP_SKEW)
            it.add(mk_check("%s 负载电容对称度" % dx, skew, gr,
                            note="%s: %s=%.2f(%s) vs %s=%.2f(%s)"
                                 % (why, ds[0][0], ds[0][1], ds[0][2], ds[1][0], ds[1][1], ds[1][2]),
                            xtal=dx, cap_a=ds[0][2], cap_b=ds[1][2],
                            d_a=round(ds[0][1], 3), d_b=round(ds[1][1], 3)))
        else:
            it.add(mk_check("%s 负载电容对称度" % dx, None, "红",
                            note="红: 同一晶振的两个负载电容未同时找到(找到 %d/2)" % len(ds),
                            xtal=dx))
        # (c) 开关节点/电感本体
        swd = min((float(math.dist(P[p], plan.pos(dx))) for p in ctx.sw_pads), default=None)
        indd = None
        indwho = None
        b = plan.body(dx)
        for d2, g in ind_bodies.items():
            gd = float(b.distance(g))
            if indd is None or gd < indd:
                indd, indwho = gd, d2
        cand = [(v, k) for v, k in ((swd, "开关节点焊盘"), (indd, "电感本体 " + str(indwho)))
                if v is not None]
        vc, kc = min(cand) if cand else (None, "")
        gr, why = band(vc, TH_XTAL_SW, reverse=True)
        it.add(mk_check("%s→最近开关节点/电感" % dx, vc, gr,
                        note="%s: %s(开关节点焊盘 %.2f, 电感本体 %.2f)" %
                             (why, kc, swd if swd is not None else -1,
                              indd if indd is not None else -1),
                        xtal=dx, sw_pad_mm=(round(swd, 3) if swd is not None else None),
                        inductor=indwho, ind_mm=(round(indd, 3) if indd is not None else None)))
    it.metrics = {"sw_nets": sorted(ctx.sw_nets),
                  "crystal_nets": sorted(n for n in ctx.crystal_nets if n)}
    return it.finalize()


# ==================================================================== [5] 隔离
def item5_isolation(ctx, plan):
    """[5] 敏感件与噪声源隔离: 敏感集 = U5、X1/X2/X3、含 ADC/SPIADC 网络的元件(剔除噪声源
    自身及其共 ADC 网的随行 RC) → 到 U8/U4/L2/L3/L4/L8 本体间隙。
    阈值 ≥10mm 绿 / 6–10mm 黄 / <6mm 红。工程依据见文件头 [5]。"""
    it = Item(5, "isolation", "敏感件与噪声源隔离",
              ["阈值(本体间隙): ≥10mm 绿 / 6–10mm 黄 / <6mm 红",
               "依据: AS5600 磁编码器(电机轴下)对磁场最敏感——功率电感漏磁直接变成角度误差; "
               "晶振/ADC 对电场-磁场耦合敏感; 源 = U8/U4 及其电感 L2/L3/L4/L8",
               "近场耦合衰减快(磁场∝1/r³, 电场∝1/r²), ≥10mm 无屏蔽时通常已可忽略, <6mm 判红",
               "敏感集剔除: 噪声源自身、以及与噪声源 IC 共 ADC 网的随行 RC(ADCx.1 这类物理上必须"
               "紧贴源的元件), 否则恒定判红属规则伪影"])
    m = ctx.model
    md = {m.info[i]["d"]: m.info[i] for i in range(len(m.info))}
    noise = [d for d in NOISE_SRC if d in ctx.byD]
    sens = set(d for d in SENSITIVE_FIXED if d in ctx.byD)
    for n, cs in m.net_comps.items():
        if not n or not re.search(r"ADC", n, re.I):
            continue
        ds = set(m.info[i]["d"] for i in cs)
        if ds & set(noise):
            continue
        sens |= ds
    sens -= set(noise)
    nb = {d: plan.body(d) for d in noise}
    rows = []
    for s in sorted(sens):
        b = plan.body(s)
        best = None
        for d2 in noise:
            gap = float(b.distance(nb[d2]))
            cd = float(math.dist(plan.pos(s), plan.pos(d2)))
            if best is None or gap < best[0]:
                best = (gap, d2, cd)
        gr, why = band(best[0], TH_ISO, reverse=True)
        it.add(mk_check("%s→最近噪声源 %s" % (s, best[1]), best[0], gr,
                        note="%s: 本体间隙 %.2fmm, 中心距 %.2fmm" % (why, best[0], best[2]),
                        sens=s, noise=best[1], gap_mm=round(best[0], 3),
                        center_mm=round(best[2], 3)))
    it.metrics = {"sensitive": sorted(sens), "noise_sources": noise}
    return it.finalize()


# ==================================================================== [6] 地拓扑
def item6_ground(ctx, plan):
    """[6] 地拓扑分区: 四组 {GND, AGND, PGND, GND_BK} 的包围盒/质心/组间质心距/包围盒重叠面积。
    AGND×PGND 重叠 >0 且重叠区内两组元件都有 → 红(混区); 仅重叠 → 黄; 无重叠 → 绿。
    net-tie(R12/R13/R14) 到其连接的两组质心连线距离 ≤5mm 绿 / 5–10 黄 / >10 红。
    工程依据见文件头 [6]。"""
    it = Item(6, "ground", "地拓扑分区",
              ["AGND/PGND 包围盒重叠 >0 且重叠区内两组元件都有 → 红(模拟地/功率地混区); 仅重叠 → 黄; 无重叠 → 绿",
               "net-tie(R12/R13/R14) 到其所连两组质心连线距离: ≤5mm 绿 / 5–10mm 黄 / >10mm 红",
               "依据: 模拟地与功率地必须单点/小面积汇合, 混区会让电机/开关大电流在地平面产生 ΔV 并"
               "经参考地串入 ADC/编码器; net-tie 就是两条地电流路径的唯一汇合点, 应落在两组交界处"])
    m = ctx.model
    mem = {}
    for g in GND_GROUPS:
        rx = re.compile(r"^%s$" % g)
        mem[g] = [c["d"] for c in m.info
                  if any(rx.match(n or "") for n in m.comp_nets.get(c["idx"], set()))]
    info = {}
    for g in GND_GROUPS:
        ds = mem[g]
        if not ds:
            info[g] = None
            continue
        xs = [plan.pos(d)[0] for d in ds]
        ys = [plan.pos(d)[1] for d in ds]
        info[g] = {"n": len(ds), "bbox": (min(xs), min(ys), max(xs), max(ys)),
                   "centroid": (sum(xs) / len(xs), sum(ys) / len(ys)), "members": ds}
    # AGND x PGND
    a, p = info.get("AGND"), info.get("PGND")
    if a and p:
        ax0, ay0, ax1, ay1 = a["bbox"]
        px0, py0, px1, py1 = p["bbox"]
        ox = max(0.0, min(ax1, px1) - max(ax0, px0))
        oy = max(0.0, min(ay1, py1) - max(ay0, py0))
        area = ox * oy
        rect = None
        if area > 0:
            rect = (max(ax0, px0), max(ay0, py0), min(ax1, px1), min(ay1, py1))
            in_a = [d for d in a["members"]
                    if rect[0] <= plan.pos(d)[0] <= rect[2] and rect[1] <= plan.pos(d)[1] <= rect[3]]
            in_p = [d for d in p["members"]
                    if rect[0] <= plan.pos(d)[0] <= rect[2] and rect[1] <= plan.pos(d)[1] <= rect[3]]
            a_only = [d for d in in_a if d not in mem["PGND"]]
            p_only = [d for d in in_p if d not in mem["AGND"]]
            if in_a and in_p:
                gr, note = "红", ("红: 重叠区内同时有 AGND(%s) 与 PGND(%s) 元件 → 模拟/功率地混区; "
                                  "仅属单组的混区件: AGND-only %s, PGND-only %s"
                                  % (",".join(in_a[:5]), ",".join(in_p[:5]),
                                     ",".join(a_only) or "无", ",".join(p_only) or "无"))
                it.metrics["overlap_mixed_parts"] = {"agnd_only_in_overlap": a_only,
                                                     "pgnd_only_in_overlap": p_only,
                                                     "agnd_in_overlap": in_a, "pgnd_in_overlap": in_p}
            else:
                gr, note = "黄", "黄: 包围盒交叠(%.1fmm²)但重叠区内无两组共存" % area
            it.add(mk_check("AGND×PGND 包围盒重叠", area, gr, unit="mm^2", note=note,
                            overlap_rect=rect, agnd_in_overlap=in_a, pgnd_in_overlap=in_p))
        else:
            it.add(mk_check("AGND×PGND 包围盒重叠", 0.0, "绿", unit="mm2",
                            note="绿: 两组包围盒不重叠"))
    else:
        it.add(mk_check("AGND×PGND 包围盒重叠", None, "绿", unit="mm2",
                        note="绿: 缺任一组(AGND/PGND)成员, 无混区风险"))
    # net-tie
    for d in NET_TIES:
        c = ctx.byD.get(d)
        if c is None:
            continue
        nets = [n for n in m.comp_nets.get(c["idx"], set()) if n]
        gs = [g for g in GND_GROUPS if any(re.match(r"^%s$" % g, n) for n in nets)]
        pair = None
        for x in gs:
            for y in gs:
                if x < y and info.get(x) and info.get(y):
                    pair = (x, y)
        if not pair:
            it.add(mk_check("%s net-tie" % d, None, "黄",
                            note="黄: 未识别到它连接的两组地(%s)" % ",".join(gs or ["?"]), tie=d))
            continue
        (gx, gy) = pair
        p1 = np.array(info[gx]["centroid"])
        p2 = np.array(info[gy]["centroid"])
        q = np.array(plan.pos(d))
        v = p2 - p1
        L2 = float((v ** 2).sum())
        t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, float((q - p1) @ v) / L2))
        foot = p1 + t * v
        dist = float(np.hypot(*(q - foot)))
        gr, why = band(dist, TH_TIE_LINE)
        it.add(mk_check("%s net-tie(%s-%s)" % (d, gx, gy), dist, gr,
                        note="%s: 到两组质心连线(垂足)距离" % why,
                        tie=d, pair="%s-%s" % (gx, gy),
                        tie_nets=sorted(nets),
                        centroid_line_mm=round(float(np.hypot(*(p2 - p1))), 3),
                        foot=[round(float(foot[0]), 3), round(float(foot[1]), 3)]))
    # 组间质心距离 + 全部 6 对包围盒重叠面积(题面要求输出"组间质心距离与包围盒重叠面积")
    cdist = {}
    ovl = {}
    for i, g1 in enumerate(GND_GROUPS):
        for g2 in GND_GROUPS[i + 1:]:
            if info.get(g1) and info.get(g2):
                cdist["%s-%s" % (g1, g2)] = round(float(math.dist(info[g1]["centroid"],
                                                                 info[g2]["centroid"])), 3)
                x0, y0, x1, y1 = info[g1]["bbox"]
                a0, b0, a1, b1 = info[g2]["bbox"]
                ox = max(0.0, min(x1, a1) - max(x0, a0))
                oy = max(0.0, min(y1, b1) - max(y0, b0))
                ovl["%s-%s" % (g1, g2)] = round(ox * oy, 3)
    it.notes.append("组间质心距离(mm): " + ", ".join("%s=%.2f" % (k, v) for k, v in cdist.items()))
    it.notes.append("包围盒重叠面积(mm²): " + ", ".join("%s=%.2f" % (k, v) for k, v in ovl.items()))
    for g in GND_GROUPS:
        if info.get(g):
            it.notes.append("组 %-6s n=%3d 包围盒=(%.2f,%.2f)-(%.2f,%.2f) 质心=(%.2f,%.2f)"
                            % (g, info[g]["n"], info[g]["bbox"][0], info[g]["bbox"][1],
                               info[g]["bbox"][2], info[g]["bbox"][3],
                               info[g]["centroid"][0], info[g]["centroid"][1]))
    it.metrics = {"groups": {g: (None if info[g] is None else
                                 {"n": info[g]["n"], "bbox": [round(x, 3) for x in info[g]["bbox"]],
                                  "centroid": [round(x, 3) for x in info[g]["centroid"]],
                                  "members": info[g]["members"]})
                             for g in GND_GROUPS},
                  "centroid_dist_mm": cdist, "bbox_overlap_mm2": ovl}
    return it.finalize()


# ==================================================================== [7] RF 链
def item7_rf(ctx, plan):
    """[7] RF 匹配链: 从 U6 的 ANT/RF 焊盘出发, 沿实测 RF 网络(RF / ANT*, 排除电源与地网)经
    匹配元件走到天线本体(ANT-SMD), 折线长 = 各元件中心点连线长度; 另判天线到板边净空区距离。
    阈值 链长 ≤8mm 绿 / 8–12mm 黄 / >12mm 红; 天线净空: 在区内(≈0)绿 / ≤3mm 黄 / >3mm 红。
    工程依据见文件头 [7]。"""
    it = Item(7, "rf", "RF 匹配链(2.4GHz)",
              ["链长(U6→匹配件→天线 的中心折线): ≤8mm 绿 / 8–12mm 黄 / >12mm 红",
               "天线本体到板边净空区(84.6–90.5 × 31.0–39.0)距离: 在区内绿 / ≤3mm 黄 / >3mm 红",
               "依据: 2.4GHz 上 1mm 走线≈0.7nH≈10Ω 感性阻抗, 任何支节长度都会破坏匹配、抬高插损与"
               "VSWR, 匹配链应紧凑到 8mm 量级; 天线必须位于板边净空区, 否则辐射效率/方向图被破坏",
               "数据修正: 题面称 C65~C68 为匹配网络, 实测 C67/C68 是 USB1 旁 +5V 去耦; 实测链为 "
               "U6 --RF-- L6 --$1N19735-- L7(ANT-SMD), 并联件 C65/C66/C55/C56/C57"])
    m = ctx.model
    u6 = ctx.byD.get("U6")
    ant = ctx.antenna[0] if ctx.antenna else None
    if u6 is None or ant is None:
        it.add(mk_check("RF 链", None, "红", note="红: 找不到 U6 或 ANT-SMD 天线本体"))
        return it.finalize()
    # RF 网络集: 名字含 RF/ANT 的非电源/地网络 ∪ 题面点名件与 U6 共用的非电源/地网络
    rf_nets = set()
    for n in m.net_comps:
        if not n or GND_RE.match(n) or POWER_RE.match(n):
            continue
        u = n.upper()
        if u == "RF" or "ANT" in u or u.startswith("RF"):
            rf_nets.add(n)
    named = set(RF_NAMED) | {ant["d"], "U6"}
    for n, cs in m.net_comps.items():
        if not n or GND_RE.match(n) or POWER_RE.match(n):
            continue
        ds = set(m.info[i]["d"] for i in cs)
        if ds & named:
            rf_nets.add(n)
    nodes = set()
    for n in rf_nets:
        for i in m.net_comps.get(n, []):
            nodes.add(m.info[i]["d"])
    # Dijkstra(按中心距)
    adj = defaultdict(list)
    for n in rf_nets:
        ds = sorted(set(m.info[i]["d"] for i in m.net_comps.get(n, [])))
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                w = float(math.dist(plan.pos(ds[i]), plan.pos(ds[j])))
                adj[ds[i]].append((ds[j], w, n))
                adj[ds[j]].append((ds[i], w, n))
    import heapq
    src, dst = "U6", ant["d"]
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    seen = set()
    while pq:
        dcur, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        for v, w, n in adj[u]:
            if dcur + w < dist.get(v, 1e18) - 1e-12:
                dist[v] = dcur + w
                prev[v] = (u, n, w)
                heapq.heappush(pq, (dcur + w, v))
    chain = []
    if dst in dist:
        cur = dst
        while cur != src:
            u, n, w = prev[cur]
            chain.append({"from": u, "to": cur, "net": n, "mm": round(w, 3)})
            cur = u
        chain.reverse()
    total = dist.get(dst)
    gr, why = band(total, TH_RF_CHAIN)
    if total is None:
        it.add(mk_check("U6→天线 匹配链长", None, "红",
                        note="红: 在实测 RF 网络中找不到 U6 到天线的连通路径"))
    else:
        it.add(mk_check("U6→天线 匹配链长(%d 跳)" % len(chain), total, gr,
                        note="%s: %s" % (why, " + ".join("%s→%s %s %.2fmm" % (c["from"], c["to"],
                                                                            c["net"], c["mm"])
                                                         for c in chain)),
                        hops=chain))
    # 天线到净空区
    ak = sh_box(*ANT_KEEPOUT)
    ab = plan.body(ant["d"])
    # 板边净空是"区域内外"关系: 天线在区内 -> 0
    dk = 0.0 if (ab.intersects(ak) or ak.contains(ab) or ab.contains(ak)) else float(ab.distance(ak))
    gr, why = band(dk, TH_ANT_KEEPOUT)
    it.add(mk_check("%s 天线→板边净空区" % ant["d"], dk, gr,
                    note="%s: 净空区 x%.1f–%.1f / y%.1f–%.1f" % (why, ANT_KEEPOUT[0],
                                                                ANT_KEEPOUT[2], ANT_KEEPOUT[1],
                                                                ANT_KEEPOUT[3]),
                    antenna=ant["d"], keepout=list(ANT_KEEPOUT)))
    # 并联件到链路的距离(信息)
    shunt = []
    for d in RF_NAMED:
        if d not in ctx.byD:
            continue
        dd = float(plan.body(d).distance(ab))
        shunt.append({"d": d, "f": ctx.byD[d]["f"], "mm_to_ant": round(dd, 3),
                      "nets": sorted(n for n in m.comp_nets.get(ctx.byD[d]["idx"], set()) if n)})
    it.metrics = {"rf_nets": sorted(rf_nets), "nodes": sorted(nodes), "chain": chain,
                  "chain_mm": (round(total, 3) if total is not None else None),
                  "antenna": ant["d"], "shunt_named": shunt}
    return it.finalize()


ITEM_FUNCS = (item1_decap, item2_ic_gnd, item3_hotloop, item4_xtal, item5_isolation,
              item6_ground, item7_rf)


# ==================================================================== 一致性自检
def consistency(ctx, comps_path, live_path, plan):
    """证明与 place_verify.py 不冲突:
    (1) 焊盘→元件归属: 用独立实现(同代价矩阵 + scipy 全局最优指派)复算并与所用后端逐焊盘比对;
    (2) 本体几何: 独立实现(旋转矩形)复算每个元件本体的面积/包围盒, 与 plan.body() 比对;
    (3) 焊盘刚体性: 每个焊盘到其属主中心距离在平移/旋转前后不变。"""
    out = {}
    m = ctx.model
    try:
        mm = MiniModel(comps_path, live_path)
        same = sum(1 for a, b in zip(m.pad_comp, mm.pad_comp) if a == b)
        cost_a = sum(m.assign_cost)
        cost_b = sum(mm.assign_cost)
        out["pad_assign"] = {"backend": ctx.backend, "n_pads": len(m.pads),
                             "n_same_owner": same, "identical": same == len(m.pads),
                             "cost_backend_mm": round(cost_a, 6),
                             "cost_independent_mm": round(cost_b, 6),
                             "cost_equal": abs(cost_a - cost_b) < 1e-6,
                             "mean_dist_mm": round(m.assign_stats["mean_dist_mm"], 4),
                             "max_dist_mm": round(m.assign_stats["max_dist_mm"], 4),
                             "layer_penalized": m.assign_stats["layer_penalized"]}
    except Exception as e:                                     # pragma: no cover
        out["pad_assign"] = {"error": str(e)}
    mp = MiniPlan(ctx.model, plan.moves, plan.rots, plan.name)
    dmax = 0.0
    amax = 0.0
    worst = None
    P1 = plan.pad_points()
    P2 = mp.pad_points()
    for ci, c in enumerate(m.info):
        g1, g2 = plan.body(c["d"]), mp.body(c["d"])
        amax = max(amax, abs(abs(g1.area) - abs(g2.area)))
        dmax = max(dmax, max(abs(x - y) for x, y in zip(g1.bounds, g2.bounds)))
        # 焊盘相对属主中心的距离守恒(刚体变换)
        for pi in m.pads_by_comp.get(ci, []):
            r0 = math.dist(P1[pi], plan.pos(c["d"]))
            r1 = math.dist(P2[pi], mp.pos(c["d"]))
            if abs(r0 - r1) > 1e-6:
                worst = max(worst or 0.0, abs(r0 - r1))
    out["body_geometry"] = {"backend": ctx.backend, "n_comps": len(m.info),
                            "area_diff_max_mm2": round(amax, 12),
                            "bounds_diff_max_mm": round(dmax, 12),
                            "pad_rigid_max_diff_mm": round(worst or 0.0, 12),
                            "identical": (amax < 1e-9 and dmax < 1e-9 and (worst or 0.0) < 1e-6)}
    out["geometry_model"] = ("本体=place_verify.Plan.body() 旋转矩形多边形; 焊盘=plan.pad_points() "
                             "焊盘中心随属主平移/旋转; 板框/天线净空取自 place_verify 常量")
    out["conflict"] = bool(out.get("pad_assign", {}).get("identical") is False
                           or out.get("body_geometry", {}).get("identical") is False)
    return out


# ==================================================================== 报告
def render_report(comps, live, plan_name, items, total, total_grade, cons, planinfo,
                  limit, cmp_rows=None, cmp_total=None, out_path=None, fps=None):
    L = []
    ap = L.append
    ap("=" * 100)
    ap(" PCB 摆放电气性能评分器 place_elec.py  —  纯离线, 只读 comps3.json / live.json, 不联网")
    ap(" 基准元件表: %-20s  焊盘实测: %-20s" % (comps, live))
    if fps:
        for k, v in fps.items():
            ap("   输入指纹 : %-14s %s %s (%d bytes)" % (k, v.get("sha256_16", "?"),
                                                          v.get("mtime", "?"), v.get("bytes", 0)))
    ap(" 评分对象  : %s" % plan_name)
    if planinfo:
        ap(" 方案摘要  : %s" % planinfo)
    pa = cons.get("pad_assign", {})
    if "identical" in pa:
        ap(" 焊盘归属  : %s 全局最优指派(scipy linear_sum_assignment, 层惩罚100mm) "
           "与独立复算一致=%s (%d/%d 焊盘同属主, 总代价 %.3f/%.3fmm, 层惩罚项 %d)"
           % (pa.get("backend"), "是" if pa["identical"] else "否", pa.get("n_same_owner", 0),
              pa.get("n_pads", 0), pa.get("cost_backend_mm", 0), pa.get("cost_independent_mm", 0),
              pa.get("layer_penalized", 0)))
    bg = cons.get("body_geometry", {})
    if bg:
        ap(" 本体几何  : %s 旋转矩形多边形; 与独立复算一致=%s (面积差 %.1e mm², 包围盒差 %.1e mm, "
           "焊盘刚体差 %.1e mm)" % (bg.get("backend"), "是" if bg.get("identical") else "否",
                                   bg.get("area_diff_max_mm2", 0), bg.get("bounds_diff_max_mm", 0),
                                   bg.get("pad_rigid_max_diff_mm", 0)))
    ap(" 与 place_verify 冲突: %s" % ("有(见上)" if cons.get("conflict") else "无"))
    ap(" 评分口径  : 每项等权; 单项 = 100×(绿 + 0.5×黄)/检查项数; 单项结论: 无红且≥90 绿, "
       "红项≥50% 或(有红且<60) 红, 其余黄; 总分 = 7 项均值 (≥85 绿 / 65–85 黄 / <65 红)")
    ap("=" * 100)

    for it in items:
        ap("")
        ap("─" * 100)
        ap("第 %d 项  %s          结论: %s   得分: %.1f/100   检查项 %d (绿%d/黄%d/红%d)"
           % (it["id"], it["title"], it["grade"], it["score"], it["n_checks"],
              it["counts"]["green"], it["counts"]["yellow"], it["counts"]["red"]))
        ap("   关键数字: %s" % _key_numbers(it))
        ap("─" * 100)
        for r in it["rationale"]:
            ap("  [依据] %s" % r)
        if it.get("notes"):
            for n in it["notes"]:
                ap("  [说明] %s" % n)
        rows = sorted_checks(it["checks"], limit)
        for c in rows:
            v = "-" if c["value"] is None else ("%s%s" % (f2(c["value"]), c["unit"]))
            ap("   %s %-42s %10s   %s" % ({"绿": "[绿]", "黄": "[黄]", "红": "[红]"}.get(c["grade"], "[--]"),
                                          c["label"][:42], v, c["note"]))
        if it["n_checks"] > len(rows):
            ap("   ... 其余 %d 条明细见 --json (--limit %d)" % (it["n_checks"] - len(rows), limit))

    ap("")
    ap("-" * 100)
    ap(" 重点关注(全部红项, 按严重度排序, 最多 %d 条; 完整明细见 --json):" % min(limit, 12))
    reds = []
    for it in items:
        for c in it["checks"]:
            if c["grade"] == "红":
                reds.append((it["id"], it["title"], c))
    reds.sort(key=lambda t: -(t[2]["value"] if t[2]["value"] is not None else 1e9))
    if not reds:
        ap("   (无红项)")
    for iid, title, c in reds[:min(limit, 12)]:
        v = "-" if c["value"] is None else ("%s%s" % (f2(c["value"]), c["unit"]))
        ap("   [%d] %-40s %10s  %s" % (iid, c["label"][:40], v, c["note"][:78]))
    if len(reds) > min(limit, 12):
        ap("   ... 共 %d 条红项" % len(reds))
    ap("")
    ap("=" * 100)
    ap(" 总表: 7 项等权 (每项 = 100×(绿+0.5×黄)/检查项数; 总分 = 7 项均值)")
    ap("-" * 100)
    ap("  #  指标                        结论   得分    绿/黄/红   关键数字")
    for it in items:
        key = _key_numbers(it)
        ap("  %d  %-26s  %s  %6.1f   %2d/%2d/%2d   %s"
           % (it["id"], it["title"][:26], it["grade"], it["score"], it["counts"]["green"],
              it["counts"]["yellow"], it["counts"]["red"], key))
    ap("-" * 100)
    globals()["_SCORE"] = float(total)
    ap("  电气摆放分 = %.1f / 100  (结论: %s)    [≥85 绿 / 65–85 黄 / <65 红]" % (total, total_grade))
    if cmp_rows is not None:
        ap("")
        ap(" 与『当前摆放』对照:")
        ap("  #  指标                        当前      方案      变化")
        for a, b in cmp_rows:
            ap("  %d  %-26s  %6.1f    %6.1f    %+6.1f  %s"
               % (a["id"], a["title"][:26], a["score"], b["score"], b["score"] - a["score"],
                  ("更好" if b["score"] > a["score"] else ("更差" if b["score"] < a["score"] else "持平"))))
        ap("  合计电气摆放分: 当前 %.1f (%s)  →  方案 %.1f (%s)   变化 %+.1f"
           % (cmp_total[0], cmp_total[2], cmp_total[1], cmp_total[3], cmp_total[1] - cmp_total[0]))
    ap("=" * 100)
    if out_path:
        ap(" 结构化结果: %s" % out_path)
    return "\n".join(L)


def _key_numbers(it):
    k = it["key"]
    md = it["metrics"]
    if k == "decap":
        worst = max((c["value"] for c in it["checks"] if c["value"] is not None), default=None)
        nocap = sum(1 for c in it["checks"] if c["value"] is None)
        return "最差 %.1fmm; 无电容网络 %d" % (worst if worst is not None else -1, nocap)
    if k == "ic_gnd":
        worst = max((c["value"] for c in it["checks"] if c["value"] is not None), default=None)
        return "最差 %.1fmm; 过孔 %d 个%s" % (worst if worst is not None else -1, md.get("n_vias", 0),
                                            "" if md.get("n_vias") else "(vias 未导出)")
    if k == "hotloop":
        return "MST %.1fmm / 下界 %.1f = %.2f" % (md.get("mst_mm", 0), md.get("lower_bound_mm", 0),
                                                  md.get("ratio", 0))
    if k == "xtal":
        return "IC距 %s; 对称差 %s; 开关距 %s" % (
            _nums(it, "晶振脚距离"), _nums(it, "负载电容对称度"), _nums(it, "最近开关节点"))
    if k == "isolation":
        worst = min((c["value"] for c in it["checks"] if c["value"] is not None), default=None)
        return "最小间隙 %.1fmm" % (worst if worst is not None else -1)
    if k == "ground":
        ov = [c for c in it["checks"] if "重叠" in c["label"]]
        ties = [c["value"] for c in it["checks"] if "net-tie" in c["label"] and c["value"] is not None]
        return "AGND×PGND 重叠 %smm2; net-tie 最差 %.1fmm" % (
            f2(ov[0]["value"], 1) if ov else "-", max(ties) if ties else -1)
    if k == "rf":
        return "链长 %smm; 净空 %smm" % (f2(md.get("chain_mm"), 2),
                                        f2([c["value"] for c in it["checks"] if "净空" in c["label"]][0], 2))
    return ""


def _nums(it, kw):
    """把同一关键词的检查项数值按元件顺序串成 "4.9/3.8/4.8" 形式"""
    vs = [c for c in it["checks"] if kw in c["label"] and c["value"] is not None]
    if not vs:
        return "-"
    return "/".join(f2(c["value"], 1) for c in vs)


def jdump(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False, default=lambda o: None))


# ==================================================================== main
def score_all(ctx, plan):
    return [f(ctx, plan) for f in ITEM_FUNCS]


def main(argv=None):
    reconf(sys.stdout)
    reconf(sys.stderr)
    ap = argparse.ArgumentParser(
        description="PCB 摆放电气性能评分器 (纯离线, 只读输入; 与 place_verify.py 同口径几何/归属)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("placement", nargs="?", default=None, help="候选方案 JSON (moves/rot)")
    ap.add_argument("--json", dest="json_out", default=None, help="结构化结果输出路径")
    ap.add_argument("--comps", default=os.path.join(HERE, "comps3.json"))
    ap.add_argument("--live", default=os.path.join(HERE, "live.json"))
    ap.add_argument("--limit", type=int, default=25, help="文本明细每项最多打印条数 (默认 25)")
    ap.add_argument("--quiet", action="store_true", help="只写 --json, 不打印文本")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.comps) or not os.path.isfile(args.live):
        sys.stderr.write("找不到输入: %s / %s\n" % (args.comps, args.live))
        return 2
    if args.json_out:
        low = os.path.basename(args.json_out).lower()
        if low in ("comps3.json", "live.json", "placement_new.json"):
            sys.stderr.write("拒绝写入受保护文件: %s\n" % args.json_out)
            return 2

    t0 = time.time()
    Model, Plan, backend, pv_mod, _MM, _MP = load_backends(args.comps, args.live)
    ctx = Ctx(args.comps, args.live, Model, Plan)
    ctx.backend = backend
    moves, rots, notes = ({}, {}, [])
    if args.placement:
        try:
            if pv_mod is not None:
                moves, rots, notes = pv_mod.parse_plan_file(args.placement)
            else:
                with io.open(args.placement, "r", encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                mv = data.get("moves", {}) if isinstance(data, dict) else {}
                for d, v in (mv or {}).items():
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        moves[str(d)] = (float(v[0]), float(v[1]))
                for d, v in ((data.get("rot") or data.get("rots") or {}) if isinstance(data, dict)
                             else {}).items():
                    rots[str(d)] = float(v)
        except Exception as e:
            globals()["_INPUT_ERR"] = True
            sys.stderr.write("[错误] 方案文件解析失败(%s), 按空方案处理 (退出码 2)\n" % e)

    cur_plan = ctx.plan({}, {}, "当前摆放 (comps3.json)")
    cur_items = score_all(ctx, cur_plan)
    cur_total = round(sum(i["score"] for i in cur_items) / len(cur_items), 2)
    cur_grade = "绿" if cur_total >= 85 else ("黄" if cur_total >= 65 else "红")

    cons = consistency(ctx, args.comps, args.live, cur_plan)

    items, total, grade, planinfo = cur_items, cur_total, cur_grade, None
    cmp_rows = cmp_total = None
    plan_name = "当前摆放 comps3.json"
    if args.placement:
        plan = ctx.plan(moves, rots, "方案 " + os.path.basename(args.placement))
        items = score_all(ctx, plan)
        total = round(sum(i["score"] for i in items) / len(items), 2)
        grade = "绿" if total >= 85 else ("黄" if total >= 65 else "红")
        n_moved = sum(1 for d in ctx.model.D if math.hypot(*plan.delta(d)) > 1e-9)
        planinfo = ("%s: 位移件 %d, 旋转件 %d, 明细 %s"
                    % (os.path.basename(args.placement), n_moved, len(plan.drot),
                       "; ".join(notes[:3]) if notes else "无"))
        plan_name = "方案 " + os.path.basename(args.placement)
        cmp_rows = list(zip(cur_items, items))
        cmp_total = (cur_total, total, cur_grade, grade)
        # 方案的一致性自检也复算一遍(几何/归属应保持一致)
        cons2 = consistency(ctx, args.comps, args.live, plan)
        cons["pad_assign_plan"] = cons2.get("pad_assign")
        cons["body_geometry_plan"] = cons2.get("body_geometry")
        cons["conflict"] = bool(cons.get("conflict") or cons2.get("conflict"))

    fp = {"comps": fingerprint(args.comps), "live": fingerprint(args.live)}
    if args.placement:
        fp["plan"] = fingerprint(args.placement)

    if not args.quiet:
        txt = render_report(os.path.basename(args.comps), os.path.basename(args.live), plan_name,
                            items, total, grade, cons, planinfo, args.limit, cmp_rows, cmp_total,
                            args.json_out, fp)
        sys.stdout.write(txt + "\n")

    if args.json_out:
        payload = {
            "tool": "place_elec.py", "offline": True,
            "input": {"comps": args.comps, "live": args.live}, "input_fingerprint": fp,
            "plan": {"path": args.placement, "name": plan_name, "info": planinfo,
                     "n_moves": len(moves), "n_rots": len(rots), "notes": notes},
            "consistency": cons,
            "items": items,
            "total_score": total, "total_grade": grade,
            "current": {"total_score": cur_total, "total_grade": cur_grade,
                        "items": [{"id": i["id"], "title": i["title"], "score": i["score"],
                                   "grade": i["grade"], "counts": i["counts"]} for i in cur_items]},
            "compare": ([{"id": a["id"], "title": a["title"], "current": a["score"],
                          "proposed": b["score"], "delta": round(b["score"] - a["score"], 2)}
                         for a, b in cmp_rows] if cmp_rows else None),
            "thresholds": {"decap_mm": TH_DECAP, "ic_gnd_mm": TH_ICGND,
                           "loop_ratio": TH_LOOP_RATIO, "xtal_ic_mm": TH_XTAL_IC,
                           "xtal_cap_skew_mm": TH_XTAL_CAP_SKEW, "xtal_switch_mm": TH_XTAL_SW,
                           "isolation_mm": TH_ISO, "net_tie_line_mm": TH_TIE_LINE,
                           "rf_chain_mm": TH_RF_CHAIN, "ant_keepout_mm": TH_ANT_KEEPOUT},
            "geometry_model": cons.get("geometry_model"),
            "elapsed_s": round(time.time() - t0, 3),
        }
        d = os.path.dirname(os.path.abspath(args.json_out))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with io.open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(jdump(payload), ensure_ascii=False, indent=1))
        if not args.quiet:
            sys.stdout.write("结构化结果已写入: %s\n" % args.json_out)
    if globals().get("_INPUT_ERR"):
        return 2
    try:
        _tot = float(globals().get('_SCORE', 0.0))
    except Exception:
        _tot = 0.0
    return 1 if (_tot < 65.0) else 0


if __name__ == "__main__":
    sys.exit(main())
