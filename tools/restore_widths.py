# -*- coding: utf-8 -*-
"""把板上走线的线宽恢复成 Freerouting SES 里的原始线宽。

背景（已实测）：
  EasyEDA 的 SES 导入器不用 SES 里的线宽，而是用板子的 net rule / 默认 Track 宽度
  （本板复位注入规则后 = 0.254mm）。FR 是按自己的线宽(默认 = DSN 结构级 width)布线的，
  被加粗后铜的净间距会变小 → 产生 <0.152mm 的假/真违规；反之变细则更安全。
  本脚本按"层 + 端点（先估计全局平移）"把每条走线映射回 SES 段，恢复其线宽。

用法: python restore_widths.py <ses文件> [--apply]
      缺省只做 dry-run（只报告），--apply 才写回板子。
"""
import io, re, json, sys, collections, urllib.request

BRIDGE = "http://localhost:49620/execute"
ROOT = r"D:\360Downloads\tourbox\pcb-layout"
LAYER_OF = {"TopLayer": 1, "BottomLayer": 2, "Inner1": 15, "Inner2": 16}
MM_PER_UNIT = 0.0254 / 1000.0          # SES: 1 unit = 1/1000 mil


def q(js, timeout=600, tries=3):
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
    raise RuntimeError(last)


def parse_ses(path):
    s = io.open(path, encoding="utf-8").read()
    i = s.find("(network_out")
    body = s[i:] if i >= 0 else s
    segs = []
    pos = 0
    net_re = re.compile(r"\(net\s+(\S+)")
    while True:
        m = net_re.search(body, pos)
        if not m:
            break
        name = m.group(1).strip('"')
        d = 0
        k = m.start()
        while k < len(body):
            if body[k] == "(":
                d += 1
            elif body[k] == ")":
                d -= 1
                if d == 0:
                    break
            k += 1
        blk = body[m.start():k + 1]
        pos = k + 1
        for pm in re.finditer(r"\(path\s+(\w+)\s+(\d+)((?:\s+-?\d+)+\s*)\)", blk):
            lay = LAYER_OF.get(pm.group(1))
            w = int(pm.group(2)) * MM_PER_UNIT
            pts = [int(x) * MM_PER_UNIT for x in pm.group(3).split()]
            xs, ys = pts[0::2], pts[1::2]
            for j in range(len(xs) - 1):
                segs.append([name, lay, w, xs[j], ys[j], xs[j + 1], ys[j + 1]])
    return segs


def estimate_offset(lines, segs):
    """用最大网络的方向/长度分组，投票出 (dx,dy)"""
    by = collections.defaultdict(list)
    for s in segs:
        by[s[0]].append(s)
    best = None
    cnt = collections.Counter()
    for net, ls in sorted(((n, v) for n, v in by.items()), key=lambda kv: -len(kv[1]))[:6]:
        for L in lines:
            if L[1] != net:
                continue
            for s in by[net]:
                if s[1] != L[2]:
                    continue
                dx = round(L[3] - s[3], 2)
                dy = round(L[4] - s[4], 2)
                cnt[(dx, dy)] += 1
    if not cnt:
        return (0.0, 0.0)
    (dx, dy), n = cnt.most_common(1)[0]
    return (dx, dy, n, cnt.most_common(3))


JS_GET = """
const MIL=1/0.0254; function NM(n){ if(n==null) return null; if(typeof n==='string') return n; if(n.name!==undefined) return String(n.name); return String(n); }
const L=await eda.pcb_PrimitiveLine.getAll(); const o=[];
for(const l of L){ o.push([l.getState_PrimitiveId(), NM(l.getState_Net()), l.getState_Layer(),
  +(l.getState_StartX()/MIL).toFixed(4), +(l.getState_StartY()/MIL).toFixed(4),
  +(l.getState_EndX()/MIL).toFixed(4), +(l.getState_EndY()/MIL).toFixed(4),
  +(l.getState_LineWidth()/MIL).toFixed(4)]); }
return JSON.stringify(o);
"""


def main():
    ses = sys.argv[1] if len(sys.argv) > 1 else r"D:\360Downloads\tourbox\pcb-layout\tools\tourbox4.ses"
    apply = "--apply" in sys.argv
    segs = parse_ses(ses)
    per_net = collections.defaultdict(list)
    for s in segs:
        per_net[s[0]].append(s[3:7] + [s[2]])
    net_min = {n: min(x[4] for x in v) for n, v in per_net.items()}
    net_max = {n: max(x[4] for x in v) for n, v in per_net.items()}
    print("SES %s: 段 %d, 网 %d" % (ses, len(segs), len(per_net)))
    print("SES 线宽分布:", collections.Counter(round(s[2] / 0.0254, 4) for s in segs).most_common())
    print("多宽度网:", [(n, sorted(set(round(x[4] / 0.0254, 4) for x in v))) for n, v in per_net.items()
                     if len(set(round(x[4], 6) for x in v)) > 1][:10])

    lines = json.loads(q(JS_GET))
    print("板上走线 %d 条，当前线宽分布: %s" % (len(lines), collections.Counter(L[7] for L in lines).most_common()))
    off = estimate_offset(lines, segs)
    print("平移估计 (dx,dy) = %s" % (off,))
    dx, dy = off[0], off[1]

    # 用 numpy 暴力最近匹配（按 网+层 分组，规模小）
    idx = collections.defaultdict(list)
    for i, s in enumerate(segs):
        idx[(s[0], s[1])].append(i)
    plan, unmatched, nomatch_net = [], 0, 0
    for L in lines:
        cand = idx.get((L[1], L[2]), [])
        best, bd = None, 1e9
        for i in cand:
            s = segs[i]
            d1 = abs((L[3] - dx) - s[3]) + abs((L[4] - dy) - s[4])
            d2 = abs((L[5] - dx) - s[5]) + abs((L[6] - dy) - s[6])
            d = min(d1 + d2, abs((L[3] - dx) - s[5]) + abs((L[4] - dy) - s[6]) +
                    abs((L[5] - dx) - s[3]) + abs((L[6] - dy) - s[4]))
            if d < bd:
                bd, best = d, i
        if best is not None and bd < 0.05:
            w_new = round(segs[best][2], 4)
        else:
            if L[1] in net_min:
                w_new = round(net_min[L[1]], 4)
                nomatch_net += 1
            else:
                w_new = None
                unmatched += 1
        if w_new is not None and abs(w_new - L[7]) > 0.0005:
            plan.append((L[0], L[1], L[7], w_new))
    print("几何匹配成功 %d / %d ；未匹配改用该网最小宽度 %d ；完全无对应 %d"
          % (len(lines) - unmatched - nomatch_net, len(lines), nomatch_net, unmatched))
    print("需要改线宽的走线数 = %d" % len(plan))
    print("改后线宽分布:", collections.Counter(p[3] for p in plan).most_common(10))
    chgs = collections.Counter((p[1], p[2], p[3]) for p in plan)
    print("按网的变化（前 20）:")
    for (net, a, b), n in chgs.most_common(20):
        print("   %-12s %s -> %s   (%d 条)" % (net, a, b, n))

    if not apply:
        print("\n[dry-run] 未写入板子；加 --apply 才应用")
        return
    done = 0
    for i in range(0, len(plan), 40):
        chunk = plan[i:i + 40]
        arr = json.dumps([[c[0], c[3]] for c in chunk])
        js = ("const a=%s; let ok=0; const L=await eda.pcb_PrimitiveLine.getAll(); const m={};"
              " for(const l of L){ m[String(l.getState_PrimitiveId())]=l; }"
              " for(const s of a){ try{ const l=m[s[0]]; if(!l) continue; l.setState_LineWidth(s[1]/0.0254*1.0); await l.done(); ok++; }catch(e){} }"
              " return String(ok);" % arr)
        # 注意：把 mm 转回 mil 需要 *39.37
        js = js.replace("s[1]/0.0254*1.0", "s[1]/0.0254")
        r = q(js)
        try:
            done += int(r)
        except Exception:
            print("   批次失败:", str(r)[:120])
    print("已应用 %d/%d 条" % (done, len(plan)))


if __name__ == "__main__":
    main()
