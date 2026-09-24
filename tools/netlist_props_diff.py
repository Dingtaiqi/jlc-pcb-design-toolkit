# -*- coding: utf-8 -*-
"""_netlist_props_diff.py —— 比对两份 PCB 网表的"元件属性"(离线, 不碰 EDA)

用途: 原理图改了"值"之后, 执行"导入变更"前后各取一次 PCB 网表,
      本脚本精确列出哪几个元件的值/厂商/料号/封装变了 —— 这就是要更新到 BOM 的内容。

用法: python tools/_netlist_props_diff.py <before.raw.json> <after.raw.json>
默认: _netlist_pcb.raw.json vs _netlist_pcb_after.raw.json

为什么走这条路: PCB 原生 API 里 `c.name` 返回的是显示表达式 "={Value}" 而不是值;
             而网表的 `props.Value` 才是真值, 且一次轻调用就能全拿到。
"""
import io, json, os, sys

a = sys.argv[1] if len(sys.argv) > 1 else '_netlist_pcb.raw.json'
b = sys.argv[2] if len(sys.argv) > 2 else '_netlist_pcb_after.raw.json'
for p in (a, b):
    if not os.path.exists(p):
        print('缺少文件:', p); sys.exit(1)

def props(p):
    d = json.load(io.open(p, encoding='utf-8'))
    out = {}
    for uid, c in (d.get('components') or {}).items():
        pr = c.get('props') or {}
        des = str(pr.get('Designator') or uid)
        out[des] = {k: str(v) for k, v in pr.items() if isinstance(v, (str, int, float))}
    return out

A, B = props(a), props(b)
print('元件数: 前 %d -> 后 %d' % (len(A), len(B)))
print('新增元件:', sorted(set(B) - set(A)) or '无')
print('消失元件:', sorted(set(A) - set(B)) or '无')

KEYS = ['Value', 'Name', 'Manufacturer', 'Manufacturer Part', 'Supplier',
        'Supplier Part', 'Footprint', 'FootprintName', 'Device', 'Description']
changed = []
for des in sorted(set(A) & set(B)):
    for k in KEYS:
        x, y = A[des].get(k), B[des].get(k)
        if x != y:
            changed.append({'designator': des, 'field': k, 'before': x, 'after': y})
print('\n属性变化: %d 项' % len(changed))
for c in changed:
    print('   %-6s %-16s %-24s -> %s'
          % (c['designator'], c['field'], c['before'] or '(空)', c['after'] or '(空)'))
if not changed:
    print('   (无差异 —— 说明导入变更没有改变元件属性?)')

by_des = {}
for c in changed:
    by_des.setdefault(c['designator'], []).append(c)
print('\n涉及元件: %d 个 -> %s' % (len(by_des), ', '.join(sorted(by_des)) or '无'))
io.open('_props_diff.json', 'w', encoding='utf-8').write(json.dumps(changed, ensure_ascii=False, indent=1))
print('明细已存 _props_diff.json')
print('★下一步: BOM / 坐标文件(Comment) 用新的值重出; 若涉及料号变化, 需通知 SMT 厂换料')
