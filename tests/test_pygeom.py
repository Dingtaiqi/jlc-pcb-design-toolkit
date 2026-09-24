# -*- coding: utf-8 -*-
"""test_pygeom.py —— v0.2 纯 Python 几何引擎单元测试（全部用 mm 建模，阈值/孔径按 mil 传入）

每条用例都对应一个**真实踩过的坑**：
  * 焊盘 rotation 是弧度（按度数处理会把阻挡区转反）
  * 过孔不能把自己算成障碍（曾给出 -21mil 假违规）
  * 同网铜不查间距，但同网孔到孔必须查
  * 通孔焊盘在所有层都挡线；贴片焊盘只挡自己那层
  * 矩形焊盘必须用精确旋转框距
  * pad/hole 在快照里可能是 'RECT,31.5,35.4,0' 这种逗号串（mil），要能解析并换算
"""
import json, math, os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import pygeom  # noqa: E402

MM = 0.0254          # 1 mil = 0.0254 mm


def pad(net, layer, x, y, shape, hole=None, rot=0.0, pin='1'):
    return [net, layer, x, y, shape, hole or 'null', pin, rot]


def via(pid, net, x, y, dia_mm=0.4064, drill_mm=0.3048):
    return [pid, net, x, y, dia_mm, drill_mm]


def line(pid, net, layer, x1, y1, x2, y2, w_mm=0.254):
    return [pid, net, layer, x1, y1, x2, y2, w_mm]


def board(lines=(), vias=(), pads=(), cl_mil=5.0, hh_mil=11.81):
    return pygeom.Board({'lines': list(lines), 'vias': list(vias), 'pads': list(pads)},
                        clearance=cl_mil, hole_hh=hh_mil)


class TestGeometry(unittest.TestCase):

    def test_rect_rotated_90_uses_radians(self):
        """★ 旋转 90°：0.5x1.0 的矩形转成 1.0 宽 x 0.5 高（弧度，不是度）"""
        p = pygeom.Pad(pad('N', 1, 0.0, 0.0, 'RECT,0.5,1.0,0', rot=math.pi / 2))
        self.assertAlmostEqual(p.dist(0.6, 0.0), 0.1, places=6)    # x 向半宽 0.5
        self.assertAlmostEqual(p.dist(0.0, 0.6), 0.35, places=6)   # y 向半宽 0.25
        # 误按"度"处理（rot 再乘 180/π）会得到另一种结果
        p2 = pygeom.Pad(pad('N', 1, 0.0, 0.0, 'RECT,0.5,1.0,0', rot=math.pi / 2 * 180 / math.pi))
        self.assertNotAlmostEqual(p2.dist(0.6, 0.0), 0.1, places=3)

    def test_rect_inside_edge_corner(self):
        p = pygeom.Pad(pad('N', 1, 0.0, 0.0, 'RECT,0.5,0.5,0'))
        self.assertAlmostEqual(p.dist(0.0, 0.0), -0.25, places=6)
        self.assertAlmostEqual(p.dist(0.25, 0.0), 0.0, places=6)
        self.assertAlmostEqual(p.dist(0.325, 0.35), 0.125, places=6)   # 0.075/0.1 → 0.125

    def test_circle_pad_and_comma_string(self):
        p = pygeom.Pad(pad('N', 1, 0.0, 0.0, 'CIRCLE,1.0,1.0'))
        self.assertAlmostEqual(p.dist(0.625, 0.0), 0.125, places=6)
        # 快照里是 mil 的逗号串时要能换算（40mil = 1.016mm，半宽 0.508）
        p2 = pygeom.Pad(pad('N', 1, 0.0, 0.0, 'CIRCLE,40,40'))
        self.assertAlmostEqual(p2.half, 0.508, places=6)

    def test_via_does_not_count_itself(self):
        """★ 被测的孔不能把自己算成障碍"""
        b = board(vias=[via('v1', 'N', 2.54, 2.54)])
        slack, who = b.via_slack('N', 2.54, 2.54, 16.0, 12.0)
        self.assertGreaterEqual(slack, 0.0, '自己不该判违规 (who=%s slack=%.4f)' % (who, slack))

    def test_same_net_copper_exempt_hole_enforced(self):
        """★ 同网铜豁免间距，但同网孔到孔必须查（20mil 心距 → 孔壁 -3.81mil）"""
        b = board(vias=[via('v1', 'N', 0.0, 0.0), via('v2', 'N', 20 * MM, 0.0)])
        slack, who = b.via_slack('N', 0.0, 0.0, 16.0, 12.0)
        self.assertTrue(who.startswith('hh'), '应是孔到孔最紧，实际 who=%s' % who)
        self.assertAlmostEqual(slack / MM, -3.81, places=1)          # 换算回 mil 比对

    def test_through_pad_blocks_all_layers_smd_only_own(self):
        """★ 通孔焊盘所有层都挡线；贴片焊盘只挡自己那层"""
        th = pad('P', 1, 0.0, 0.0, 'CIRCLE,1.0,1.0', hole='ROUND,20')   # 20mil 钻
        smd = pad('P', 1, 2.54, 0.0, 'RECT,1.0,1.0')
        b = board(pads=[th, smd])
        self.assertFalse(b.free('N', 0.68, 0.0, 6.0, 1), '通孔在 L1 应挡')
        self.assertFalse(b.free('N', 0.68, 0.0, 6.0, 2), '通孔在 L2 也应挡')
        self.assertFalse(b.free('N', 3.22, 0.0, 6.0, 1), '贴片在 L1 应挡')
        self.assertTrue(b.free('N', 3.22, 0.0, 6.0, 2), '贴片不该挡 L2')

    def test_same_net_line_exempt_and_layer_filter(self):
        b = board(lines=[line('l1', 'N', 1, 0.0, 0.0, 2.54, 0.0, w_mm=0.254),
                         line('l2', 'OTHER', 2, 0.0, 1.27, 2.54, 1.27, w_mm=0.254)])
        self.assertTrue(b.free('N', 1.27, 0.0, 6.0, 1), '本网线不挡自己')
        self.assertFalse(b.free('OTHER', 1.27, 0.0, 6.0, 1), '别网线要挡')
        self.assertTrue(b.free('N', 1.27, 1.27, 6.0, 1), 'L2 的线不该挡 L1')

    def test_min_hole_gap(self):
        b = board(vias=[via('v1', 'A', 0.0, 0.0), via('v2', 'B', 30 * MM, 0.0)],
                  pads=[pad('C', 1, 0.0, 30 * MM, 'CIRCLE,1.0,1.0', hole='ROUND,20')])
        gap, a, c = b.min_hole_gap()
        # 孔-孔: 0.762 - 0.1524 - 0.1524 = 0.4572；孔-通孔盘: 0.762 - 0.1524 - 0.254 = 0.3556
        self.assertAlmostEqual(gap, 0.3556, places=4)

    def test_astar_finds_path_between_walls(self):
        """A*：通道内必须能布通，且路径不压到别网铜"""
        pads = [pad('N', 1, 0.0, 0.0, 'RECT,1.0,1.0'), pad('N', 1, 5.08, 0.0, 'RECT,1.0,1.0')]
        walls = [line('w1', 'GND', 1, -1.27, -0.508, 6.35, -0.508, w_mm=0.254),
                 line('w2', 'GND', 1, -1.27, 0.508, 6.35, 0.508, w_mm=0.254)]
        b = board(lines=walls, pads=pads)
        path = b.route('N', 1, 6.0, (0.0, 0.0), (5.08, 0.0), step=0.05)
        self.assertIsNotNone(path, '通道内应能布通')
        self.assertGreaterEqual(len(path), 2)
        for k in range(len(path) - 1):
            a, c = path[k], path[k + 1]
            n = max(1, int(math.hypot(c[0] - a[0], c[1] - a[1]) / 0.05))
            for q in range(1, n):
                x = a[0] + (c[0] - a[0]) * q / n
                y = a[1] + (c[1] - a[1]) * q / n
                self.assertTrue(b.free('N', x, y, 6.0, 1), '路径经过 (%.3f,%.3f) 不该压到 GND 墙' % (x, y))

    def test_astar_returns_none_when_blocked(self):
        """被贯穿整个搜索框的墙隔断时，必须老实返回 None"""
        pads = [pad('N', 1, -5.08, 0.0, 'RECT,1.0,1.0'), pad('N', 1, 5.08, 0.0, 'RECT,1.0,1.0')]
        wall = [line('w1', 'GND', 1, 0.0, -10.0, 0.0, 10.0, w_mm=1.0)]
        b = board(lines=wall, pads=pads)
        path = b.route('N', 1, 6.0, (-5.08, 0.0), (5.08, 0.0), step=0.05,
                       box=[-6.6, -6.35, 6.6, 6.35])
        self.assertIsNone(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
