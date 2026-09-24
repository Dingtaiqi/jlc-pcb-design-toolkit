#!/usr/bin/env python
"""Body-level placement audit: estimate each part's physical body box from its pads
(+ type margin) and find every body-body overlap. LC = 'real mechanical' parts."""
import json, io, math, time, urllib.request, collections, re

BASE = r"D:\360Downloads\tourbox\pcb-layout"
BRIDGE = "http://localhost:49620/execute"
MIL = 1 / 0.0254


def q(js, timeout=300, tries=3):
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
        time.sleep(1.0)
    raise RuntimeError(last)


# ---- fetch components with their pin positions ----
raw = q("""
const MIL=1/0.0254; const C=await eda.pcb_PrimitiveComponent.getAll(); const o=[];
for(const c of C){
  const pins=[];
  try{ const ps=await c.getAllPins();
    for(const p of ps){ const x=(p.getState_X?p.getState_X():p.x)/MIL, y=(p.getState_Y?p.getState_Y():p.y)/MIL;
      pins.push([+x.toFixed(3), +y.toFixed(3), String(p.getState_Net?p.getState_Net():p.net||"")]); }
  }catch(e){}
  o.push({d:c.getState_Designator(), x:+(c.getState_X()/MIL).toFixed(3), y:+(c.getState_Y()/MIL).toFixed(3),
          r:c.getState_Rotation(), l:c.getState_Layer(), pins:pins});
}
return JSON.stringify(o);
""")
parts = json.loads(raw)
print("components:", len(parts))
io.open(BASE + r"\parts_now.json", "w", encoding="utf-8").write(json.dumps(parts, indent=1))

# margin by designator class (half-extent added around the pad bbox)
def margin(d):
    if re.match(r"^SW\d+$", d):     return 1.2      # tactile switch body
    if re.match(r"^H\d+$", d):      return 1.2      # headers
    if d in ("USB1", "CN1"):        return 2.5      # connector shells
    if re.match(r"^U\d+$", d):      return 0.8      # ICs (EP + body)
    if re.match(r"^X\d+$", d):      return 0.4      # crystals
    if re.match(r"^L\d+$", d):      return 0.4      # inductors
    return 0.25                                     # passives


BOX = {}
for p in parts:
    if p["pins"]:
        xs = [q_[0] for q_ in p["pins"]]; ys = [q_[1] for q_ in p["pins"]]
        m = margin(p["d"])
        BOX[p["d"]] = (min(xs) - m, max(xs) + m, min(ys) - m, max(ys) + m, p["x"], p["y"], p["l"])
    else:
        BOX[p["d"]] = (p["x"] - 1, p["x"] + 1, p["y"] - 1, p["y"] + 1, p["x"], p["y"], p["l"])

LOCKED = set(["U5", "H1", "U7", "L7", "H2", "H5", "CN1", "LED1"]
             + ["SW%d" % i for i in range(1, 14)] + ["H%d" % i for i in range(3, 13)])

print("\n=== 本体盒尺寸（关键件）===")
for d in ("U1", "U6", "U2", "U3", "U4", "U8", "SW12", "SW4", "SW3", "USB1", "X1", "X2", "LDO1", "U9", "U10"):
    if d in BOX:
        b = BOX[d]
        print("   %-5s x %.2f..%.2f (%.2f)  y %.2f..%.2f (%.2f)  L%s"
              % (d, b[0], b[1], b[1] - b[0], b[2], b[3], b[3] - b[2], b[6]))

print("\n=== 本体级冲突 ===")
ks = sorted(BOX.keys())
conf = []
for i in range(len(ks)):
    for j in range(i + 1, len(ks)):
        a, b = ks[i], ks[j]
        A, B = BOX[a], BOX[b]
        ox = min(A[1], B[1]) - max(A[0], B[0])
        oy = min(A[3], B[3]) - max(A[2], B[2])
        if ox > 0 and oy > 0:
            conf.append((a, b, round(ox, 2), round(oy, 2),
                         "LOCK-LOCK" if (a in LOCKED and b in LOCKED) else "fixable"))
print("总计 %d 对" % len(conf))
for c in sorted(conf, key=lambda t: -(t[2] * t[3])):
    print("   %-5s <-> %-5s  overlap %.2f x %.2f mm   %s" % c)
json.dump({"box": {k: list(v) for k, v in BOX.items()}, "conflicts": conf},
          io.open(BASE + r"\body_audit.json", "w"), indent=1)
