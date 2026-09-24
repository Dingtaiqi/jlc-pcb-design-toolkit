import json,urllib.request,re,collections
code="""try{ const r=await eda.pcb_Drc.check(false,false,true); return JSON.stringify(Array.isArray(r)?r:(r?[r]:[])); }catch(e){ return JSON.stringify([]); }"""
req=urllib.request.Request("http://localhost:49620/execute",data=json.dumps({"code":code}).encode(),headers={"Content-Type":"application/json"})
a=json.loads(json.loads(urllib.request.urlopen(req,timeout=240).read().decode())["result"])
nets=collections.Counter()
for g in a:
    for sub in g.get('list',[]):
        for it in sub.get('list',[]):
            for o in (it.get('objs') or []):
                pass
            for side in ('obj1','obj2'):
                s=(it.get(side) or {}).get('suffix') or ''
                m=re.match(r'\(([^)]+)\)', s)
                if m: nets[m.group(1)]+=1
print("nets appearing in DRC violations:")
for k,v in nets.most_common(40): print("   %-16s %d"%(k,v))
