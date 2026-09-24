# -*- coding: utf-8 -*-
"""标准库 xlsx 解析: load(path) -> [(sheetname, [[cell,...],...]), ...]"""
import zipfile, re, os
from xml.etree import ElementTree as ET
M='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def _col(ref):
    m=re.match(r'([A-Z]+)(\d+)', ref or '')
    if not m: return 0,0
    c=0
    for ch in m.group(1): c=c*26+(ord(ch)-64)
    return c, int(m.group(2))
def fixpath(p):
    if os.path.exists(p): return p
    for enc in ('cp1252','latin1','gbk'):
        try:
            q=p.encode(enc).decode('utf-8')
            if os.path.exists(q): return q
        except Exception: pass
    return p
def load(path):
    path=fixpath(path)
    z=zipfile.ZipFile(path); names=z.namelist()
    ss=[]
    if 'xl/sharedStrings.xml' in names:
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(M+'si'):
            ss.append(''.join(t.text or '' for t in si.iter(M+'t')))
    sheets=[]
    wb=ET.fromstring(z.read('xl/workbook.xml'))
    idx=0
    for sh in wb.iter(M+'sheet'):
        idx+=1
        fn='xl/worksheets/sheet%d.xml'%idx
        if fn not in names: continue
        root=ET.fromstring(z.read(fn))
        grid={}
        maxc=0
        for row in root.iter(M+'row'):
            for c in row.iter(M+'c'):
                ref=c.get('r'); t=c.get('t')
                v=c.find(M+'v'); isv=c.find(M+'is')
                if t=='s' and v is not None and v.text is not None and v.text.isdigit(): val=ss[int(v.text)]
                elif isv is not None: val=''.join(x.text or '' for x in isv.iter(M+'t'))
                elif v is not None: val=v.text
                else: continue
                if t=='s' and isinstance(val,str): pass
                col,r=_col(ref)
                grid[(r,col)]=val; maxc=max(maxc,col)
        if not grid: sheets.append((sh.get('name'),[])); continue
        mr=max(r for r,_ in grid)
        rows=[[grid.get((r,c),'') for c in range(1,maxc+1)] for r in range(1,mr+1)]
        sheets.append((sh.get('name'),rows))
    return sheets
if __name__=='__main__':
    import sys
    for name,rows in load(sys.argv[1]):
        print('='*76); print('sheet:',name,'| rows:',len(rows),'| cols:',len(rows[0]) if rows else 0)
        n=int(sys.argv[2]) if len(sys.argv)>2 else 15
        for i,r in enumerate(rows[:n],1):
            print(i,'|',' | '.join(str(x)[:18] for x in r))
