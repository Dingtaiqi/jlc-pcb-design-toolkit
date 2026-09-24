# -*- coding: utf-8 -*-
"""_inventory_diff.py —— 比较两份 PCB 网络清点(导入变更前 vs 后), 只读离线

用法: python tools/_inventory_diff.py <before.json> <after.json>
默认: snapshots/inventory_before.json  vs  _pcb_net_inventory.json

输出: 被删的网络(铜会消失!)、新增的网络、以及每个网络的 线/孔/焊盘 变化
"""
import io, json, os, sys

a = sys.argv[1] if len(sys.argv) > 1 else 'snapshots/inventory_before.json'
b = sys.argv[2] if len(sys.argv) > 2 else '_pcb_net_inventory.json'
for p in (a, b):
    if not os.path.exists(p):
        print('缺少文件:', p); sys.exit(1)
A = json.load(io.open(a, encoding='utf-8'))['nets']
B = json.load(io.open(b, encoding='utf-8'))['nets']

gone = sorted(set(A) - set(B))
new = sorted(set(B) - set(A))
print('网络: 前 %d -> 后 %d' % (len(A), len(B)))
print('\n★消失的网络(导入变更把它们删了, 铜一起没):', len(gone))
for n in gone:
    v = A[n]
    print('   %-16s 原有 线%4d(%.0fmm) 孔%3d 焊盘%2d' % (n, v['lines'], v['lineLenMm'], v['vias'], v['pads']))
print('\n新增的网络(需要新布线):', len(new), new[:20])

print('\n铜量发生变化的网络:')
chg = []
for n in sorted(set(A) & set(B)):
    x, y = A[n], B[n]
    if (x['lines'], x['vias'], x['pads']) != (y['lines'], y['vias'], y['pads']):
        chg.append((n, x, y))
for n, x, y in chg:
    print('   %-16s 线 %4d->%-4d  孔 %3d->%-3d  焊盘 %2d->%-2d  (%+.0fmm)'
          % (n, x['lines'], y['lines'], x['vias'], y['vias'], x['pads'], y['pads'],
             y['lineLenMm'] - x['lineLenMm']))
if not chg:
    print('   (无)')
print('\n小结: 消失 %d 网 / 新增 %d 网 / 铜量变化 %d 网' % (len(gone), len(new), len(chg)))
