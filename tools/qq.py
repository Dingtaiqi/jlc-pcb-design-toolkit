import io
import json,sys,urllib.request
src=sys.argv[1]; to=int(sys.argv[2]) if len(sys.argv)>2 else 180
code=io.open(src,encoding='utf-8').read() if src.endswith(('.js','.txt')) else src
req=urllib.request.Request("http://localhost:49620/execute",
  data=json.dumps({"code":code}).encode(),headers={"Content-Type":"application/json"})
try:
    print(urllib.request.urlopen(req,timeout=to).read().decode())
except Exception as e:
    print("ERR",e)
