# -*- coding: utf-8 -*-
"""
export_all.py -- 把当前 PCB 的全部制造文件导出到 ./deliver/

背景: EasyEDA Pro 的 eda.pcb_ManufactureData.* 返回的是浏览器 File 对象,
      不能直接落盘; 本脚本在浏览器侧读成 arrayBuffer -> base64 送回 Python 解码写文件。

用法:
    python export_all.py            # 导出全部
    python export_all.py gerber bom # 只导出指定项
    python export_all.py --list     # 只列可用接口, 不导出

退出码: 0 全部成功 / 1 部分失败 / 2 全失败
"""
import base64
import json
import os
import sys
import time
import urllib.request

BRIDGE = "http://localhost:49620/execute"
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deliver")
MAX_MB = 40  # 单个文件超过此大小则跳过 (桥接是 JSON 文本通道)

# key -> (中文名, 取文件表达式)
ITEMS = {
    "gerber":    ("嘉立创/通用 Gerber+钻孔 zip", "M.getGerberFile()"),
    "bom":       ("BOM 物料表",                  "M.getBomFile()"),
    "pickplace": ("贴片坐标 Pick&Place",         "M.getPickAndPlaceFile()"),
    "netlist":   ("网表",                        "M.getNetlistFile()"),
    "ipc356":    ("IPC-D-356A 测试网表",         "M.getIpcD356AFile()"),
    "pdf":       ("装配/丝印 PDF",               "M.getPdfFile()"),
    "dxf":       ("DXF 结构图",                  "M.getDxfFile()"),
    "step3d":    ("3D STEP 模型",                "M.get3DFile()"),
    "pcbinfo":   ("PCB 信息",                    "M.getPcbInfoFile()"),
}

JS_TMPL = r"""
const M = eda.pcb_ManufactureData;
const out = {};
const toB64 = (bytes) => {
  let s = ''; const CH = 8192;
  for (let i = 0; i < bytes.length; i += CH) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  }
  return btoa(s);
};
%(calls)s
return JSON.stringify(out);
"""

CALL_TMPL = r"""
try {
  const f = await %(expr)s;
  if (!f) { out['%(key)s'] = { err: '返回 null/undefined' }; }
  else if (f.size > %(maxbytes)d) {
    out['%(key)s'] = { err: 'too big', name: f.name, size: f.size };
  } else {
    const bytes = new Uint8Array(await f.arrayBuffer());
    out['%(key)s'] = { name: f.name, type: f.type, size: bytes.length, b64: toB64(bytes) };
  }
} catch (e) {
  out['%(key)s'] = { err: String(e) };
}
"""


def post(code, timeout=300):
    body = json.dumps({"code": code}).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    argv = [a for a in sys.argv[1:]]
    if "--list" in argv:
        for k, (label, expr) in ITEMS.items():
            print("%-10s %s" % (k, label))
        return 0

    keys = [a for a in argv if not a.startswith("-")] or list(ITEMS)
    bad = [k for k in keys if k not in ITEMS]
    if bad:
        print("未知导出项: %s\n可用: %s" % (bad, ", ".join(ITEMS)))
        return 2

    os.makedirs(OUTDIR, exist_ok=True)
    calls = "\n".join(
        CALL_TMPL % {"key": k, "expr": ITEMS[k][1], "maxbytes": MAX_MB * 1024 * 1024}
        for k in keys
    )
    t0 = time.time()
    print("导出 %d 项 -> %s" % (len(keys), OUTDIR))
    try:
        resp = post(JS_TMPL % {"calls": calls})
    except Exception as e:
        print("桥接调用失败: %s" % e)
        return 2
    if not resp.get("success"):
        print("桥接返回失败: %s" % json.dumps(resp, ensure_ascii=False)[:400])
        return 2

    res = json.loads(resp["result"])
    ok = fail = 0
    for k in keys:
        label = ITEMS[k][0]
        r = res.get(k) or {"err": "无返回"}
        if "err" in r:
            print("  [失败] %-10s %-24s %s" % (k, label, r["err"]))
            fail += 1
            continue
        raw = base64.b64decode(r["b64"])
        name = r.get("name") or (k + ".bin")
        # 防目录穿越
        name = os.path.basename(name)
        path = os.path.join(OUTDIR, name)
        with open(path, "wb") as f:
            f.write(raw)
        print("  [成功] %-10s %-24s %8.1f KB  %s"
              % (k, label, len(raw) / 1024.0, name))
        ok += 1

    print("\n成功 %d / 失败 %d   耗时 %.1fs" % (ok, fail, time.time() - t0))
    if ok == 0:
        return 2
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
