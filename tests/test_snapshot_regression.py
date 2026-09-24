# -*- coding: utf-8 -*-
"""test_snapshot_regression.py —— 用**真实板子的快照**做回归（快照不存在则自动跳过）

为什么要有它：几何引擎最容易悄悄退化成"过度保守"（把好位置判死 ✗）或"过度宽松"（漏判 ✗），
两者在界面上都看不出来。用一块**已经 DRC 0 违规**的板子快照钉住两条不变量，就能立刻发现：

  1. 最小孔壁间距  >= 0.30mm（厂规 0.25mm，留余量）
  2. 既有走线的中点，在 5mil 判定下 >= 99% 畅通（不通 = 引擎模型把合法铜判成冲突）

快照从哪来：
    python pcbai.py snap && cp live.json work/board_snapshot.json
或用环境变量指定：
    PCB_SNAPSHOT=/path/to/live.json python -m unittest discover -s tests
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import pygeom  # noqa: E402

CANDIDATES = [
    os.environ.get('PCB_SNAPSHOT'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'board_snapshot.json'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'live.json'),
]
SNAP = next((p for p in CANDIDATES if p and os.path.exists(p)), None)


@unittest.skipIf(SNAP is None, '没有真实板快照（work/board_snapshot.json 或 $PCB_SNAPSHOT）')
class TestSnapshotRegression(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.b = pygeom.load_board(SNAP, clearance=5.0, hole_hh=11.81)
        print('\n  快照: %s' % SNAP)
        print('  规模: 线 %d / 过孔 %d / 焊盘 %d'
              % (len(cls.b.lines), len(cls.b.vias), len(cls.b.pads)))

    def test_min_hole_gap_meets_fab(self):
        """孔壁最小间距 >= 0.30mm（厂规 0.25mm）"""
        gap, a, c = self.b.min_hole_gap()
        print('  最小孔壁间距: %.3f mm (%.2f mil)' % (gap, gap * pygeom.MIL_PER_MM))
        self.assertGreaterEqual(gap, 0.30,
                                '孔距不足 0.30mm: 最紧一处 %s ↔ %s' % (a, c))

    def test_existing_copper_is_legal(self):
        """既有走线中点应几乎全部畅通（与"该板 DRC 0 违规"互证）"""
        r = self.b.check_lines()
        total = r['ok'] + r['bad']
        ratio = (r['ok'] / total) if total else 1.0
        print('  既有线中点畅通: %d/%d = %.2f%%' % (r['ok'], total, ratio * 100))
        for s in r['samples']:
            print('    例: net=%s L%s 被 %s(%s) 挡 @(%.1f,%.1f)'
                  % (s['net'], s['layer'], s['obj'], s['why'], s['x'], s['y']))
        self.assertGreaterEqual(ratio, 0.99,
                                '畅通率 %.2f%% 过低 → 引擎模型可能过度保守（把合法铜判成冲突）' % (ratio * 100))

    def test_through_holes_have_real_drill(self):
        """通孔焊盘必须解析出钻孔半径，否则孔到孔检查会漏"""
        th = [p for p in self.b.pads if p.hole_r > 0]
        print('  解析到带钻孔的焊盘: %d 个' % len(th))
        self.assertGreater(len(th), 0, '一个通孔焊盘都没解析出来 → hole 字段解析有问题')


if __name__ == '__main__':
    unittest.main(verbosity=2)
