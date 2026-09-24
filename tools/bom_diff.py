# -*- coding: utf-8 -*-
"""_bom_values_diff.py —— 比对两份 EasyEDA 导出 BOM, 列出所有单元格级差异(离线)

用法: python tools/_bom_values_diff.py <旧.xlsx> <新.xlsx>
      默认 snapshots/Export_BOM_before.xlsx  vs  deliver/Export_BOM.xlsx

用于: 原理图改了"值"后重出 BOM, 精确列出哪几个元件的哪个字段变了 —— 即给 SMT 厂的换料说明。
"""
import io, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import xlsx  # 工具包自带的 stdlib xlsx 解析器

a = sys.argv[1] if len(sys.argv) > 1 else 'snapshots/Export_BOM_before.xlsx'
b = sys.argv[2] if len(sys.argv) > 2 else 'deliver/Export_BOM.xlsx'
for p in (a, b):
    if not os.path.exists(p):
        print('缺少文件:', p); sys.exit(1)

def load(p):
    sheets = xlsx.load(p)
    name, rows = sheets[0]
    # 找表头行: 含 Designator 的那一行
    hi = 0
    for i, r in enumerate(rows[:10]):
        cells = [str(c) for c in r]
        if any('Designator' in c or '设计' in c or 'Comment' in c for c in cells):
            hi = i; break
    hdr = [str(c).strip() for c in rows[hi]]
    data = {}
    for r in rows[hi + 1:]:
        cells = ['' if c is None else str(c).strip() for c in r]
        if not any(cells): continue
        # 设计ator 列
        try:
            di = next(i for i, h in enumerate(hdr) if 'Designator' in h)
        except StopIteration:
            di = 0
        key = cells[di] if di < len(cells) else ''
        if not key: continue
        data[key] = dict(zip(hdr, cells + [''] * (len(hdr) - len(cells))))
    return name, hdr, data

na, ha, A = load(a)
nb, hb, B = load(b)
print('表头(旧):', ha)
print('元件行数: 旧 %d -> 新 %d' % (len(A), len(B)))
print('新增:', sorted(set(B) - set(A))[:10] or '无', ' 消失:', sorted(set(A) - set(B))[:10] or '无')

cols = [c for c in ha if c and c in hb]
diff = []
for k in sorted(set(A) & set(B)):
    for c in cols:
        x, y = A[k].get(c, ''), B[k].get(c, '')
        if x != y:
            diff.append((k, c, x, y))
print('\n单元格差异: %d 处' % len(diff))
for k, c, x, y in diff:
    print('   %-8s %-18s %-24s -> %s' % (k, c, x or '(空)', y or '(空)'))
if not diff:
    print('   (无差异)')
by_des = sorted(set(d[0] for d in diff))
print('\n涉及元件: %d 个 -> %s' % (len(by_des), ', '.join(by_des) or '无'))
io.open('_bom_diff.json', 'w', encoding='utf-8').write(
    __import__('json').dumps(diff, ensure_ascii=False, indent=1))
print('明细已存 _bom_diff.json')
