import glob
DEFAULT_Q=(glob.glob(r'C:\Users\yinsh\Downloads\*核对BOM*.xlsx') or [''])[0]
# -*- coding: utf-8 -*-
import json, re, sys, os
sys.path.insert(0,'.')
from xlsx import load
Q = sys.argv[1] if len(sys.argv)>1 else globals().get("DEFAULT_Q","")
rows=load(Q)[0][1]
# 报价单行
q=[]
for r in rows[4:]:
    if not str(r[0]).strip(): continue
    try: qty=int(float(r[1]))
    except: qty=None
    q.append(dict(no=r[0],qty=qty,comment=str(r[2]),des=str(r[3]),fp=str(r[4]),val=str(r[5]),
                  lcsc=str(r[8]),m_des=str(r[11]),m_qty=str(r[17]),m_lcsc=str(r[18]),
                  src=str(r[19]),stat=str(r[20])))
# 设计BOM(网表)
d=json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'design','Net_List.enet'),encoding='utf-8'))
dev={}
for cid,c in d['components'].items():
    p=c['props']; des=p.get('Designator')
    if des: dev[des]=dict(val=p.get('Value') or p.get('Name') or '', fp=p.get('Supplier Footprint') or p.get('FootprintName') or '', dev=p.get('DeviceName') or '')
print('报价单行数: %d   设计器件数: %d'%(len(q), len(dev)))
# 位号覆盖
qdes=set()
for it in q:
    for x in re.split(r'[,\s]+', it['des']):
        x=x.strip()
        if x: qdes.add(x)
print('报价单覆盖位号: %d 个'%len(qdes))
missing=sorted(set(dev)-qdes)
extra=sorted(qdes-set(dev))
print('★ 报价单漏掉的位号(%d): %s'%(len(missing), ','.join(missing) if missing else '无'))
print('★ 报价单多出的位号(%d): %s'%(len(extra), ','.join(extra) if extra else '无'))
# 数量一致性
print('\n--- 数量核对(报价单数量 vs 位号个数 vs 设计器件数) ---')
bad=0
for it in q:
    names=[x.strip() for x in re.split(r'[,\s]+', it['des']) if x.strip()]
    n=len(names)
    exp=sum(1 for x in names if x in dev)
    if it['qty']!=n or n!=exp:
        bad+=1
        print('  ! No.%s %s: 数量=%s, 位号数=%d, 设计命中=%d'%(it['no'],it['comment'][:14],it['qty'],n,exp))
print('  数量异常行数: %d'%bad)
# 值/封装抽查
print('\n--- 值/封装与设计不一致的行 ---')
mm=0
for it in q:
    names=[x.strip() for x in re.split(r'[,\s]+', it['des']) if x.strip()]
    for x in names:
        if x in dev:
            dv=str(dev[x]['val']).strip(); df=str(dev[x]['fp']).strip()
            if dv and dv!=it['val'].strip():
                mm+=1; print('  ! %s: 设计值=%s  报价单值=%s'%(x,dv,it['val'])); break
print('  值不一致行数: %d'%mm)
# 缺 LCSC 码/未匹配
print('\n--- 匹配异常 ---')
for it in q:
    if '已匹配' not in it['stat'] or not it['m_lcsc'].strip() or it['m_lcsc']=='None':
        print('  ! No.%s %s  位号=%s  状态=%s 立创码=%s'%(it['no'],it['comment'][:16],it['des'][:24],it['stat'],it['m_lcsc']))
print('\n--- 汇总 ---')
print('  总贴片点数(设计 166 器件): %d'%len(dev))
print('  报价单数量合计: %s'%sum(it['qty'] for it in q if it['qty']))
print('  物料来源分布: %s'%({s:sum(1 for it in q if it['src']==s) for s in set(it['src'] for it in q)}))
