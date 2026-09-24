# -*- coding: utf-8 -*-
import json, re, sys
sys.path.insert(0,'.')
from xlsx import load
Q=r"C:\Users\yinsh\Downloads\晚成鸟核对BOM_00163L_Y001_1790072793347.xlsx"
rows=load(Q)[0][1]
q=[]
for r in rows[4:]:
    if not str(r[0]).strip(): continue
    q.append(dict(no=str(r[0]),qty=r[1],cmt=str(r[2]),des=str(r[3]),fp=str(r[4]),val=str(r[5]),lcsc=str(r[8])))
d=json.load(open('deliver/Net_List.enet',encoding='utf-8'))
dev={}; net2des={}
for cid,c in d['components'].items():
    p=c['props']; des=p.get('Designator')
    if not des: continue
    dev[des]=dict(cmt=p.get('Value') or p.get('Name') or '', fp=p.get('Supplier Footprint') or p.get('FootprintName') or '', dev=p.get('DeviceName') or '')
    for pn,pi in (c.get('pinInfoMap') or {}).items():
        n=pi.get('net')
        if n: net2des.setdefault(n,[]).append(des)
qdes=set()
for it in q:
    for x in re.split(r'[,\s]+', it['des']):
        if x.strip(): qdes.add(x.strip())
missing=sorted(set(dev)-qdes, key=lambda s:(re.sub(r'\d+','',s), int(re.sub(r'\D','',s) or 0)))
print('=== 25 个未出现在报价单的位号，按封装分类 ===')
th=[]; smd=[]
for x in missing:
    fp=str(dev[x]['fp']); devn=str(dev[x]['dev'])
    isth = any(k in (fp+devn).upper() for k in ['TH','HDR','CONN','USB','SW-TH','PLUG','SOCKET','PIN','H:','DIP','AXIAL','RADIAL'])
    (th if isth else smd).append((x,fp,dev[x]['cmt']))
print('  [通孔/连接器类 — 本来就不该出现在贴片BOM] %d 个:'%len(th))
for x,fp,c in th: print('     %-6s fp=%-18s %s'%(x,fp,c))
print('  [★表面贴装类 — 疑似真漏] %d 个:'%len(smd))
for x,fp,c in smd: print('     %-6s fp=%-18s %s'%(x,fp,c))
print()
print('=== 报价单值 vs 设计(改用 Comment 列复核) ===')
bad=0
for it in q:
    for x in re.split(r'[,\s]+', it['des']):
        x=x.strip()
        if x in dev:
            dv=re.sub(r'^~','',str(dev[x]['cmt'])).strip()
            qv=it['cmt'].strip()
            if dv and qv and dv.lower()!=qv.lower() and dv.replace('.0','')!=qv.replace('.0',''):
                bad+=1; print('  ! %-6s 设计=%-16s 报价单=%-16s (fp=%s)'%(x,dv,qv,dev[x]['fp']))
            break
print('  真不一致: %d 行'%bad)
print()
print('=== 背面件(决定单面/双面贴片) ===')
import re as R
bl=json.load(open('live.json',encoding='utf-8')) if __import__('os').path.exists('live.json') else None
if bl:
    pads=bl.get('pads') if isinstance(bl,dict) else bl
    botnets={}
    for p in (pads or []):
        if isinstance(p,dict) and p.get('l')==2: botnets.setdefault(p.get('net'),0)
    botset=set()
    for n in botnets:
        for des in net2des.get(n,[]): botset.add(des)
    print('  背面焊盘的网数: %d ；涉及位号(估): %d 个'%(len(botnets), len(botset)))
    print('  ', ','.join(sorted(botset, key=lambda s:(R.sub(r'\d+','',s), int(R.sub(r'\D','',s) or 0)))))
    print('  其中出现在报价单里的(需双面贴片): %d 个'%len([x for x in botset if x in qdes]))
else:
    print('  live.json 不可用')
