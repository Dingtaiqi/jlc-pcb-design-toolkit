#!/usr/bin/env python
# Hand-route the short open nets directly, then validate with DRC.
import json, re, time, urllib.request

BRIDGE = "http://localhost:49620/execute"
MIL = 1 / 0.0254


def q(js, timeout=280, tries=4):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(BRIDGE,
                data=json.dumps({"code": js}).encode(),
                headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
            if r.get("success"):
                return r.get("result")
            last = str(r)[:200]
        except Exception as e:
            last = str(e)[:200]
        time.sleep(1.5)
    raise RuntimeError(last)


def track(net, layer, x1, y1, x2, y2, w):
    return q("try{ const t=await eda.pcb_PrimitiveLine.create(%s,%d,%f,%f,%f,%f,%f,false);"
             " return t?'ok':'undef'; }catch(e){ return 'ERR '+escape(String(e&&e.message?e.message:e)); }"
             % (json.dumps(net), layer, x1 * MIL, y1 * MIL, x2 * MIL, y2 * MIL, w * MIL), 120)


def via(net, x, y, drill=0.305, dia=0.61):
    return q("try{ const v=await eda.pcb_PrimitiveVia.create(%s,%f,%f,%f,%f);"
             " return v?'ok':'undef'; }catch(e){ return 'ERR '+escape(String(e&&e.message?e.message:e)); }"
             % (json.dumps(net), x * MIL, y * MIL, drill * MIL, dia * MIL), 120)


def drc_for(nets):
    raw = q("try{ const r=await eda.pcb_Drc.check(false,false,true);"
            " return JSON.stringify(Array.isArray(r)?r:(r?[r]:[])); }"
            "catch(e){ return JSON.stringify([]); }")
    groups = json.loads(raw)
    res = {}
    for g in groups:
        for sub in g.get("list", []):
            nm = sub.get("name")
            for it in sub.get("list", []):
                for side in ("obj1", "obj2"):
                    s = ((it.get(side) or {}).get("suffix") or "")
                    m = re.match(r"\(([^)]+)\)", s)
                    if m and m.group(1) in nets:
                        res.setdefault((g.get("name"), m.group(1)), []).append(s)
    return res


JOBS = {
    "XL1": (0.254, [
        ("T", 59.499, 37.249, 61.000, 37.249),
        ("T", 61.000, 37.249, 61.000, 36.000),
        ("T", 61.000, 36.000, 63.251, 35.999),
    ]),
    "$1N19139": (0.30, [
        ("T", 61.699, 28.499, 64.000, 28.499),
        ("T", 64.000, 28.499, 64.000, 31.250),
    ]),
    "ADC1.1": (0.254, [
        ("T", 6.759, 41.041, 16.137, 41.041),
        ("T", 16.137, 41.041, 16.137, 43.180),
    ]),
}

for net, (w, segs) in JOBS.items():
    print("=== routing %s (w=%.3f) ===" % (net, w))
    for lay, x1, y1, x2, y2 in segs:
        layer = 1 if lay == "T" else 2
        r = track(net, layer, x1, y1, x2, y2, w)
        print("   %s (%.3f,%.3f)->(%.3f,%.3f) : %s" % (lay, x1, y1, x2, y2, r))
    q("await eda.pcb_Document.save(); return 'ok';", 120)

print()
print("=== DRC check for these nets ===")
bad = drc_for(set(JOBS.keys()))
if not bad:
    print("   CLEAN - no violations involving these nets")
else:
    for (grp, net), items in sorted(bad.items()):
        print("   %-20s %-10s %d  %s" % (grp, net, len(items), items[:3]))
