import json,urllib.request
PLACE = [
 # ---- U6 ----
 ["U6",66.0,34.0,270,1],
 # ---- RF chain y=35 ----
 ["C55",72.5,35.0,90,1],
 ["C56",74.5,35.0,90,1],
 ["C57",76.5,35.0,90,1],
 ["C65",78.5,35.0,90,1],
 ["L6", 80.7,35.0,0,1],
 ["C66",82.6,35.0,90,1],
 ["L7", 86.8,35.0,0,1],
 ["R28",84.8,31.3,0,1],
 # ---- above U6 : X3 32MHz ----
 ["X3", 70.0,41.5,0,1],
 ["C51",65.5,41.5,0,1],
 ["C52",74.5,41.5,0,1],
 # ---- left of U6 : X2 32k ----
 ["X2", 58.0,36.0,0,1],
 ["C43",61.0,38.5,0,1],
 ["C44",61.0,33.5,0,1],
 # ---- left column : DC-DC + analog ----
 ["L2", 57.5,40.5,90,1],
 ["L3", 57.5,38.0,90,1],
 ["C47",55.5,43.0,90,1],
 ["C48",55.5,40.5,90,1],
 ["C49",55.5,38.0,90,1],
 ["C45",61.0,31.0,0,1],
 ["C62",61.0,28.5,0,1],
 ["C61",61.0,26.0,0,1],
 ["L4", 58.0,26.0,0,1],
 ["C64",57.5,23.5,0,1],
 ["C46",60.0,23.5,0,1],
 # ---- bottom-right : VCC_NRF bank + misc ----
 ["C53",71.0,30.5,0,1],
 ["C59",73.5,30.5,0,1],
 ["C60",76.0,30.5,0,1],
 ["C50",71.0,27.5,0,1],
 ["C54",73.5,27.5,0,1],
 ["C58",76.0,27.5,0,1],
 ["C63",66.5,28.5,0,1],
]
code = """
const P = %s;
const cs = await eda.pcb_PrimitiveComponent.getAll();
const by = {}; for (const c of cs) by[c.getState_Designator()] = c;
const missing = [], done = [];
for (const row of P) {
  const d = row[0], x = row[1], y = row[2], r = row[3], l = row[4];
  const c = by[d];
  if (!c) { missing.push(d); continue; }
  c.setState_X(x / 0.0254);
  c.setState_Y(y / 0.0254);
  c.setState_Rotation(r);
  c.setState_Layer(l);
  await c.done();
  done.push(d);
}
await eda.pcb_Document.save();
return JSON.stringify({placed: done.length, missing: missing});
""" % (json.dumps(PLACE),)
req = urllib.request.Request("http://localhost:49620/execute",
    data=json.dumps({"code": code}).encode(),
    headers={"Content-Type": "application/json"})
try:
    print(urllib.request.urlopen(req, timeout=180).read().decode())
except Exception as e:
    print("ERR", e)
