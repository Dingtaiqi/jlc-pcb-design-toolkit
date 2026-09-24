import json,urllib.request
def q(js,t=200):
    req=urllib.request.Request("http://localhost:49620/execute",
        data=json.dumps({"code":js}).encode(),headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(req,timeout=t).read().decode()).get("result")
want = {
 "PWM_LU": ["U1.26","U4.28"],
 "PWM_LV": ["U1.28","U4.30"],
 "PGND":   ["U4.12","U4.15","R14.2","C23.1"],
 "ADC1.1": ["U4.39","R23.1"],
 "SDO":    ["U1.20","U4.33","H2.5"],
 "XL1":    ["X2.1","U6.D2","C43.2"],
 "$1N19139":["C62.2","U6.AC5"],
}
out={}
for net, refs in want.items():
    row=[]
    for ref in refs:
        d,p = ref.rsplit(".",1)
        js=("const cs=await eda.pcb_PrimitiveComponent.getAll();"
            "const c=cs.find(x=>x.getState_Designator()===%s); if(!c) return 'NONE';"
            "const ps=await c.getAllPins();"
            "const p=ps.find(z=>String(z.getState_PadNumber())===%s); if(!p) return 'NONE';"
            "return (Number(p.getState_X())*0.0254).toFixed(3)+','+(Number(p.getState_Y())*0.0254).toFixed(3);"
            % (json.dumps(d), json.dumps(p)))
        r=q(js,120)
        row.append((ref, r))
    out[net]=row
for net,row in out.items():
    print("=== %s ==="%net)
    for ref,r in row: print("   %-10s %s"%(ref,r))
