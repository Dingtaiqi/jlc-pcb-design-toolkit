import json, math, urllib.request, collections

BRIDGE = "http://localhost:49620/execute"


def q(js, timeout=300):
    req = urllib.request.Request(BRIDGE,
        data=json.dumps({"code": js}).encode(),
        headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
    if not r.get("success"):
        raise RuntimeError(str(r)[:400])
    return r.get("result")


nets = json.loads(q("const n=await eda.pcb_Net.getAllNetName(); return JSON.stringify(n);"))

# collect all pads with real geometry
pads = []           # (net, parentId, layerId, x, y, w, h, rot)
for net in nets:
    for attempt in range(3):
        try:
            raw = q("const r=await eda.pcb_Net.getAllPrimitivesByNet(%s);"
                    "return JSON.stringify(r.filter(p=>p.net).map(p=>[p.net,p.parentId,"
                    "p.layerId,p.center.x,p.center.y,p.topWidth,p.topHeight,p.rotation]));"
                    % json.dumps(net))
            pads.extend(json.loads(raw))
            break
        except Exception:
            continue

print("pads collected:", len(pads))
print()

# U6 surroundings
raw = q("const cs=await eda.pcb_PrimitiveComponent.getAll();"
        "const o={}; for(const c of cs) o[c.getState_PrimitiveId()]=c.getState_Designator();"
        "return JSON.stringify(o);")
id2des = json.loads(raw)


def des(pid):
    return id2des.get(pid, pid)


# keep pads within a window around U6
UX, UY, R = 66.0, 34.0, 14.0
near = []
for net, pid, layer, x, y, w, h, rot in pads:
    if not isinstance(x, (int, float)):
        continue
    if abs(x - UX) <= R and abs(y - UY) <= R:
        near.append((net, des(pid), x, y, float(w or 0), float(h or 0), rot))
print("pads within %.0f mm of U6: %d" % (R, len(near)))

# axis-aligned extent of a rotated rect
def extents(x, y, w, h, rot):
    a = math.radians(rot or 0)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    ew = w * c + h * s
    eh = w * s + h * c
    return x - ew / 2, x + ew / 2, y - eh / 2, y + eh / 2


boxes = []
for net, d, x, y, w, h, rot in near:
    x0, x1, y0, y1 = extents(x, y, w, h, rot)
    boxes.append((net, d, x, y, x0, x1, y0, y1))

gaps = []
for i in range(len(boxes)):
    for j in range(i + 1, len(boxes)):
        na, da, xa, ya, ax0, ax1, ay0, ay1 = boxes[i]
        nb, db, xb, yb, bx0, bx1, by0, by1 = boxes[j]
        if da == db:
            continue
        dx = max(0.0, bx0 - ax1, ax0 - bx1)
        dy = max(0.0, by0 - ay1, ay0 - by1)
        gap = math.hypot(dx, dy)
        gaps.append((gap, da, nb, db))

gaps.sort()
print()
print("=== tightest pad-to-pad gaps between different components near U6 ===")
print("%-8s %-14s %-14s" % ("gap mm", "comp A", "comp B"))
seen = set()
shown = 0
for gap, da, nb, db in gaps:
    key = tuple(sorted([da, db]))
    if gap > 0.35:
        break
    if key in seen:
        continue
    seen.add(key)
    print("%-8.3f %-14s %-14s (%s)" % (gap, da, db, nb))
    shown += 1
    if shown > 40:
        break
if shown == 0:
    print("  (none under 0.35 mm)")

under = [g for g in gaps if g[0] < 0.2]
print()
print("pairs under 0.20 mm : %d" % len(under))
print("pairs under 0.15 mm : %d" % len([g for g in gaps if g[0] < 0.15]))
