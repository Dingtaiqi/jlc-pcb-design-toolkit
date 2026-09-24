# -*- coding: utf-8 -*-
"""SES 独立几何预检：线-线 / 线-过孔（异网，同层）间距 < 阈值 的对数"""
import io, re, math, sys, collections
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
SES = sys.argv[1] if len(sys.argv) > 1 else 'tools/tourbox9.ses'
TH = 0.152
U = 0.0254/1000.0
s = io.open(SES, encoding='utf-8', errors='replace').read()
i = s.find('(network_out'); body = s[i:] if i >= 0 else s
segs, vias = [], []
pos = 0; net_re = re.compile(r"\(net\s+(\S+)")
while True:
    m = net_re.search(body, pos)
    if not m: break
    name = m.group(1); d = 0; k = m.start()
    while k < len(body):
        if body[k] == '(': d += 1
        elif body[k] == ')':
            d -= 1
            if d == 0: break
        k += 1
    blk = body[m.start():k+1]; pos = k+1
    for pm in re.finditer(r'\(path\s+(\w+)\s+(\d+)((?:\s+-?\d+)+\s*)\)', blk):
        lay = pm.group(1); w = int(pm.group(2))*U
        pts = [int(x)*U for x in pm.group(3).split()]
        xs, ys = pts[0::2], pts[1::2]
        for j in range(len(xs)-1):
            segs.append((name, lay, w, LineString([(xs[j], ys[j]), (xs[j+1], ys[j+1])])))
    for vm in re.finditer(r'\(via\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s*\)', blk):
        vias.append((name, vm.group(1), float(vm.group(2))*U, float(vm.group(3))*U))
pad = {}
for m in re.finditer(r'\(padstack\s+(\S+)', s):
    c = re.search(r'\(circle\s+TopLayer\s+([\d.]+)', s[m.end(): m.end()+800])
    if c: pad[m.group(1)] = float(c.group(1))*U
print('SES=%s  线段=%d  过孔=%d  padstack=%s' % (SES, len(segs), len(vias), {k: round(v,4) for k,v in pad.items()}))

bad_ll = 0
for lay in set(x[1] for x in segs):
    items = [x for x in segs if x[1] == lay]
    if len(items) < 2: continue
    geoms = [it[3].buffer(it[2]/2, cap_style=1) for it in items]
    tree = STRtree(geoms)
    for a in range(len(items)):
        for b in tree.query(geoms[a]):
            b = int(b)
            if b <= a or items[a][0] == items[b][0]: continue
            g = geoms[a].distance(geoms[b])
            if g < TH: bad_ll += 1
bad_lv = 0; worst = None
for vnet, pk, vx, vy in vias:
    r = pad.get(pk, 0)/2
    pv = Point(vx, vy).buffer(r)
    for (net, lay, w, ls) in segs:
        if net == vnet: continue
        g = pv.distance(ls.buffer(w/2, cap_style=1))
        if g < TH:
            bad_lv += 1
            if worst is None or g < worst[0]: worst = (g, vnet, net, lay)
print()
print('★ 线-线(异网同层)   < %.3fmm 对数 = %d' % (TH, bad_ll))
print('★ 线-过孔(异网)     < %.3fmm 对数 = %d' % (TH, bad_lv))
if worst: print('   最差 %.2f mil (过孔网=%s 线网=%s 层=%s)' % (worst[0]/0.0254, worst[1], worst[2], worst[3]))
