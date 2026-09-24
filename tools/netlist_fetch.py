# -*- coding: utf-8 -*-
"""_netlist_fetch.py —— 只调一次 getNetlist(), 把当前活动文档的网表存下来(只读)

用法:  python tools/_netlist_fetch.py pcb      # PCB 侧  eda.pcb_Net.getNetlist()
       python tools/_netlist_fetch.py sch      # 原理图侧 eda.sch_Netlist.getNetlist()
说明: 解析后只打印结构摘要, 原文存 _netlist_<side>.raw.json, 供对账脚本用。
★安全: 单次调用 + 30s 超时 + 不重试(重 API 会锁死 EDA 主线程, 见 PITFALLS #23)
"""
import io, json, sys, urllib.request

BRIDGE = "http://localhost:49620/execute"
side = (sys.argv[1] if len(sys.argv) > 1 else 'pcb').lower()
TIMEOUT = int(sys.argv[2]) if len(sys.argv) > 2 else 30
CALL = "eda.pcb_Net.getNetlist()" if side == 'pcb' else "eda.sch_Netlist.getNetlist()"
JS = "const r=await %s; return (typeof r==='string')?r:JSON.stringify(r);" % CALL

req = urllib.request.Request(BRIDGE, data=json.dumps({"code": JS}).encode(),
                            headers={"Content-Type": "application/json"})
try:
    r = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode())
except Exception as e:
    print("调用失败(不重试):", str(e)[:160]); sys.exit(1)
if not r.get("success"):
    print("EDA 报错:", json.dumps(r, ensure_ascii=False)[:300]); sys.exit(1)

raw = r.get("result") or ''
if not isinstance(raw, str):
    raw = json.dumps(raw, ensure_ascii=False)
io.open("_netlist_%s.raw.json" % side, "w", encoding="utf-8").write(raw)
print("侧=%s  原文长度=%d 字符" % (side, len(raw)))
try:
    d = json.loads(raw)
except Exception as e:
    print("不是 JSON:", str(e)[:120], "  前 300 字:", raw[:300]); sys.exit(0)
print("顶层键:", list(d.keys()))
comp = d.get('components') or {}
print("元件数:", len(comp))
# 结构摘要: 找"网络->引脚"到底藏在哪
def probe(obj, path='', depth=0, hits=None):
    if hits is None: hits = []
    if depth > 3: return hits
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:40]:
            kk = str(k)
            if 'net' in kk.lower() or 'pin' in kk.lower() or kk.lower() in ('nodes', 'connections'):
                hits.append((path + '/' + kk, type(v).__name__, (len(v) if hasattr(v, '__len__') else '')))
            probe(v, path + '/' + kk, depth + 1, hits)
    elif isinstance(obj, list) and obj:
        probe(obj[0], path + '[0]', depth + 1, hits)
    return hits
hits = probe(d)
print("含 net/pin 字样的字段(前 25):")
for h in hits[:25]: print("   ", h)
if comp:
    k0 = list(comp.keys())[0]
    print("样例元件键:", list(comp[k0].keys()))
    print("样例元件:", json.dumps(comp[k0], ensure_ascii=False)[:500])
