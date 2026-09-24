# -*- coding: utf-8 -*-
"""清空旧铜 -> 分块传输 SES 文本 -> 用 importAutoRouteSesFile 导入。"""
import json, io, urllib.request, time, sys, os

BRIDGE = "http://localhost:49620/execute"
# 用法: python ses_import.py [D:\...\tools\tourbox5.ses]  （缺省 = tourbox4.ses，兼容旧调用）
SES_PATH = sys.argv[1] if len(sys.argv) > 1 else r"D:\360Downloads\tourbox\pcb-layout\tools\tourbox4.ses"
SES_NAME = os.path.basename(SES_PATH)


def q(js, timeout=600, tries=3):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(BRIDGE, data=json.dumps({"code": js}).encode(),
                                         headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
            if r.get("success"):
                return r.get("result")
            last = str(r)[:200]
        except Exception as e:
            last = str(e)[:200]
    raise RuntimeError(last)


print("清空旧铜:", q(
    "const L=await eda.pcb_PrimitiveLine.getAll(); const V=await eda.pcb_PrimitiveVia.getAll();"
    " const lids=L.map(function(x){return x.getState_PrimitiveId();});"
    " const vids=V.map(function(x){return x.getState_PrimitiveId();});"
    " if(lids.length) await eda.pcb_PrimitiveLine.delete(lids);"
    " if(vids.length) await eda.pcb_PrimitiveVia.delete(vids);"
    " return JSON.stringify({lines:lids.length,vias:vids.length});"), flush=True)

ses = io.open(SES_PATH, encoding="utf-8").read()
print("SES 文件:", SES_PATH, flush=True)
print("SES 长度:", len(ses), flush=True)
q("window.__ses=''; return 'ok';")
step = 8000
t0 = time.time()
for i in range(0, len(ses), step):
    chunk = json.dumps(ses[i:i + step])
    q("window.__ses += %s; return String(window.__ses.length);" % chunk)
print("传输完成 %.1fs" % (time.time() - t0), flush=True)
print("JS 端长度:", q("return String(window.__ses.length);"), flush=True)

res = q("try{ const f=new File([window.__ses],%s,{type:'text/plain'});" % json.dumps(SES_NAME) +
        " const r=await eda.pcb_Document.importAutoRouteSesFile(f);"
        " return 'OK '+String(JSON.stringify(r)).slice(0,200); }"
        "catch(e){ return 'ERR '+String(e&&e.message?e.message:e).slice(0,300); }", timeout=900)
print("导入结果:", res, flush=True)
