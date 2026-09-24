# -*- coding: utf-8 -*-
"""_pcb_inventory.py —— PCB 侧"每个网络有多少铜"清点(只读, 轻调用)

为什么要有它: 原理图改动后点"导入变更"会按新网表删/改铜。提前知道每个网络的铜量,
一旦确认哪个网络被删/改, 就能立刻说出"会少多少铜、要不要补线"。

输出: _pcb_net_inventory.json + 屏幕摘要
"""
import io, json, collections, urllib.request

BRIDGE = "http://localhost:49620/execute"
JS = """
const NM=n=>n==null?null:(typeof n==='string'?n:(n.name!==undefined?String(n.name):String(n)));
const L=(await eda.pcb_PrimitiveLine.getAll())||[];
const V=(await eda.pcb_PrimitiveVia.getAll())||[];
const C=(await eda.pcb_PrimitiveComponent.getAll())||[];
const inv={};
const get=n=>{ if(!n) return null; if(!inv[n]) inv[n]={lines:0,vias:0,lineLen:0,pads:0,comps:{}}; return inv[n]; };
const ML=1/0.0254;
for(const l of L){ const e=get(NM(l.net)); if(!e) continue; e.lines++;
  e.lineLen+=Math.hypot(l.endX-l.startX,l.endY-l.startY)/ML; }
for(const v of V){ const e=get(NM(v.net)); if(!e) continue; e.vias++; }
for(const c of C){
  for(const p of (c.pads||[])){ const n=NM(p.net); if(!n) continue;
    const e=get(n); e.pads++; e.comps[c.designator||'?']=(e.comps[c.designator||'?']||0)+1; }
}
const o={};
for(const k in inv){ const e=inv[k];
  o[k]={lines:e.lines,vias:e.vias,lineLenMm:+e.lineLen.toFixed(1),pads:e.pads,
        comps:Object.keys(e.comps).length}; }
return JSON.stringify({nets:o,total:{lines:L.length,vias:V.length,comps:C.length}});
"""
req = urllib.request.Request(BRIDGE, data=json.dumps({"code": JS}).encode(),
                            headers={"Content-Type": "application/json"})
r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
if not r.get("success"):
    print("ERR:", json.dumps(r, ensure_ascii=False)[:300]); raise SystemExit(1)
d = json.loads(r["result"])
io.open("_pcb_net_inventory.json", "w", encoding="utf-8").write(
    json.dumps(d, ensure_ascii=False, indent=1))

nets = d["nets"]
print("总图元:", d["total"], " 有铜的网络数:", len(nets))
copper = {k: v for k, v in nets.items() if v["lines"] or v["vias"]}
print("其中带线/过孔的网络:", len(copper))
print("\n铜最多的 15 个网络:")
for k, v in sorted(copper.items(), key=lambda kv: -(kv[1]["lineLenMm"] + kv[1]["vias"] * 3))[:15]:
    print("   %-16s 线 %4d (%.0fmm)  过孔 %3d  焊盘 %2d  器件 %d"
          % (k, v["lines"], v["lineLenMm"], v["vias"], v["pads"], v["comps"]))
print("\n只有焊盘没有线的网络(未布线):")
nc = [k for k, v in nets.items() if not v["lines"] and not v["vias"]]
print("   ", len(nc), nc[:20])
print("\n已存 _pcb_net_inventory.json")
