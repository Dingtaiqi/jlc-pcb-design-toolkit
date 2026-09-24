#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stitch_connections.py -- 连接缝合器 (EasyEDA Pro 4 层板, 经本地桥接)

把 drc_full.py / drc_to_commands.py 报出的 "Connection Error"（网络被拆成孤岛）
用最短可行铜连起来: 单层走线优先, 必要时换层加过孔; 加完后重铺铺铜并跑 DRC 复核。

用法:
    python stitch_connections.py --plan                 # 只规划(默认), 不改板子
    python stitch_connections.py --apply                # 实际落铜
    python stitch_connections.py --apply --nets A,B     # 只做指定网络
    python stitch_connections.py --apply --allow-narrow # 允许比本网线宽更细的补线
    python stitch_connections.py --rebuild-pours        # 只重铺铺铜
    python stitch_connections.py --rollback-created FILE# 删除本工具创建的图元(回滚)

设计要点:
  * 判据: 新铜对"异网铜(线/焊盘/过孔)"必须保持 >= CLEAR(默认 6mil=0.1524mm) 净距;
    铺铜不算障碍 —— 落铜后调用 eda.pcb_PrimitivePour.rebuildCopperRegion() 让铺铜重新挖孔。
  * 规划 = 局部窗口内对异网铜做距离变换, 二分阈值 + 连通性检查, 取 maximin 路径, RDP 简化后再逐段采样复核。
  * 幂等: 每次都重新读板子并重算连通分量, 已连通的网络直接跳过。
  * 只读约束: 不改元件、不碰天线匹配件(L7/C65/C66/L6/R28)、不调用 router DSL、不写 live.json/comps3.json。
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys
import time

import numpy as np
from scipy import ndimage
import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

try:
    import drc_full
except Exception:
    drc_full = None

MIL_PER_MM = 39.3701
CLEAR = 0.1524          # 6 mil
OFFICIAL_MARGIN = 0.12  # 板上 DRC 有效阈值约 0.10mm, 退让时至少留 0.12mm
VIA_HOLE = 0.305 / 0.0254   # mil (12 mil drill)
VIA_DIA = 0.610 / 0.0254    # mil (24 mil)
FORBIDDEN = ('L7', 'C65', 'C66', 'L6', 'R28')     # 天线匹配网络: 只读, 不作为连接目标
LAYERS = (1, 2, 15, 16)


# --------------------------------------------------------------------------
# 桥接/板子读取
# --------------------------------------------------------------------------
DUMP_JS = r"""
const MM = 1/39.3701;
const NM = function(n){ if(n==null) return ''; if(typeof n==='string') return n; if(n.name!==undefined) return String(n.name); return String(n); };
const L = await eda.pcb_PrimitiveLine.getAll();
const lines = [];
L.forEach(function(l){ lines.push([String(l.getState_PrimitiveId()), NM(l.getState_Net()), l.getState_Layer(),
  +(l.getState_StartX()*MM).toFixed(4), +(l.getState_StartY()*MM).toFixed(4),
  +(l.getState_EndX()*MM).toFixed(4), +(l.getState_EndY()*MM).toFixed(4),
  +(l.getState_LineWidth()*MM).toFixed(4)]); });
const V = await eda.pcb_PrimitiveVia.getAll();
const vias = [];
V.forEach(function(v){ vias.push([String(v.getState_PrimitiveId()), NM(v.getState_Net()),
  +(v.getState_X()*MM).toFixed(4), +(v.getState_Y()*MM).toFixed(4),
  +(v.getState_Diameter()*MM).toFixed(4), +(v.getState_HoleDiameter()*MM).toFixed(4)]); });
const P = await eda.pcb_PrimitivePad.getAll();
const pads = [];
P.forEach(function(p){
  let rot=0; try { rot = p.getState_Rotation ? p.getState_Rotation() : 0; } catch(e){}
  let pad=''; try { pad = JSON.stringify(p.getState_Pad()); } catch(e){}
  pads.push([String(p.getState_PrimitiveId()), NM(p.getState_Net()),
    +(p.getState_X()*MM).toFixed(4), +(p.getState_Y()*MM).toFixed(4), p.getState_Layer(),
    pad, rot, String(p.getState_PadNumber ? p.getState_PadNumber() : '')]);
});
const extra = [];
for (const k of ['pcb_PrimitiveFill', 'pcb_PrimitivePoured', 'pcb_PrimitiveRegion']) {
  try {
    const arr = await eda[k].getAll();
    for (let j = 0; j < arr.length; j++) {
      const o = arr[j];
      let cp = null, net = null, layer = null;
      try { cp = await o.getState_ComplexPolygon(); } catch (e) {}
      try { net = NM(o.getState_Net()); } catch (e) {}
      try { layer = o.getState_Layer(); } catch (e) {}
      extra.push({ kind: k, id: String(o.getState_PrimitiveId()), net: net, layer: layer, cp: cp });
    }
  } catch (e) {}
}
globalThis.__bd2extra = extra;
const PO = await eda.pcb_PrimitivePour.getAll();
const pours = [];
for (let i=0;i<PO.length;i++){
  let rgn=null; try { rgn = await PO[i].getCopperRegion(); } catch(e){}
  pours.push({ net: NM(PO[i].getState_Net()), layer: PO[i].getState_Layer(),
               id: String(PO[i].getState_PrimitiveId()), nfills: rgn && rgn.pourFills ? rgn.pourFills.length : 0 });
}
globalThis.__bd2 = { lines: lines, vias: vias, pads: pads, pours: pours, extra: extra };
return JSON.stringify({ lines: lines.length, vias: vias.length, pads: pads.length,
                        pours: pours.length, extra: extra.length,
                        bytes: JSON.stringify(globalThis.__bd2).length });
"""

FETCH_JS = r"""
const bd = globalThis.__bd2;
if (!bd) return JSON.stringify({ __err: 'no board dump' });
const key = '__KEY__'; const a = __A__, b = __B__;
const arr = bd[key] || [];
return JSON.stringify({ total: arr.length, items: arr.slice(a, b) });
"""

CREATE_LINE_JS = r"""
const seg = __SEG__;
const rv = await eda.pcb_PrimitiveLine.create(seg.net, seg.layer,
  seg.x1*39.3701, seg.y1*39.3701, seg.x2*39.3701, seg.y2*39.3701, seg.w*39.3701, false);
const id = (rv && rv.primitiveId) ? String(rv.primitiveId) : String(rv);
return JSON.stringify({ ok: true, id: id });
"""

CREATE_VIA_JS = r"""
const v = __VIA__;
const rv = await eda.pcb_PrimitiveVia.create(v.net, v.x*39.3701, v.y*39.3701,
  v.hole*39.3701, v.dia*39.3701);
const id = (rv && rv.primitiveId) ? String(rv.primitiveId) : String(rv);
return JSON.stringify({ ok: true, id: id });
"""

DELETE_JS = r"""
const ids = __IDS__;
const out = { lines: 0, vias: 0 };
try { out.lines = (await eda.pcb_PrimitiveLine.delete(ids.lines || [])) ? (ids.lines || []).length : 0; } catch(e) { out.line_err = String(e && e.message ? e.message : e); }
try { out.vias = (await eda.pcb_PrimitiveVia.delete(ids.vias || [])) ? (ids.vias || []).length : 0; } catch(e) { out.via_err = String(e && e.message ? e.message : e); }
return JSON.stringify(out);
"""

REBUILD_POURS_JS = r"""
const P = await eda.pcb_PrimitivePour.getAll();
const out = [];
for (let i=0;i<P.length;i++){
  let before=null, after=null;
  try { const r = await P[i].getCopperRegion(); before = r && r.pourFills ? r.pourFills.length : 0; } catch(e){}
  try { await P[i].rebuildCopperRegion(); } catch(e) { out.push({i:i, err:String(e && e.message ? e.message : e)}); continue; }
  try { const r2 = await P[i].getCopperRegion(); after = r2 && r2.pourFills ? r2.pourFills.length : 0; } catch(e){}
  out.push({ i:i, net:String(P[i].getState_Net()), layer:P[i].getState_Layer(), fills_before:before, fills_after:after });
}
return JSON.stringify(out);
"""


def q(js, timeout=900):
    if drc_full is None:
        raise RuntimeError('需要同目录的 drc_full.py')
    return drc_full.bridge_json(js, drc_full.DEFAULT_BRIDGE, timeout)


def dump_board(path='_stitch_board.json', quiet=False):
    counts = q(DUMP_JS)
    if isinstance(counts, dict) and counts.get('__err'):
        raise RuntimeError('读板子失败: %r' % (counts,))
    if not quiet:
        sys.stderr.write('板子: %s\n' % json.dumps(counts, ensure_ascii=False))
    bd = {}
    for key in ('lines', 'vias', 'pads'):
        arr, a, chunk = [], 0, 400
        while True:
            part = q(FETCH_JS.replace('__KEY__', key).replace('__A__', str(a)).replace('__B__', str(a + chunk)))
            arr.extend(part['items'])
            a += chunk
            if a >= part['total']:
                break
        bd[key] = arr
    bd['pours'] = list(q(FETCH_JS.replace('__KEY__', 'pours').replace('__A__', '0')
                         .replace('__B__', '99'))['items'])
    ex = q(FETCH_JS.replace('__KEY__', 'extra').replace('__A__', '0').replace('__B__', '99'))
    bd['extra'] = list(ex.get('items') or [])
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(bd, f, ensure_ascii=False)
    return bd


# --------------------------------------------------------------------------
# 几何 + 连通分量
# --------------------------------------------------------------------------
def th_layer(layer):
    return layer not in LAYERS


def pad_poly(padstr, rot, x, y):
    import json as _j
    from shapely import affinity
    try:
        parts = _j.loads(padstr) if isinstance(padstr, str) else padstr
    except Exception:
        return Point(x, y).buffer(0.3, resolution=12)
    kind = str(parts[0]).upper() if parts else ''
    try:
        if kind.startswith('RECT'):
            w, h = float(parts[1]) * 0.0254, float(parts[2]) * 0.0254
            g = box(-w / 2, -h / 2, w / 2, h / 2)
        elif kind.startswith('CIRCLE') or kind.startswith('ELLIPSE') or kind.startswith('ROUND'):
            w = float(parts[1]) * 0.0254 if len(parts) > 1 else 0.3
            h = float(parts[2]) * 0.0254 if len(parts) > 2 else w
            g = Point(0, 0).buffer(max(w, h) / 2, resolution=16)
        elif kind.startswith('OVAL') or kind.startswith('OBLONG'):
            w, h = float(parts[1]) * 0.0254, float(parts[2]) * 0.0254
            if w >= h:      # 长轴在 X
                g = LineString([(-(w - h) / 2, 0), ((w - h) / 2, 0)]).buffer(h / 2, cap_style=1)
            else:           # 长轴在 Y (EasyEDA: parts[1]=X宽, parts[2]=Y高)
                g = LineString([(0, -(h - w) / 2), (0, (h - w) / 2)]).buffer(w / 2, cap_style=1)
        else:
            w = float(parts[1]) * 0.0254 if len(parts) > 1 else 0.3
            h = float(parts[2]) * 0.0254 if len(parts) > 2 else w
            g = box(-w / 2, -h / 2, w / 2, h / 2)
    except Exception:
        return Point(x, y).buffer(0.3, resolution=12)
    g = affinity.rotate(g, math.degrees(rot or 0.0), origin=(0, 0))
    return affinity.translate(g, x, y)


def _complex_to_polys(cp, scale=None):
    """EasyEDA 多边形 -> shapely 列表。三种形式都要吃:
      1) pour 风格: [[token环], [token环], ...]  坐标单位 0.254mm
      2) Fill 风格: {polygon: [扁平 token 环]}    坐标单位 mil
      3) Region   : {polygon: ['R', x, y, w, h]} 坐标单位 mil (矩形)
    """
    if not cp:
        return []
    if isinstance(cp, dict):
        cp = cp.get('polygon') or cp.get('complexPolygon') or cp.get('complexPolygons') or []
    if not isinstance(cp, list) or not cp:
        return []
    # 形式 3: 矩形 'R', x, y, w, h (mil)
    if isinstance(cp[0], str) and cp[0].upper().startswith('R') and len(cp) >= 5:
        try:
            x, y, w, h = [float(v) * 0.0254 for v in cp[1:5]]
            if w < 0:
                x, w = x + w, -w
            if h < 0:
                y, h = y + h, -h
            return [box(x, y, x + w, y + h)]
        except Exception:
            return []
    if isinstance(cp[0], list):          # 形式 1 (pour): 环的列表, 单位 0.254mm
        rings, sc = cp, (scale if scale else 0.254)
    else:                                 # 形式 2 (Fill): 单个扁平环, 单位 mil
        rings, sc = [cp], (scale if scale else 0.0254)
    out = []
    for ring in rings:
        if not isinstance(ring, list):
            continue
        pts = []
        i, n = 0, len(ring)
        while i < n:
            t = ring[i]
            if isinstance(t, str):
                if t == 'ARC' and i + 1 < n and not isinstance(ring[i + 1], str):
                    i += 2
                else:
                    i += 1
                continue
            if i + 1 < n and not isinstance(ring[i + 1], str):
                pts.append((float(t) * sc, float(ring[i + 1]) * sc))
                i += 2
            else:
                i += 1
        if len(pts) >= 4:
            try:
                g = Polygon(pts)
                if not g.is_valid:
                    g = g.buffer(0)
                if not g.is_empty and g.area > 1e-9:
                    out.append(g)
            except Exception:
                pass
    return out


class Board:
    def __init__(self, bd):
        self.bd = bd
        self.lines = bd['lines']
        self.vias = bd['vias']
        self.pads = bd['pads']
        self.pours = bd['pours']
        self.pad_by_id = {p[0]: p for p in self.pads}
        self.line_by_id = {l[0]: l for l in self.lines}
        self.via_by_id = {v[0]: v for v in self.vias}
        self._pad_poly = {}
        self.copper = collections.defaultdict(lambda: {'lines': [], 'pads': [], 'vias': []})
        for lid, net, layer, x1, y1, x2, y2, w in self.lines:
            if x1 == x2 and y1 == y2:
                continue
            g = LineString([(x1, y1), (x2, y2)]).buffer(max(w, 0.05) / 2.0, cap_style=2)
            self.copper[layer]['lines'].append((g, net, lid))
        for vid, net, x, y, dia, hole in self.vias:
            g = Point(x, y).buffer(max(dia, 0.1) / 2.0, resolution=24)
            for l in LAYERS:
                self.copper[l]['vias'].append((g, net, vid))
        for p in self.pads:
            g = self.poly_of(p)
            for l in (LAYERS if th_layer(p[4]) else (p[4],)):
                self.copper[l]['pads'].append((g, p[1], p[0]))
        # PrimitiveFill / Poured / Region 也是铜(或禁布区), 必须当障碍
        for ex in (bd.get('extra') or []):
            polys = _complex_to_polys(ex.get('cp'))
            if not polys:
                continue
            g = unary_union(polys)
            lx = ex.get('layer')
            tgt = list(LAYERS) if th_layer(lx) else [lx]
            for l in tgt:
                self.copper[l].setdefault('fills', []).append((g, ex.get('net') or '', ex.get('id') or ''))

    def poly_of(self, p):
        if p[0] not in self._pad_poly:
            self._pad_poly[p[0]] = pad_poly(p[5], p[6], p[2], p[3])
        return self._pad_poly[p[0]]

    def mode_width(self, net, default=0.254):
        c = collections.Counter(round(l[7], 4) for l in self.lines if l[1] == net)
        return c.most_common(1)[0][0] if c else default

    def obstacles(self, layer, net, win):
        out = []
        for kind in ('lines', 'pads', 'vias', 'fills'):
            for g, n, i in self.copper[layer].get(kind, ()):
                if n == net:
                    continue
                if n and any(f in str(n) for f in ()):   # 预留
                    pass
                if g.intersects(win):
                    out.append((g, n, i, kind))
        return out


def islands_of(board, net):
    """并查集: 同层相接触(<=0.012mm)的图元归为一个孤岛。"""
    objs = {}
    for g, n, i in board.copper[1]['lines'] + board.copper[2]['lines'] + \
            board.copper[15]['lines'] + board.copper[16]['lines']:
        if n == net:
            objs.setdefault('L:' + i, {'geom': g, 'layers': set()})
    for l in LAYERS:
        for g, n, i in board.copper[l]['lines']:
            if n == net:
                objs.setdefault('L:' + i, {'geom': g, 'layers': set()})['layers'].add(l)
        for g, n, i in board.copper[l]['pads']:
            if n == net:
                objs.setdefault('P:' + i, {'geom': g, 'layers': set()})['layers'].add(l)
        for g, n, i in board.copper[l]['vias']:
            if n == net:
                objs.setdefault('V:' + i, {'geom': g, 'layers': set()})['layers'].add(l)
    keys = list(objs)
    parent = {k: k for k in keys}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    cells = collections.defaultdict(list)
    for k in keys:
        b = objs[k]['geom'].bounds
        for cx in range(int(b[0] // 2), int(b[2] // 2) + 1):
            for cy in range(int(b[1] // 2), int(b[3] // 2) + 1):
                cells[(cx, cy)].append(k)
    for ks in cells.values():
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = ks[i], ks[j]
                if not (objs[a]['layers'] & objs[b]['layers']):
                    continue
                if objs[a]['geom'].distance(objs[b]['geom']) <= 0.012:
                    union(a, b)
    comp = collections.defaultdict(list)
    for k in keys:
        comp[find(k)].append(k)
    return objs, list(comp.values())


# --------------------------------------------------------------------------
# 栅格布线
# --------------------------------------------------------------------------
_DMAP_CACHE = {}


def _dmap(board, net, layer, win, res):
    key = (layer, net, round(win.bounds[0], 3), round(win.bounds[1], 3),
           round(win.bounds[2], 3), round(win.bounds[3], 3), res)
    if key in _DMAP_CACHE:
        return _DMAP_CACHE[key]
    obs = [g for g, n, i, k in board.obstacles(layer, net, win.buffer(0.4))]
    u = unary_union(obs) if obs else None
    if u is not None and not u.is_valid:
        u = u.buffer(0)
    nx = int((win.bounds[2] - win.bounds[0]) / res) + 1
    ny = int((win.bounds[3] - win.bounds[1]) / res) + 1
    if nx * ny > 3_000_000:
        return None
    xs = win.bounds[0] + np.arange(nx) * res
    ys = win.bounds[1] + np.arange(ny) * res
    X, Y = np.meshgrid(xs, ys)
    mask = shapely.contains_xy(u, X, Y) if u is not None else np.zeros_like(X, dtype=bool)
    D = ndimage.distance_transform_edt(~mask, sampling=res)
    val = (D, win, nx, ny)
    _DMAP_CACHE[key] = val
    return val


def plan_path(board, net, layer, width, src_poly, dst_poly, clear=CLEAR,
              res=0.02, margin=1.2, mode='all', tol=0.0005, win=None, zone=None):
    """在 layer 上找一条 max-min 距离 >= clear+width/2 的路径。返回 (path, pinch) 或 (None, pinch)"""
    if win is None:
        b1, b2 = src_poly.bounds, dst_poly.bounds
        M = margin
        win = box(min(b1[0], b2[0]) - M, min(b1[1], b2[1]) - M,
                  max(b1[2], b2[2]) + M, max(b1[3], b2[3]) + M)
    dm = _dmap(board, net, layer, win, res)
    if dm is None:
        return None, 0.0
    D, win, nx, ny = dm

    def cell(p):
        return (max(0, min(nx - 1, int(round((p[0] - win.bounds[0]) / res)))),
                max(0, min(ny - 1, int(round((p[1] - win.bounds[1]) / res)))))
    sp = cell((src_poly.representative_point().x, src_poly.representative_point().y))
    gp = cell((dst_poly.representative_point().x, dst_poly.representative_point().y))
    # 栅格化误差: EDT 给的是到最近的'被标记格心'的距离, 对斜向铜最多高估 ~res*0.71,
    # 实测 0.02mm 栅格高估 0.0144mm -> 必须把这段补进阈值, 否则 DRC 会判净距不足。
    base = clear + width / 2.0 + res * 0.75 - tol
    need_map = np.full(D.shape, base, dtype=np.float64)
    if zone:
        # zone = ((x,y), 放宽后的净距, 半径mm): 逃逸区(封装焊盘附近)允许更小净距
        zp, zc, zr = zone
        xi = int(round((zp[0] - win.bounds[0]) / res))
        yj = int(round((zp[1] - win.bounds[1]) / res))
        rc = zr / res
        yy, xx = np.ogrid[0:D.shape[0], 0:D.shape[1]]
        m = ((xx - xi) ** 2 + (yy - yj) ** 2) <= rc * rc
        need_map[m] = zc + width / 2.0 + res * 0.4 - tol
    ok = D >= need_map
    # 诊断用 pinch = 起终点连通的最大统一阈值
    pinch = 0.0
    lo, hi = 0.0, float(D.max())
    for _ in range(18):
        mid = (lo + hi) / 2.0
        lbl, _n = ndimage.label(D >= mid)
        if lbl[sp[1], sp[0]] and lbl[sp[1], sp[0]] == lbl[gp[1], gp[0]]:
            pinch, lo = mid, mid
        else:
            hi = mid
    if not (ok[sp[1], sp[0]] and ok[gp[1], gp[0]]):
        return None, round(pinch, 4)
    ok[sp[1], sp[0]] = ok[gp[1], gp[0]] = True
    # BFS 8 邻域
    from collections import deque
    prev = np.full((ny, nx), -1, dtype=np.int32)
    qd = deque([sp])
    seen = np.zeros((ny, nx), dtype=bool)
    seen[sp[1], sp[0]] = True
    nb = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
    while qd:
        x, y = qd.popleft()
        if (x, y) == gp:
            break
        for dx, dy in nb:
            ax, ay = x + dx, y + dy
            if 0 <= ax < nx and 0 <= ay < ny and ok[ay, ax] and not seen[ay, ax]:
                seen[ay, ax] = True
                prev[ay, ax] = x * 100000 + y
                qd.append((ax, ay))
    if not seen[gp[1], gp[0]]:
        return None, round(pinch, 4)
    pts = []
    cur = gp
    while cur != sp:
        pts.append((win.bounds[0] + cur[0] * res, win.bounds[1] + cur[1] * res))
        v = prev[cur[1], cur[0]]
        cur = (v // 100000, v % 100000)
    pts.append((win.bounds[0] + sp[0] * res, win.bounds[1] + sp[1] * res))
    pts.reverse()
    # 逐步放松简化容差: RDP 会切角, 切到障碍里就换更保守的简化
    for tol_try in (res * 1.2, res * 0.6, res * 0.25, 0.0):
        simple = LineString(pts).simplify(tol_try).coords[:] if tol_try > 0 else list(pts)
        good = True
        for k in range(len(simple) - 1):
            a, b = simple[k], simple[k + 1]
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            n = max(2, int(L / (res / 2)) + 1)
            for t in range(n + 1):
                px = a[0] + (b[0] - a[0]) * t / n
                py = a[1] + (b[1] - a[1]) * t / n
                ci, cj = cell((px, py))
                if D[cj, ci] < need_map[cj, ci] - 1e-6:
                    good = False
                    break
            if not good:
                break
        if good:
            return [(round(p[0], 4), round(p[1], 4)) for p in simple], round(pinch, 4)
    return None, round(pinch, 4)


def clearances_of_path(board, net, path, width, layers):
    """复算路径到异网铜的最小净距(margin)"""
    best = (9e9, None)
    line = LineString(path).buffer(width / 2.0, cap_style=1)
    for layer in layers:
        for g, n, i, k in board.obstacles(layer, net, line.buffer(0.4).bounds and
                                          box(*line.buffer(0.4).bounds)):
            d = g.distance(line)
            if d < best[0]:
                best = (d, '%s %s(%s)' % (k, i, n))
    return best


# --------------------------------------------------------------------------
def action_targets(board, cmd_path, nets=None):
    """从 drc_commands 的 manual_connect 里取出每个网络需要缝合的孤岛信息。"""
    cmd = json.load(open(cmd_path, encoding='utf-8'))
    flagged = collections.defaultdict(set)
    for a in cmd['actions']:
        if a['action'] == 'manual_connect':
            net = a['obj1']['suffix'].split('):')[0].lstrip('(')
            if nets and net not in nets:
                continue
            flagged[net].add(a['obj1']['id'])
    return flagged


def plan_all(board, flagged, allow_narrow=False, quiet=False, max_cases=99, margin=2.5, res=0.02, clear=CLEAR):
    plans = []
    for net in sorted(flagged):
        objs, comps = islands_of(board, net)
        comps = sorted(comps, key=lambda ks: -len(ks))
        if len(comps) < 2:
            if not quiet:
                print('%-10s 已连通, 跳过' % net)
            continue
        if net in FORBIDDEN:
            continue
        w0 = board.mode_width(net)
        width_try = [w0]
        if allow_narrow:
            for cand in (0.24, 0.22, 0.20, 0.18, 0.16, 0.15, 0.13, 0.12, 0.10):
                if cand < w0 - 1e-4 and cand not in width_try:
                    width_try.append(cand)
        main = comps[0]
        done = 0
        for oi, isl in enumerate(comps[1:], 1):
            if done >= max_cases:
                break
            got = None
            best_pinch = 0.0
            for layer in (1, 2, 15, 16):
                A = [objs[k]['geom'] for k in main if layer in objs[k]['layers']]
                B = [objs[k]['geom'] for k in isl if layer in objs[k]['layers']]
                if not A or not B:
                    continue
                ua, ub = unary_union(A), unary_union(B)
                # 主岛可能横跨全板 -> 用"最近接近点"附近的小窗口规划, 避免窗口过大
                try:
                    from shapely.ops import nearest_points
                    np1, np2 = nearest_points(ua, ub)
                    cx, cy = (np1.x + np2.x) / 2.0, (np1.y + np2.y) / 2.0
                    RR = max(4.0, math.hypot(np1.x - np2.x, np1.y - np2.y) / 2.0 + 2.0)
                    lwin = box(cx - RR, cy - RR, cx + RR, cy + RR)
                    ua_l = ua.intersection(lwin)
                    ub_l = ub.intersection(lwin)
                    if ua_l.is_empty or ub_l.is_empty:
                        continue
                    ua, ub = ua_l, ub_l
                except Exception:
                    lwin = None
                for w in width_try:
                    t0 = time.time()
                    path, pinch = plan_path(board, net, layer, w, ua, ub, margin=margin, res=res, clear=clear, win=lwin)
                    best_pinch = max(best_pinch, pinch)
                    if path:
                        got = {'net': net, 'layer': layer, 'width': w, 'path': path,
                               'pinch': pinch, 'secs': round(time.time() - t0, 1),
                               'need': round(CLEAR + w / 2, 4),
                               'tier': 'strict-6mil' if w >= w0 else 'narrow-6mil',
                               'src': 'island%d' % oi}
                        break
                if got:
                    break
            if got:
                cl, who = clearances_of_path(board, net, got['path'], got['width'], (got['layer'],))
                got['min_clearance'] = round(cl, 4)
                got['nearest_foreign'] = who
                # 硬门槛: 用真实几何复算, 必须 >= 6mil + 0.2mil 余量, 否则宁可不做
                if cl < CLEAR + 0.001:
                    if not quiet:
                        print('%-10s 孤岛%d -> 弃用(实测净距 %.4fmm < %.4f): 最近=%s' % (
                            net, oi, cl, CLEAR + 0.001, who))
                    continue
                plans.append(got)
                done += 1
                if not quiet:
                    print('%-10s 孤岛%d -> layer %-2d 宽%.3f 长%.2fmm pinch=%.3f 净距=%.3f [%s] %ss' % (
                        net, oi, got['layer'], got['width'],
                        sum(math.hypot(got['path'][k + 1][0] - got['path'][k][0],
                                       got['path'][k + 1][1] - got['path'][k][1])
                            for k in range(len(got['path']) - 1)),
                        got['pinch'], got['min_clearance'], got['tier'], got['secs']))
            elif not quiet:
                print('%-10s 孤岛%d -> 无可行路径 (最佳pinch=%.4f, 需求=%.4f, 线宽候选 %s)' % (
                    net, oi, best_pinch, CLEAR + width_try[0] / 2 + 0.015, width_try))
    return plans


def apply_plans(board, plans, log=print):
    """落铜: 逐条 create 线段(折线拆段) + 过孔。支持单层(plan['path'])
    与多层(plan['path_top_1'/'path_inner'/'path_top_2'] + via1/via2)两种结构。"""
    created = {'lines': [], 'vias': []}

    def mkline(net, layer, a, b, w):
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-4:
            return
        js = CREATE_LINE_JS.replace('__SEG__', json.dumps({
            'net': net, 'layer': layer, 'x1': a[0], 'y1': a[1], 'x2': b[0], 'y2': b[1], 'w': w}))
        r = q(js)
        if isinstance(r, dict) and r.get('ok'):
            created['lines'].append(r.get('id'))
            log('  + line %s (%s L%d) %.3f,%.3f -> %.3f,%.3f w=%.3f' % (
                r.get('id'), net, layer, a[0], a[1], b[0], b[1], w))
        else:
            log('  !! 建线失败: %r' % (r,))

    def mkvia(net, v):
        js = CREATE_VIA_JS.replace('__VIA__', json.dumps({
            'net': net, 'x': v['x'], 'y': v['y'], 'hole': v['hole'], 'dia': v['dia']}))
        r = q(js)
        if isinstance(r, dict) and r.get('ok'):
            created['vias'].append(r.get('id'))
            log('  + via %s (%s) %.3f,%.3f dia=%.3f hole=%.3f' % (
                r.get('id'), net, v['x'], v['y'], v['dia'], v['hole']))
        else:
            log('  !! 建过孔失败: %r' % (r,))

    for p in plans:
        if 'path_inner' in p:      # 多层: 顶层两段 + 内层一段 + 两个过孔 (每段用各自线宽!)
            for leg, lay, wkey in (('path_top_1', 1, 'width_stub1'), ('path_inner', p['layer'], 'width'),
                                   ('path_top_2', 1, 'width_stub2')):
                pts = p.get(leg) or []
                wleg = p.get(wkey, p['width'])
                for k in range(len(pts) - 1):
                    mkline(p['net'], lay, pts[k], pts[k + 1], wleg)
            mkvia(p['net'], p['via1'])
            mkvia(p['net'], p['via2'])
            continue
        for k in range(len(p['path']) - 1):
            a, b = p['path'][k], p['path'][k + 1]
            mkline(p['net'], p['layer'], a, b, p['width'])
    return created


MATCH_JS = r'''
const segs = __SEGS__;
const L = await eda.pcb_PrimitiveLine.getAll();
const out = [];
const norm = function(v){ return Math.round(v*10000)/10000; };
L.forEach(function(l){
  const net = String(l.getState_Net()), layer = l.getState_Layer();
  const x1=norm(l.getState_StartX()*0.0254), y1=norm(l.getState_StartY()*0.0254);
  const x2=norm(l.getState_EndX()*0.0254), y2=norm(l.getState_EndY()*0.0254);
  segs.forEach(function(s, i){
    if (s.net!==net || Math.abs(s.layer-layer)>0.001) return;
    const fwd = Math.abs(s.x1-x1)<0.01 && Math.abs(s.y1-y1)<0.01 && Math.abs(s.x2-x2)<0.01 && Math.abs(s.y2-y2)<0.01;
    const rev = Math.abs(s.x1-x2)<0.01 && Math.abs(s.y1-y2)<0.01 && Math.abs(s.x2-x1)<0.01 && Math.abs(s.y2-y1)<0.01;
    if (fwd || rev) out.push({ i:i, id:String(l.getState_PrimitiveId()) });
  });
});
return JSON.stringify(out);
'''


def match_created_ids(plans, log=print):
    segs = []
    for p in plans:
        for k in range(len(p['path'])-1):
            a, b = p['path'][k], p['path'][k+1]
            if math.hypot(b[0]-a[0], b[1]-a[1]) < 1e-4:
                continue
            segs.append({'net': p['net'], 'layer': p['layer'],
                         'x1': a[0], 'y1': a[1], 'x2': b[0], 'y2': b[1]})
    r = q(MATCH_JS.replace('__SEGS__', json.dumps(segs)))
    return r


def rebuild_pours(log=print):
    r = q(REBUILD_POURS_JS)
    log('重铺铺铜: %s' % json.dumps(r, ensure_ascii=False))
    return r


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description='EasyEDA 连接缝合器')
    ap.add_argument('--plan', action='store_true', help='只规划(默认)')
    ap.add_argument('--apply', action='store_true', help='落铜')
    ap.add_argument('--nets', help='逗号分隔的网络白名单')
    ap.add_argument('--allow-narrow', action='store_true', help='允许比本网更细的补线')
    ap.add_argument('--margin', type=float, default=2.5, help='规划窗口外扩 mm (默认 2.5)')
    ap.add_argument('--clear', type=float, default=0.1524,
                    help='规划用净距 mm (默认 0.1524=6mil; 建议留 0.05 余量抗栅格化误差)')
    ap.add_argument('--rollback-nets', metavar='NETS', help='只删除这些网络由本工具创建的线段')
    ap.add_argument('--res', type=float, default=0.02, help='栅格分辨率 mm (默认 0.02)')
    ap.add_argument('--rebuild-pours', action='store_true')
    ap.add_argument('--rollback-created', metavar='FILE', help='按记录删除本工具创建的图元')
    ap.add_argument('--cmds', default='drc_commands_after_reimport.json')
    ap.add_argument('--plans-file', metavar='JSON',
                    help='直接用已有的规划 JSON（如 _st25_multi_plans.json）落铜')
    ap.add_argument('--dump', default='_stitch_board.json')
    ap.add_argument('--out', default='stitch_plan.json', help='规划结果 JSON')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)

    if args.rollback_nets:
        want = set(args.rollback_nets.split(','))
        rec = json.load(open('stitch_created.json', encoding='utf-8'))
        plans = [p for p in rec.get('plans', []) if p['net'] in want]
        matched = match_created_ids(plans)
        ids = sorted({m['id'] for m in matched})
        r = q(DELETE_JS.replace('__IDS__', json.dumps({'lines': ids, 'vias': []})))
        print('回滚网络 %s: 删除 %d 条线 -> %s' % (','.join(sorted(want)), len(ids),
                                              json.dumps(r, ensure_ascii=False)))
        return 0
    if args.rollback_created:
        d = json.load(open(args.rollback_created, encoding='utf-8'))
        r = q(DELETE_JS.replace('__IDS__', json.dumps(d.get('created', d))))
        print('回滚: %s' % json.dumps(r, ensure_ascii=False))
        return 0
    if args.rebuild_pours:
        rebuild_pours()
        return 0

    if args.plans_file:
        plans = json.load(open(args.plans_file, encoding='utf-8'))
        print('从 %s 载入 %d 条规划' % (args.plans_file, len(plans)))
        if args.apply and plans:
            created = apply_plans(Board(dump_board(args.dump, args.quiet)), plans)
            json.dump({'created': created, 'plans': plans},
                      open('stitch_created_multi.json', 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            print('创建 %d 线 / %d 过孔 (stitch_created_multi.json)' % (
                len(created['lines']), len(created['vias'])))
            rebuild_pours()
        return 0
    board = Board(dump_board(args.dump, args.quiet))
    nets = set(args.nets.split(',')) if args.nets else None
    flagged = action_targets(board, args.cmds, nets)
    if not flagged:
        print('没有需要缝合的连接错误（或 --nets 过滤后为空）')
        return 0
    print('待缝合网络 %d 个: %s' % (len(flagged), ','.join(sorted(flagged))))
    plans = plan_all(board, flagged, args.allow_narrow, args.quiet, margin=args.margin, res=args.res, clear=args.clear)
    json.dump({'plans': plans, 'generated': time.strftime('%Y-%m-%d %H:%M:%S')},
              open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('规划 %d 条 -> %s' % (len(plans), args.out))
    if args.apply and plans:
        created = apply_plans(board, plans)
        try:
            matched = match_created_ids(plans)
            ids = [m['id'] for m in matched]
            if ids:
                created['lines'] = sorted(set(ids))
                print('已回填 %d 条线段的真实 id（用于回滚）' % len(created['lines']))
        except Exception as e:
            print('id 回填失败: %r' % (e,))
        prev = {'created': {'lines': [], 'vias': []}, 'plans': []}
        if os.path.exists('stitch_created.json'):
            try:
                prev = json.load(open('stitch_created.json', encoding='utf-8'))
            except Exception:
                pass
        merged = {'created': {'lines': sorted(set(prev.get('created', {}).get('lines', []) + created['lines'])),
                              'vias': sorted(set(prev.get('created', {}).get('vias', []) + created['vias']))},
                  'plans': prev.get('plans', []) + plans,
                  'generated': time.strftime('%Y-%m-%d %H:%M:%S')}
        json.dump(merged, open('stitch_created.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('创建 %d 线 / %d 过孔 (记录 stitch_created.json)' % (
            len(created['lines']), len(created['vias'])))
        rebuild_pours()
    return 0


if __name__ == '__main__':
    sys.exit(main())
