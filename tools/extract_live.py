import json, io, urllib.request, time

BRIDGE = "http://localhost:49620/execute"

def q(js, timeout=600, tries=3):
    last=None
    for _ in range(tries):
        try:
            req = urllib.request.Request(BRIDGE, data=json.dumps({"code": js}).encode(),
                                         headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
            if r.get("success"): return r.get("result")
            last=str(r)[:200]
        except Exception as e:
            last=str(e)[:200]
        time.sleep(1.0)
    raise RuntimeError(last)

MIL = 1/0.0254

# ---- lines
raw = q("""
const MIL=1/0.0254; function NM(n){ if(n==null) return null; if(typeof n==="string") return n; if(n.name!==undefined) return String(n.name); return String(n); } const L=await eda.pcb_PrimitiveLine.getAll(); const o=[];
for(const l of L){ o.push([l.getState_PrimitiveId(), NM(l.getState_Net()), l.getState_Layer(),
  +(l.getState_StartX()/MIL).toFixed(4), +(l.getState_StartY()/MIL).toFixed(4),
  +(l.getState_EndX()/MIL).toFixed(4), +(l.getState_EndY()/MIL).toFixed(4),
  +(l.getState_LineWidth()/MIL).toFixed(4)]); }
return JSON.stringify(o);""")
lines = json.loads(raw)
print("lines:", len(lines))

# ---- vias
raw = q("""
const MIL=1/0.0254; function NM(n){ if(n==null) return null; if(typeof n==="string") return n; if(n.name!==undefined) return String(n.name); return String(n); } const V=await eda.pcb_PrimitiveVia.getAll(); const o=[];
for(const v of V){ let n=null; try{n=NM(v.getState_Net());}catch(e){}
  o.push([v.getState_PrimitiveId(), n, +(v.getState_X()/MIL).toFixed(4), +(v.getState_Y()/MIL).toFixed(4),
          +(v.getState_Diameter()/MIL).toFixed(4), +(v.getState_HoleDiameter()/MIL).toFixed(4)]); }
return JSON.stringify(o);""")
vias = json.loads(raw)
print("vias:", len(vias))

# ---- pads
raw = q("""
const MIL=1/0.0254; function NM(n){ if(n==null) return null; if(typeof n==="string") return n; if(n.name!==undefined) return String(n.name); return String(n); } const P=await eda.pcb_PrimitivePad.getAll(); const o=[];
for(const p of P){
  let n=null,h=null; try{n=NM(p.getState_Net());}catch(e){} try{h=p.getState_Hole();}catch(e){}
  o.push([n, p.getState_Layer(), +(p.getState_X()/MIL).toFixed(4), +(p.getState_Y()/MIL).toFixed(4),
          String(p.getState_Pad()), String(h), String(p.getState_PadNumber()),
          +(p.getState_Rotation()||0).toFixed(4)]);
}
return JSON.stringify(o);""")
pads = json.loads(raw)
print("pads:", len(pads))

# ---- special objects (cutout / keepout candidates)
raw = q("""
const MIL=1/0.0254; const o={};
const R=await eda.pcb_PrimitiveRegion.getAll();
o.regions=(R||[]).map(function(r){ let b=null; try{ const p=r.getState_ComplexPolygon&&r.getState_ComplexPolygon(); b=JSON.stringify(p).slice(0,200);}catch(e){} 
  return [r.getState_PrimitiveId(), r.getState_Layer(), r.getState_RegionName?String(r.getState_RegionName()):"", b]; });
const F=await eda.pcb_PrimitiveFill.getAll();
o.fills=(F||[]).map(function(f){ return [f.getState_PrimitiveId(), f.getState_Layer()]; });
return JSON.stringify(o);""")
spec = json.loads(raw)
print("specials:", json.dumps(spec)[:500])

io.open("live.json","w",encoding="utf-8").write(json.dumps({"lines":lines,"vias":vias,"pads":pads,"spec":spec}))
print("saved live.json")
