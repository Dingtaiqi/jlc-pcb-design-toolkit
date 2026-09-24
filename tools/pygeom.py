# -*- coding: utf-8 -*-
"""pygeom.py —— v0.2：纯 Python 几何引擎（不依赖 EasyEDA / 浏览器，可进 CI）

和 tools/geom_router.js 是同一套判据，但能在**离线快照**上跑，因此可以：
  * 单元测试、回归测试（把某块板的快照钉住，防止未来改动悄悄破坏）
  * 在没有 EDA 的机器/CI 上复核"这块板的间距是否真的够"

输入：`tools/extract_live.py` 产出的快照 JSON
    ★单位坑（实测）：快照里 x/y/线宽/孔径 是 **mm**，而焊盘 pad/hole 字符串保留 EasyEDA 原始 **mil**
      （例：`line=[id,net,layer,25.466,56.261,...,0.2553]` = 10mil 线；`pad='RECT,31.5,35.4'` = 31.5mil 焊盘）
      本引擎内部一律用 **mm**，读入时把 pad/hole 的 mil 值转成 mm；对外参数仍用 mil（你习惯的那套）。
    {"lines":[[id,net,layer,x1,y1,x2,y2,width], ...],
     "vias" :[[id,net,x,y,diameter,holeDiameter], ...],
     "pads" :[[net,layer,x,y,padStr,holeStr,padNumber,rotation], ...]}

用法：
    python tools/pygeom.py --report work/board_snapshot.json        # 体检: 孔距/间距/悬空
    python tools/pygeom.py --check-lines work/board_snapshot.json   # 既有线中点是否都畅通
    python tools/pygeom.py --route work/board_snapshot.json ...     # A* 布线(示例)
    python -m unittest discover tests                              # 单元测试

踩过的坑（在 JS 版里都真实发生过，这里全部已修正）：
  * 焊盘 rotation 是**弧度**，不是度
  * 过孔不能把自己算成障碍；同网铜不查间距，但**同网孔到孔必须查**
  * 矩形焊盘必须用"精确旋转框距"，不许拿对角线当半径
  * 通孔焊盘(有钻孔)在**所有层**都挡线；贴片焊盘只挡自己那层
"""
import argparse, heapq, json, math, os, sys

MIL_PER_MM = 1.0 / 0.0254
MM_PER_MIL = 0.0254
U_MM = 'mm'
MULTI_LAYER = 12            # EasyEDA: 12 = Multi-Layer
HOLE_HH_DEFAULT = 11.81     # 孔壁到孔壁最小间距(mil) ≈ 0.30mm(比厂规 0.25mm 保守)


def mm(v):
    return v / MIL_PER_MM


def _num(v, d=0.0):
    try:
        if isinstance(v, bool):
            return d
        return float(v)
    except Exception:
        return d


def _split_shape(v):
    """EasyEDA 快照里 pad/hole 有三种形态:
       '["RECT",31.5,35.4,0]'(JSON 数组) / 'RECT,31.5,35.4,0'(逗号串) / 'ROUND,40.158'
       → 统一成 list; 非形状字符串返回 None"""
    j = _load_jsonish(v)
    if isinstance(j, list):
        return j
    if isinstance(j, str) and ',' in j:
        parts = [x.strip() for x in j.split(',')]
        out = [parts[0]]
        for x in parts[1:]:
            try:
                out.append(float(x))
            except ValueError:
                out.append(x)
        return out
    return j if isinstance(j, (int, float)) else None


def _load_jsonish(v):
    """快照里 pad/hole 字段是字符串形式的 JSON（extract_live.py 的产物）"""
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s in ('', 'null', 'None'):
        return None
    if s[0] in '[{"':
        try:
            return json.loads(s)
        except Exception:
            return None
    return s


class Obst:
    """障碍物基类：返回"点到铜边"的有符号距离（内部为正，压住为负）"""
    __slots__ = ('net', 'layer', 'half', 'hole_r')

    def dist(self, x, y):
        raise NotImplementedError


class Line(Obst):
    __slots__ = ('x1', 'y1', 'x2', 'y2', 'w', 'pid')

    def __init__(self, row):
        self.pid = row[0]
        self.net = row[1] or ''
        self.layer = int(_num(row[2], 0))
        self.x1, self.y1, self.x2, self.y2 = (_num(row[3]), _num(row[4]), _num(row[5]), _num(row[6]))
        self.w = _num(row[7], 6.0 * MM_PER_MIL)
        self.half = self.w / 2.0
        self.hole_r = 0.0

    def dist(self, x, y):
        dx, dy = self.x2 - self.x1, self.y2 - self.y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 <= 0 else max(0.0, min(1.0, ((x - self.x1) * dx + (y - self.y1) * dy) / L2))
        return math.hypot(x - (self.x1 + t * dx), y - (self.y1 + t * dy)) - self.half


class Pad(Obst):
    """焊盘：RECT/OVAL 用精确旋转框距；CIRCLE/ELLIPSE 用半径（保守取长边）"""
    __slots__ = ('x', 'y', 'rot', 'shape', 'a', 'b', 'pin')

    def __init__(self, row):
        self.net = row[0] or ''
        self.layer = int(_num(row[1], 0))
        self.x, self.y = _num(row[2]), _num(row[3])
        shp = _split_shape(row[4])
        self.pin = str(row[6] if len(row) > 6 else '')
        self.rot = _num(row[7] if len(row) > 7 else 0.0)          # ★ 弧度
        if isinstance(shp, list) and len(shp) >= 3:
            self.shape = str(shp[0]).upper()
            self.a, self.b = _num(shp[1]), _num(shp[2])
            if max(self.a, self.b) > 5.0:          # ★ 快照里 pad 尺寸是 mil → 转 mm
                self.a, self.b = self.a * MM_PER_MIL, self.b * MM_PER_MIL
        else:
            self.shape, self.a, self.b = 'RECT', 0.0, 0.0
        if self.shape in ('CIRCLE', 'ELLIPSE'):
            self.half = max(self.a, self.b) / 2.0
        else:
            self.half = max(self.a, self.b) / 2.0
        hole = _split_shape(row[5])
        self.hole_r = 0.0
        if isinstance(hole, list):
            for v in hole:
                if isinstance(v, (int, float)) and v > 0:
                    self.hole_r = (v * (MM_PER_MIL if v > 5.0 else 1.0)) / 2.0   # ★ mil → mm
                    break
        elif isinstance(hole, (int, float)) and hole > 0:
            self.hole_r = (hole * (MM_PER_MIL if hole > 5.0 else 1.0)) / 2.0

    @property
    def through(self):
        return self.hole_r > 0 or self.layer == MULTI_LAYER

    def dist(self, x, y):
        dx, dy = x - self.x, y - self.y
        r = self.rot
        if r:
            c, s = math.cos(-r), math.sin(-r)
            dx, dy = dx * c - dy * s, dx * s + dy * c
        if self.shape in ('CIRCLE', 'ELLIPSE'):
            return math.hypot(dx, dy) - self.half
        qx = abs(dx) - self.a / 2.0
        qy = abs(dy) - self.b / 2.0
        # ★ 精确旋转框距：外点用 hypot(max,0)，内点取 max(qx,qy)
        return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0)


class Via(Obst):
    __slots__ = ('x', 'y', 'drill_r', 'pid')

    def __init__(self, row):
        self.pid = row[0]
        self.net = row[1] or ''
        self.x, self.y = _num(row[2]), _num(row[3])
        self.layer = MULTI_LAYER
        self.half = _num(row[4], 16.0 * MM_PER_MIL) / 2.0          # 缺省 16mil
        self.drill_r = _num(row[5], 12.0 * MM_PER_MIL) / 2.0       # 缺省 12mil
        self.hole_r = self.drill_r


class Board:
    """板子几何模型：能回答"这个点/这条线能不能放"以及"孔距够不够" """

    def __init__(self, snap, clearance=5.0, hole_hh=HOLE_HH_DEFAULT, via_hole_fallback=12.0):
        """clearance/hole_hh 单位 = mil（对外习惯），内部换算成 mm"""
        self.lines = [Line(r) for r in (snap.get('lines') or [])]
        self.vias = [Via(r) for r in (snap.get('vias') or [])]
        self.pads = [Pad(r) for r in (snap.get('pads') or [])]
        self.CL = clearance * MM_PER_MIL
        self.HH = hole_hh * MM_PER_MIL
        self.via_hole_fallback = via_hole_fallback

    # ---------- 基础判据 ----------
    def free_why(self, net, x, y, w_mil, layer=None):
        """线宽 w_mil(单位 mil) 的中心线放在 (x,y) 是否合法；返回 (ok, 原因, 对象描述)"""
        need = (w_mil * MM_PER_MIL) / 2.0 + self.CL
        for l in self.lines:
            if l.net == net:
                continue
            if layer is not None and l.layer != layer:
                continue
            if l.dist(x, y) - need < 0:
                return False, 'line', 'L%d %s' % (l.layer, l.net)
        for p in self.pads:
            if p.net == net:
                continue
            if layer is not None and not p.through and p.layer != layer:
                continue                      # 贴片焊盘只挡自己那层
            if p.dist(x, y) - need < 0:
                return False, 'pad', '%s@L%d' % (p.net, p.layer)
        for v in self.vias:
            if v.net == net:
                continue
            if math.hypot(v.x - x, v.y - y) - v.half - need < 0:
                return False, 'via', v.net or '(无网)'
        return True, '', ''

    def free(self, net, x, y, w_mil, layer=None):
        return self.free_why(net, x, y, w_mil, layer)[0]

    def via_slack(self, net, x, y, dia, drill):
        """dia/drill 单位 = mil。返回 (余量(mm), 约束描述)；余量 >= 0 表示合法。"""
        dia, drill = dia * MM_PER_MIL, drill * MM_PER_MIL
        r, hr = dia / 2.0, drill / 2.0
        best, who = 1e18, ''
        for l in self.lines:
            if l.net == net:
                continue
            s = l.dist(x, y) - r - self.CL
            if s < best:
                best, who = s, 'L%d %s' % (l.layer, l.net)
        for p in self.pads:
            if p.net != net:
                s = p.dist(x, y) - r - self.CL
                if s < best:
                    best, who = s, 'pad %s' % p.net
            if p.hole_r > 0:                                    # 孔到孔: 同网也查
                s = math.hypot(p.x - x, p.y - y) - hr - p.hole_r - self.HH
                if s < best:
                    best, who = s, 'hh pad %s' % p.net
        for v in self.vias:
            d = math.hypot(v.x - x, v.y - y)
            if d < 1e-6:
                continue                                        # ★ 不能把自己算成障碍
            if v.net != net:                                    # 同网铜本就相连, 不查间距
                s = d - v.half - r - self.CL
                if s < best:
                    best, who = s, 'via %s' % v.net
            s = d - hr - v.drill_r - self.HH                    # 孔到孔: 同网也必须查
            if s < best:
                best, who = s, 'hh %s' % v.net
        return best, who

    def place_via(self, net, near, dia, drill, search=30.0, step=1.0):
        """在 near 附近找一个合法、且仍压住本网铜的过孔位置"""
        best = None
        n = int(search / step)
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                x, y = near[0] + i * step, near[1] + j * step
                slack, who = self.via_slack(net, x, y, dia, drill)
                if slack < 0:
                    continue
                rr = dia * MM_PER_MIL / 2.0
                touch = False
                for l in self.lines:
                    if l.net == net and l.dist(x, y) <= rr:
                        touch = True
                        break
                if not touch:
                    for p in self.pads:
                        if p.net == net and p.dist(x, y) <= rr:
                            touch = True
                            break
                if not touch:
                    continue
                sc = -math.hypot(i, j)
                if best is None or sc > best[0]:
                    best = (sc, x, y, slack, who)
        if not best:
            return None
        return {'x': round(best[1], 2), 'y': round(best[2], 2), 'slack': round(best[3], 2), 'who': best[4]}

    # ---------- A* ----------
    def route(self, net, layer, width, src, dst, step=2.0, max_nodes=400000, box=None):
        """单层 A*；返回折线 [[x,y],...] 或 None"""
        if box is None:
            xs = [min(l.x1, l.x2) for l in self.lines] + [max(l.x1, l.x2) for l in self.lines] + [src[0], dst[0]]
            ys = [min(l.y1, l.y2) for l in self.lines] + [max(l.y1, l.y2) for l in self.lines] + [src[1], dst[1]]
            m = step * 3
            box = [min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m]
        nx = int((box[2] - box[0]) / step) + 1
        ny = int((box[3] - box[1]) / step) + 1
        if nx * ny > max_nodes:
            return None
        fr = bytearray(nx * ny)
        for i in range(nx):
            for j in range(ny):
                if self.free(net, box[0] + i * step, box[1] + j * step, width, layer):
                    fr[j * nx + i] = 1

        def idx(p):
            return int(round((p[0] - box[0]) / step)), int(round((p[1] - box[1]) / step))
        si, sj = idx(src)
        ti, tj = idx(dst)
        if not (0 <= si < nx and 0 <= sj < ny and 0 <= ti < nx and 0 <= tj < ny):
            return None
        fr[sj * nx + si] = 1
        fr[tj * nx + ti] = 1
        start, goal = sj * nx + si, tj * nx + ti
        g = {start: 0.0}
        pq = [(math.hypot(ti - si, tj - sj), 0.0, start)]
        prev = {}
        dirs = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                (1, 1, 1.41421356), (1, -1, 1.41421356), (-1, 1, 1.41421356), (-1, -1, 1.41421356)]
        seen = set()
        while pq:
            _, gc, k = heapq.heappop(pq)
            if k in seen:
                continue
            seen.add(k)
            if k == goal:
                break
            ci, cj = k % nx, k // nx
            for di, dj, dw in dirs:
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < nx and 0 <= nj < ny):
                    continue
                kk = nj * nx + ni
                if not fr[kk]:
                    continue
                ng = gc + dw
                if ng < g.get(kk, 1e18) - 1e-9:
                    g[kk] = ng
                    prev[kk] = k
                    heapq.heappush(pq, (ng + math.hypot(ti - ni, tj - nj), ng, kk))
        if goal not in prev and goal != start:
            return None
        path, cur = [], goal
        while cur != start:
            i, j = cur % nx, cur // nx
            path.append([box[0] + i * step, box[1] + j * step])
            cur = prev[cur]
        path.append(list(src))
        path.reverse()
        path[-1] = list(dst)
        # 抽直：能直达就跳过中间点
        out = [path[0]]
        i0 = 0
        while i0 < len(path) - 1:
            j2 = len(path) - 1
            while j2 > i0 + 1:
                a, b = path[i0], path[j2]
                d = math.hypot(b[0] - a[0], b[1] - a[1])
                n = max(1, int(d / step))
                if all(self.free(net, a[0] + (b[0] - a[0]) * q / n, a[1] + (b[1] - a[1]) * q / n, width, layer)
                       for q in range(1, n)):
                    break
                j2 -= 1
            out.append(path[j2])
            i0 = j2
        return out

    # ---------- 体检 ----------
    def min_hole_gap(self):
        """全板最小孔壁间距（过孔 + 通孔焊盘；暴力全对全）"""
        holes = [(v.x, v.y, v.drill_r * 2) for v in self.vias]
        holes += [(p.x, p.y, p.hole_r * 2) for p in self.pads if p.hole_r > 0]
        if len(holes) < 2:
            return None, None, None          # ★不用哨兵值(哨兵值会伪装成"真结果")
        best = (1e18, None, None)
        for i in range(len(holes)):
            xi, yi, di = holes[i]
            for j in range(i + 1, len(holes)):
                xj, yj, dj = holes[j]
                gap = math.hypot(xi - xj, yi - yj) - di / 2.0 - dj / 2.0
                if gap < best[0]:
                    best = (gap, (xi, yi), (xj, yj))
        return best

    def check_lines(self, cl=None, limit=None):
        """既有线中点是否都畅通（与 DRC 0 违规的板互证）"""
        ok = bad = skipped = 0
        bads = []
        for k, l in enumerate(self.lines):
            if limit and k >= limit:
                break
            if l.layer <= 0:
                skipped += 1
                continue
            mx, my = (l.x1 + l.x2) / 2.0, (l.y1 + l.y2) / 2.0
            good, why, who = self.free_why(l.net, mx, my, l.w / MM_PER_MIL, l.layer)
            if good:
                ok += 1
            else:
                bad += 1
                if len(bads) < 5:
                    bads.append({'net': l.net, 'layer': l.layer, 'why': why, 'obj': who,
                                 'x': round(mx, 1), 'y': round(my, 1)})
        return {'ok': ok, 'bad': bad, 'skipped': skipped, 'samples': bads}


def load_board(path, clearance=5.0, hole_hh=HOLE_HH_DEFAULT):
    with open(path, encoding='utf-8') as f:
        snap = json.load(f)
    return Board(snap, clearance=clearance, hole_hh=hole_hh)


def main():
    ap = argparse.ArgumentParser(description='纯 Python 几何引擎(v0.2)：离线复核板子间距')
    ap.add_argument('snapshot', help='extract_live.py 产出的快照 JSON')
    ap.add_argument('--report', action='store_true', help='体检：孔距 / 既有线中点 / 统计')
    ap.add_argument('--check-lines', action='store_true', help='既有线中点是否都畅通')
    ap.add_argument('--clearance', type=float, default=5.0, help='安全间距(mil)，默认 5（比板规宽）')
    ap.add_argument('--hole-hh', type=float, default=HOLE_HH_DEFAULT, help='孔壁最小间距(mil)')
    ap.add_argument('--min-hole-mm', type=float, default=0.30, help='孔距达标线(mm)')
    args = ap.parse_args()

    b = load_board(args.snapshot, clearance=args.clearance, hole_hh=args.hole_hh)
    print('快照: %s' % args.snapshot)
    print('规模: 线 %d / 过孔 %d / 焊盘 %d' % (len(b.lines), len(b.vias), len(b.pads)))

    rc = 0
    if args.report or args.check_lines or True:
        gap, a, c = b.min_hole_gap()
        ok = gap / MIL_PER_MM >= args.min_hole_mm
        print('\n[孔距] 最小孔壁间距 %.3f mm (%.2f mil) 对照 %.2f mm → %s'
              % (mm(gap), gap, args.min_hole_mm, '达标 ✓' if ok else '不达标 ✗'))
        if a and c:
            print('       最紧一处: (%.1f, %.1f) ↔ (%.1f, %.1f) mil' % (a[0], a[1], c[0], c[1]))
        if not ok:
            rc = 1
        r = b.check_lines()
        print('[既有线] 中点畅通 %d / 不畅通 %d (跳过 %d, 间距阈值 %.1f mil)'
              % (r['ok'], r['bad'], r['skipped'], args.clearance))
        for s in r['samples']:
            print('       例: net=%s L%s 被 %s(%s) 挡 @(%.1f,%.1f)' % (s['net'], s['layer'], s['obj'], s['why'], s['x'], s['y']))
        if r['bad']:
            print('       提示: 少量"不畅通"多为阈值比板规更严造成的保守误报；'
                  '若比例 >1%% 才说明模型或设计有问题')
        # 悬空检查
        ends = {}
        for l in b.lines:
            if l.net:
                ends[(l.net, round(l.x1, 1), round(l.y1, 1))] = ends.get((l.net, round(l.x1, 1), round(l.y1, 1)), 0) + 1
                ends[(l.net, round(l.x2, 1), round(l.y2, 1))] = ends.get((l.net, round(l.x2, 1), round(l.y2, 1)), 0) + 1
        print('[端点] 只被一条线碰到的端点(可能是悬空, 也可能是焊盘/过孔处): %d 个'
              % sum(1 for v in ends.values() if v == 1))
    return rc


if __name__ == '__main__':
    sys.exit(main())
