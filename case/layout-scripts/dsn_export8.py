# -*- coding: utf-8 -*-
import json, io, re, urllib.request
BRIDGE="http://localhost:49620/execute"
def q(js,timeout=300,tries=3):
    last=None
    for _ in range(tries):
        try:
            req=urllib.request.Request(BRIDGE,data=json.dumps({"code":js}).encode(),
                                       headers={"Content-Type":"application/json"})
            r=json.loads(urllib.request.urlopen(req,timeout=timeout).read().decode())
            if r.get("success"): return r.get("result")
            last=str(r)[:200]
        except Exception as e:
            last=str(e)[:200]
    raise RuntimeError(last)
n=int(q("const f=await eda.pcb_ManufactureData.getDsnFile(); const t=await f.text();"
        " window.__dsn=t; return String(t.length);"))
print("DSN 长度:",n,flush=True)
parts=[]; step=50000
for i in range(0,n,step):
    parts.append(q("return window.__dsn.substr(%d,%d);"%(i,step)))
dsn="".join(parts)
out=r"D:\360Downloads\tourbox\pcb-layout\tools\tourbox8.dsn"
io.open(out,"w",encoding="utf-8",newline="\n").write(dsn)
print("已写出:",out,len(dsn),"字符",flush=True)
print("层定义:", sorted(set(re.findall(r"\(layer\s+([A-Za-z0-9_]+)", dsn)))[:12], flush=True)
print("(wire 段数:", dsn.count("(wire"), flush=True)
print("(component 数:", dsn.count("(component"), "  (place 数:", dsn.count("(place"), flush=True)
print("前 300 字符:"); print(dsn[:300])
