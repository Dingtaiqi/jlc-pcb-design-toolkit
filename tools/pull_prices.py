# -*- coding: utf-8 -*-
import sys,os,re,json,csv,time,urllib.request,urllib.error
sys.path.insert(0,'.')
from xlsx import load
UA={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36',
    'Accept':'text/html,application/json,*/*','Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8'}
def get(u,cookie=None,to=20):
    h=dict(UA)
    if cookie: h['Cookie']=cookie
    r=urllib.request.urlopen(urllib.request.Request(u,headers=h),timeout=to)
    return r.read().decode('utf-8','ignore')
def ladder(txt):
    m=re.search(r'"productPriceList":\s*\[(.*?)\]',txt,re.S)
    out=[]
    if m:
        for o in re.finditer(r'\{([^{}]*)\}',m.group(1)):
            s=o.group(1)
            q=re.search(r'"ladder":\s*(\d+)',s); p=re.search(r'"(?:cnyProductPrice|productPrice|currencyPrice|usdPrice)":\s*"?([0-9.]+)"?',s)
            cny=re.search(r'"cnyProductPrice":\s*"?([0-9.]+)"?',s)
            if q and p:
                try:
                    qq=int(q.group(1)); pp=float(cny.group(1)) if cny else float(p.group(1))
                    if pp>0: out.append((qq,pp,bool(cny)))
                except: pass
    if not out:  # 单页兜底: schema.org 的 price
        m2=re.search(r'"priceCurrency":"(\w+)","price":([0-9.]+)',txt)
        if m2: out.append((1,float(m2.group(2)),m2.group(1)=='CNY'))
    d={}
    for q,p,is_cny in out: d[q]=p
    return sorted(d.items())
def fetch(code):
    for url,ck in [(f'https://www.lcsc.com/product-detail/{code}.html?currency=CNY',None),
                   (f'https://www.lcsc.com/product-detail/{code}.html','currency=CNY'),
                   (f'https://www.lcsc.com/product-detail/{code}.html',None)]:
        try:
            t=get(url,ck); L=ladder(t)
            if L: return L
        except Exception: pass
        time.sleep(0.4)
    return []
def pick(L,qty):
    p=None
    for q,pr in L:
        if qty>=q: p=pr
    return p if p is not None else (L[0][1] if L else None)
# 汇率兜底
rate=None
try:
    j=json.loads(get('https://open.er-api.com/v6/latest/USD'))
    rate=j['rates']['CNY']; print('USD->CNY 汇率: %.4f'%rate)
except Exception as e: print('汇率获取失败:',str(e)[:50])
rows=load(r"C:\Users\yinsh\Downloads\晚成鸟核对BOM_00163L_Y001_1790072793347.xlsx")[0][1]
items=[]
for r in rows[4:]:
    if not str(r[0]).strip(): continue
    code=str(r[8]).strip(); 
    if not re.match(r'^C\d+$',code): continue
    try: qty=int(float(r[1]))
    except: continue
    items.append(dict(no=str(r[0]).strip(),des=str(r[3]).strip(),cmt=str(r[2]).strip(),qty=qty,
                      code=code,src=str(r[19]).strip()))
print('读取 %d 行'%len(items))
res=[];tot=0.0;miss=[];cur=''
for it in items:
    if it['src']=='客供料':
        print('%-8s %-4d 客供料  %s'%(it['code'],it['qty'],it['cmt'][:26])); 
        res.append([it['no'],it['des'],it['cmt'],it['qty'],it['code'],'客供','','客供料']); continue
    L=fetch(it['code']); p=pick(L,it['qty'])
    if p is None: miss.append(it['code']); print('%-8s %-4d 取价失败 %s'%(it['code'],it['qty'],it['cmt'][:24])); res.append([it['no'],it['des'],it['cmt'],it['qty'],it['code'],'','','FAIL']); continue
    iscny=any(x[2] for x in L) if L and len(L[0])>2 else False
    unit=p if iscny else (p*rate if rate else None)
    if unit is None: miss.append(it['code']); continue
    sub=unit*it['qty']; tot+=sub
    lad=','.join('%d+:%.4f'%(q,(pr if iscny else pr*rate)) for q,pr,_, in [(x[0],x[1],0) for x in L][:4])
    print('%-8s %-4d %8.4f  %-34s %8.2f  %s'%(it['code'],it['qty'],unit,lad[:34],sub,it['cmt'][:20]))
    res.append([it['no'],it['des'],it['cmt'],it['qty'],it['code'],'%.4f'%unit,'%.2f'%sub,('CNY' if iscny else 'USDx%.2f'%(rate or 0))])
    time.sleep(0.5)
with open('lcsc_prices.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['No.','位号','物料','数量','立创码','单价(元)','小计(元)','价源']);w.writerows(res)
print('\n==== 物料成本合计(不含客供料): ￥%.2f ===='%tot)
print('取价失败: %s'%(','.join(miss) if miss else '无'))
print('明细: lcsc_prices.csv')
