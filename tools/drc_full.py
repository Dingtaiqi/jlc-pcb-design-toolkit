#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drc_full.py -- EasyEDA Pro 全量 DRC 违规导出器（只读，经本地桥接执行）

用法:
    python drc_full.py [--json out.json] [--limit N] [--passes K] [--strict]
                       [--bridge URL] [--timeout SEC] [--diff OLD.json] [--quiet]

要点:
  * 走 `eda.pcb_Drc.check(strict, userInterface=false, includeVerboseError=true)`。
    实测该调用返回的是**全量**列表（每个 group 的 count == 实际条目数），不是抽样。
    多次调用做并集 + 按“图元对+坐标”去重，规避 EasyEDA 在规则配置切换瞬间
    可能出现的重复上报（实测见过 2722 = 2x1361 的一次重复）。
  * 单位（已实测标定）：1 DRC internal unit = 0.254 mm = 10 mil
        mm = raw * 0.254      mil = raw * 10
    对 pos.x/pos.y 与 explanation.errData.minDistance/clearance 均成立，
    并用 explanation.param 里的 "5.6mil" / "0.006mm" 文本做交叉校验。
  * 只读：仅调用 check/getAll/getState_*/getCopperRegion/getNetRules/
    getCurrentRuleConfigurationName。

退出码: 0 成功; 2 DRC/桥接不可用; 3 输出文件写入失败
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BRIDGE = os.environ.get("EDA_BRIDGE", "http://localhost:49620/execute")
DEFAULT_TIMEOUT = float(os.environ.get("DRC_TIMEOUT", "900"))
UNIT_MM = 0.254           # 1 DRC unit -> mm
MIL_PER_UNIT = 10.0       # 1 DRC unit -> mil
PCB_UUID = "a13a9a0e834c40d3a24ee99ae8ff4e1c"

API_SIG = ("eda.pcb_Drc.check(strict={strict}, userInterface=false, "
           "includeVerboseError=true)")


class DrcUnavailable(RuntimeError):
    """DRC 路径不可用（桥接断开 / API 不存在 / DRC 引擎报错）。"""


# --------------------------------------------------------------------------
# 桥接
# --------------------------------------------------------------------------
def bridge(code: str, url: str = DEFAULT_BRIDGE, timeout: float = DEFAULT_TIMEOUT):
    """POST 一段 JS 到桥接，返回 response.result（原样，通常是 JSON 字符串）。"""
    body = json.dumps({"code": code}).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise DrcUnavailable("桥接 HTTP %s: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise DrcUnavailable(
            "桥接不可达 %s (%s)。请先启动: node C:/Users/yinsh/.dsh/skills/"
            "easyeda-api/scripts/bridge-server.mjs 并等待 ~80 秒扩展重连。" % (url, e))
    except Exception as e:  # timeout 等
        raise DrcUnavailable("桥接调用异常: %r" % (e,))
    try:
        env = json.loads(raw)
    except Exception:
        raise DrcUnavailable("桥接返回不是 JSON: %s" % raw[:300])
    if not isinstance(env, dict) or not env.get("success"):
        raise DrcUnavailable("桥接返回失败: %s" % json.dumps(env, ensure_ascii=False)[:400])
    return env.get("result")


def bridge_json(code: str, url: str = DEFAULT_BRIDGE, timeout: float = DEFAULT_TIMEOUT):
    res = bridge(code, url, timeout)
    if res is None:
        return None
    if isinstance(res, (dict, list)):
        return res
    try:
        return json.loads(res)
    except Exception:
        raise DrcUnavailable("桥接 result 不是 JSON: %s" % str(res)[:300])


# --------------------------------------------------------------------------
# 页内 JS
# --------------------------------------------------------------------------
PROBE_JS = r"""
const out = {ok:true};
try { out.has_check = (typeof eda.pcb_Drc.check === 'function'); } catch(e) { out.has_check = false; out.err = String(e && e.message ? e.message : e); }
try { out.proto = Object.getOwnPropertyNames(Object.getPrototypeOf(eda.pcb_Drc)); } catch(e) {}
try { out.realtime_status = await eda.pcb_Drc.getRealTimeDrcStatus(); } catch(e) { out.realtime_err = String(e && e.message ? e.message : e); }
try { out.check_src = String(eda.pcb_Drc.check).slice(0, 220); } catch(e) {}
try { out.rule_config_name = await eda.pcb_Drc.getCurrentRuleConfigurationName(); } catch(e) { out.rule_config_err = String(e && e.message ? e.message : e); }
return JSON.stringify(out);
"""

# 每次 pass：跑 DRC，把结果并入页内并集缓存 globalThis.__drcExport
PASS_JS = r"""
const VERSION = 2;
if (!globalThis.__drcExport || globalThis.__drcExport.v !== VERSION || globalThis.__drcExport.recovered) {
  globalThis.__drcExport = { v: VERSION, pass: 0, list: [], idx: {}, pairs: {}, meta: [] };
}
const U = globalThis.__drcExport;
if (!U.pairs) U.pairs = {};
if (!U.idx) U.idx = {};
const passIdx = U.pass;
async function _fp() {
  const L = await eda.pcb_PrimitiveLine.getAll();
  let sx = 0;
  L.forEach(function (l) { sx += l.getState_StartX() + l.getState_StartY() + l.getState_EndX() + l.getState_EndY(); });
  const V = await eda.pcb_PrimitiveVia.getAll();
  let vx = 0;
  V.forEach(function (v) { vx += v.getState_X() + v.getState_Y(); });
  const P = await eda.pcb_PrimitivePour.getAll();
  const pf = [];
  for (let i = 0; i < P.length; i++) {
    let rgn; try { rgn = await P[i].getCopperRegion(); } catch (e) {}
    pf.push(!!(rgn !== undefined && rgn !== null));
  }
  let C = [];
  try { C = await eda.pcb_PrimitiveComponent.getAll(); } catch (e) {}
  return { n_lines: L.length, n_vias: V.length, n_pours: P.length,
           pours_filled: pf.filter(Boolean).length, n_comps: C.length,
           sum_line: Math.round(sx * 1000) / 1000, sum_via: Math.round(vx * 1000) / 1000 };
}
let rcName = null, nrCount = null, nrResidue = null;
try { rcName = await eda.pcb_Drc.getCurrentRuleConfigurationName(); } catch (e) { rcName = 'ERR:' + String(e && e.message ? e.message : e); }
try {
  const nr = await eda.pcb_Drc.getNetRules();
  nrCount = (nr && typeof nr === 'object') ? Object.keys(nr).length : null;
  nrResidue = (JSON.stringify(nr || {}).match(/copilot_router/g) || []).length;
} catch (e) {}
const rc = { name: rcName, net_rules: nrCount, copilot_router_residue: nrResidue };

const t0 = Date.now();
let r;
try { r = await eda.pcb_Drc.check(__STRICT__, false, true); }
catch (e) { return JSON.stringify({ __err: String(e && e.message ? e.message : e), pass: passIdx }); }
if (!r) return JSON.stringify({ __err: 'check() 返回空值 (null/undefined)', pass: passIdx });
const groups = Array.isArray(r) ? r : [r];
let raw = 0, declared = 0;
const bySub = {}, byRule = {};
groups.forEach(function (g) {
  declared += Number(g && g.count) || 0;
  ((g && g.list) || []).forEach(function (sub) {
    (((sub) && sub.list) || []).forEach(function (it) {
      raw++;
      const subKey = (g.name || '?') + ' / ' + ((sub && sub.name) || '?');
      bySub[subKey] = (bySub[subKey] || 0) + 1;
      const ed = (it.explanation || {}).errData || {};
      const pr = (it.explanation || {}).param || {};
      const ids = (it.objs || []).map(String).sort();
      const p = it.pos || {};
      const px = Math.round((Number(p.x) || 0) * 1000) / 1000;
      const py = Math.round((Number(p.y) || 0) * 1000) / 1000;
      const s1 = ((it.obj1 || {}).suffix) || '';
      const s2 = ((it.obj2 || {}).suffix) || '';
      const layer = String(it.layer || '');
      const cat = String(it.errorType || '');
      const typ = String(it.errorObjType || '');
      const rn = String(it.ruleName || '');
      byRule[rn || '(none)'] = (byRule[rn || '(none)'] || 0) + 1;
      const pairKey = [cat, typ, ids.join(','), s1, s2, layer].join('|');
      U.pairs[pairKey] = 1;
      const pointKey = pairKey + '|' + px + '|' + py;
      let rec = U.idx[pointKey] ? U.list[U.idx[pointKey]] : null;
      if (!rec) {
        rec = {
          c: cat, s: typ, grp: String((sub && sub.name) || ''),
          t1: String((it.obj1 || {}).typeName || ''), t2: String((it.obj2 || {}).typeName || ''),
          s1: s1, s2: s2, ids: ids, id1: ids[0] || '', id2: ids[1] || '',
          x: px, y: py, L: layer,
          md: (typeof ed.minDistance === 'number') ? ed.minDistance : null,
          cl: (typeof ed.clearance === 'number') ? ed.clearance : null,
          pm: String(pr.minDistance || ''), ps: String(pr.shouldBe || ''),
          rn: rn, gi: String(it.globalIndex || ed.globalIndex || ''),
          net: String(it.net || ed.net || ''), isFree: !!it.isFree,
          n: 0, passes: [], rules: {}
        };
        U.idx[pointKey] = U.list.length;
        U.list.push(rec);
      }
      rec.n++;
      if (rec.passes.indexOf(passIdx) < 0) rec.passes.push(passIdx);
      rec.rules[rn || '(none)'] = (rec.rules[rn || '(none)'] || 0) + 1;
    });
  });
});
U.pass++;
const fp = await _fp();
const meta = { pass: passIdx, ms: Date.now() - t0, raw: raw, declared: declared,
               by_sub: bySub, by_rule: byRule, fingerprint: fp, rule_config: rc,
               unique_points: U.list.length, unique_pairs: Object.keys(U.pairs).length };
U.meta.push(meta);
return JSON.stringify(meta);
"""

FETCH_JS = r"""
const U = globalThis.__drcExport;
if (!U) return JSON.stringify({ __err: 'no page cache (globalThis.__drcExport)' });
const a = __A__, b = __B__;
return JSON.stringify({ total: U.list.length, pairs: Object.keys(U.pairs || {}).length,
                        meta: U.meta, slice: U.list.slice(a, b) });
"""

RESET_JS = r"""
try { globalThis.__drcExport = null; } catch (e) {}
return JSON.stringify({ ok: true, reset: true });
"""

# --recover: 把之前会话遗留在页面里的 DRC 结果缓存（__p0list / __drcFull / __p0 …）
# 规范化成同样的 __drcExport 结构，用于抢救“板子已被改动、无法重跑”的历史快照。
RECOVER_LIST_JS = r"""
const out = { caches: {} };
function n(name) { try { const v = globalThis[name]; if (Array.isArray(v)) return v.length; if (v && typeof v === 'object') return Object.keys(v).length; } catch (e) {} return null; }
['__p0list', '__p1list', '__drcFull', '__p0', '__p1', '__drcU'].forEach(function (k) { const c = n(k); if (c !== null) out.caches[k] = c; });
return JSON.stringify(out);
"""

RECOVER_BUILD_JS = r"""
const NAME = '__NAME__';
let src = null;
try {
  const v = globalThis[NAME];
  if (Array.isArray(v)) src = v;
  else if (v && typeof v === 'object') src = Object.keys(v).map(function (k) { return v[k]; });
} catch (e) {}
if (!src) return JSON.stringify({ __err: 'cache ' + NAME + ' 不存在' });
const U = { v: 2, pass: 0, list: [], idx: {}, pairs: {}, meta: [], recovered: true, source: NAME };
let raw = 0;
const bySub = {}, byRule = {};
src.forEach(function (x) {
  if (!x) return;
  const it = x.it ? x.it : (x.errorType ? x : null);
  if (!it) return;
  raw++;
  const gName = String(x.g || it.errorType || '?');
  const sName = String(x.s || it.errorObjType || '?');
  const subKey = gName + ' / ' + sName;
  bySub[subKey] = (bySub[subKey] || 0) + 1;
  const ed = (it.explanation || {}).errData || {};
  const pr = (it.explanation || {}).param || {};
  const ids = (it.objs || []).map(String).sort();
  const p = it.pos || {};
  const px = Math.round((Number(p.x) || 0) * 1000) / 1000;
  const py = Math.round((Number(p.y) || 0) * 1000) / 1000;
  const s1 = ((it.obj1 || {}).suffix) || '';
  const s2 = ((it.obj2 || {}).suffix) || '';
  const layer = String(it.layer || '');
  const cat = String(it.errorType || '');
  const typ = String(it.errorObjType || '');
  const rn = String(it.ruleName || '');
  byRule[rn || '(none)'] = (byRule[rn || '(none)'] || 0) + 1;
  const pairKey = [cat, typ, ids.join(','), s1, s2, layer].join('|');
  U.pairs[pairKey] = 1;
  const pointKey = pairKey + '|' + px + '|' + py;
  let rec = U.idx[pointKey] ? U.list[U.idx[pointKey]] : null;
  if (!rec) {
    rec = {
      c: cat, s: typ, grp: sName,
      t1: String((it.obj1 || {}).typeName || ''), t2: String((it.obj2 || {}).typeName || ''),
      s1: s1, s2: s2, ids: ids, id1: ids[0] || '', id2: ids[1] || '',
      x: px, y: py, L: layer,
      md: (typeof ed.minDistance === 'number') ? ed.minDistance : null,
      cl: (typeof ed.clearance === 'number') ? ed.clearance : null,
      pm: String(pr.minDistance || ''), ps: String(pr.shouldBe || ''),
      rn: rn, gi: String(it.globalIndex || ed.globalIndex || ''),
      net: String(it.net || ed.net || ''), isFree: !!it.isFree,
      n: 0, passes: [0], rules: {}
    };
    U.idx[pointKey] = U.list.length;
    U.list.push(rec);
  }
  rec.n++;
  rec.rules[rn || '(none)'] = (rec.rules[rn || '(none)'] || 0) + 1;
});
U.meta.push({ pass: 0, ms: 0, raw: raw, declared: raw, by_sub: bySub, by_rule: byRule,
              fingerprint: { recovered: true, source: NAME },
              rule_config: { name: null, net_rules: null, copilot_router_residue: null },
              unique_points: U.list.length, unique_pairs: Object.keys(U.pairs).length,
              recovered: true, source: NAME });
globalThis.__drcExport = U;
return JSON.stringify({ ok: true, source: NAME, raw: raw, unique_points: U.list.length,
                        unique_pairs: Object.keys(U.pairs).length });
"""


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
NET_RE = re.compile(r"^\s*\(([^)]*)\)\s*:")


def net_of(suffix: str, fallback: str = "") -> str:
    m = NET_RE.match(suffix or "")
    return m.group(1) if m else (fallback or "")


def parse_mil(text: str):
    """把 '>= 6mil' / '0.152mm' 解析成 mil。"""
    if not text:
        return None
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(mil|mm)", text, re.I)
    if not m:
        return None
    v = float(m.group(1))
    return v if m.group(2).lower() == "mil" else v / 0.0254


def run_passes(passes, strict, url, timeout, quiet=False, retries=2):
    """多次采样。单次失败(常见: EasyEDA 'Error: undefined')会重试；仍失败则跳过该 pass，
    只要还有成功的 pass 就继续导出（并在报告里标注）。"""
    metas, errors = [], []
    for i in range(passes):
        for attempt in range(retries + 1):
            try:
                meta = bridge_json(PASS_JS.replace("__STRICT__", "true" if strict else "false"),
                                   url, timeout)
                if not isinstance(meta, dict):
                    raise DrcUnavailable("返回异常: %r" % (meta,))
                if meta.get("__err"):
                    raise DrcUnavailable(str(meta["__err"]))
                metas.append(meta)
                if not quiet:
                    sys.stderr.write(
                        "  pass %d: %d 条 (declared=%d%s) %.1fs  并集唯一=%d\n" % (
                            i, meta.get("raw", -1), meta.get("declared", -1),
                            " OK" if meta.get("raw") == meta.get("declared") else " !!不一致",
                            (meta.get("ms") or 0) / 1000.0, meta.get("unique_points", -1)))
                break
            except DrcUnavailable as e:
                if attempt < retries:
                    if not quiet:
                        sys.stderr.write("  pass %d 失败(%s), 重试 %d/%d ...\n"
                                         % (i, e, attempt + 1, retries))
                    time.sleep(2.0 + 2.0 * attempt)
                    continue
                errors.append("pass %d: %s" % (i, e))
                if not quiet:
                    sys.stderr.write("  pass %d 放弃: %s\n" % (i, e))
    return metas, errors


def fetch_union(url, timeout, chunk=150, quiet=False):
    head = bridge_json(FETCH_JS.replace("__A__", "0").replace("__B__", "0"),
                       url, timeout)
    if not isinstance(head, dict) or head.get("__err"):
        raise DrcUnavailable("读取页内并集失败: %r" % (head,))
    total = int(head.get("total") or 0)
    records = []
    a = 0
    while a < total:
        b = min(a + chunk, total)
        part = bridge_json(FETCH_JS.replace("__A__", str(a)).replace("__B__", str(b)),
                           url, timeout)
        if not isinstance(part, dict) or part.get("__err"):
            raise DrcUnavailable("分块读取失败 @%d-%d: %r" % (a, b, part))
        sl = part.get("slice") or []
        records.extend(sl)
        a = b
    if len(records) != total:
        raise DrcUnavailable("分块读取不完整: 期望 %d 实际 %d" % (total, len(records)))
    if not quiet:
        sys.stderr.write("  拉取全量记录: %d 条 (分块 %d)\n" % (total, chunk))
    return records, head.get("meta") or []


def enrich(rec):
    """补全单位换算/派生字段。"""
    out = {
        "category": rec.get("c", ""),
        "subcategory": rec.get("s", ""),
        "group": rec.get("grp", ""),
        "net1": net_of(rec.get("s1", ""), rec.get("net", "")),
        "net2": net_of(rec.get("s2", ""), ""),
        "obj1": {"id": rec.get("id1", ""), "suffix": rec.get("s1", ""),
                 "type": rec.get("t1", "")},
        "obj2": {"id": rec.get("id2", ""), "suffix": rec.get("s2", ""),
                 "type": rec.get("t2", "")},
        "layer": rec.get("L", ""),
        "rule": rec.get("rn", ""),
        "global_index": rec.get("gi", ""),
        "param_minDistance": rec.get("pm", ""),
        "param_shouldBe": rec.get("ps", ""),
        "passes": rec.get("passes", []),
        "copies_seen": rec.get("n", 0),
        "rules_seen": rec.get("rules", {}),
    }
    md = rec.get("md")
    out["distance_mil"] = round(md * MIL_PER_UNIT, 4) if isinstance(md, (int, float)) else None
    out["distance_mm"] = round(md * UNIT_MM, 5) if isinstance(md, (int, float)) else None
    # 要求值优先取 explanation.param.shouldBe (如 ">= 6mil" / ">= 0.152mm")，
    # 退化到 errData.clearance (raw unit)。注意 param.minDistance 是"实测距离"不是要求值。
    req = parse_mil(rec.get("ps", ""))
    if req is None:
        req = parse_mil(rec.get("pm", "")) if not rec.get("ps") else None
    if req is None:
        cl = rec.get("cl")
        req = cl * MIL_PER_UNIT if isinstance(cl, (int, float)) else None
    out["required_mil"] = round(req, 4) if req is not None else None
    out["required_mm"] = round(req * 0.0254, 5) if req is not None else None
    if out["distance_mil"] is not None and req is not None:
        out["deficit_mil"] = round(max(0.0, req - out["distance_mil"]), 4)
    else:
        out["deficit_mil"] = None
    x, y = rec.get("x"), rec.get("y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        out["pos_raw"] = [x, y]
        out["pos_mil"] = [round(x * MIL_PER_UNIT, 4), round(y * MIL_PER_UNIT, 4)]
        out["pos_mm"] = [round(x * UNIT_MM, 5), round(y * UNIT_MM, 5)]
    else:
        out["pos_raw"] = out["pos_mil"] = out["pos_mm"] = None
    ida = [out["obj1"]["id"]] if out["obj1"]["id"] else []
    idb = [out["obj2"]["id"]] if out["obj2"]["id"] else []
    out["sig_pair"] = "|".join([out["category"], out["subcategory"],
                                ",".join(sorted(ida + idb)),
                                out["obj1"]["suffix"], out["obj2"]["suffix"], out["layer"]])
    out["sig_point"] = out["sig_pair"] + ("|%.3f|%.3f" % (rec.get("x") or 0,
                                                          rec.get("y") or 0))
    return out


def stats(items):
    by_cat = collections.Counter()
    by_sub = collections.Counter()
    by_layer = collections.Counter()
    by_rule = collections.Counter()
    by_net = collections.Counter()
    for it in items:
        by_cat[it["category"]] += 1
        by_sub[(it["category"], it["subcategory"])] += 1
        by_layer[it["layer"] or "(none)"] += 1
        by_rule[it["rule"] or "(none)"] += 1
        for k in ("net1", "net2"):
            v = it.get(k)
            if v:
                by_net[v] += 1
    return by_cat, by_sub, by_layer, by_rule, by_net


def short(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "~"


# --------------------------------------------------------------------------
# 文本报告
# --------------------------------------------------------------------------
def render_text(payload, limit, probe, stream):
    items = payload["violations"]
    t = payload["totals"]
    w = 100

    def p(s=""):
        stream.write(s + "\n")

    p("=" * w)
    p("EasyEDA Pro 全量 DRC 导出 -- tourbox eltie  PCB %s" % PCB_UUID)
    p("=" * w)
    p("生成时间    : %s" % payload["generated_at"])
    p("API         : %s" % payload["board"]["api"])
    p("桥接        : %s" % payload["board"]["bridge"])
    rc = payload["rule_config"] or {}
    p("规则配置    : %s  (net rules=%s, copilot_router 残留=%s)" % (
        rc.get("name"), rc.get("net_rules"), rc.get("copilot_router_residue")))
    fp = payload["fingerprint"] or {}
    if fp.get("recovered"):
        p("板子指纹    : (抢救快照, 无当时指纹; 缓存来源 %s)" % fp.get("source"))
    else:
        p("板子指纹    : %s 线 / %s 过孔 / %s 铺铜(已填充 %s) / %s 元件  (sum_line=%s)" % (
            fp.get("n_lines"), fp.get("n_vias"), fp.get("n_pours"),
            fp.get("pours_filled"), fp.get("n_comps"), fp.get("sum_line")))
    p("实时 DRC    : %s" % ("可用" if probe.get("realtime_status") else
                            "不可用 (startRealTimeDrc/getRealTimeDrcStatus 是空实现, 恒返回 false)"))
    p("-" * w)
    p("原始 per-pass 计数（未去重）:")
    for m in payload["passes"]:
        p("   pass %d : %5d 条   declared=%5d %s  %.1fs  并集唯一点(累计)=%d" % (
            m.get("pass"), m.get("raw", -1), m.get("declared", -1),
            "一致" if m.get("raw") == m.get("declared") else "不一致!!",
            (m.get("ms") or 0) / 1000.0, m.get("unique_points", -1)))
    p("")
    p(">>> 唯一违规点总数 : %d      唯一图元对 : %d    (合并 %d 次采样并去重)" % (
        t["unique_points"], t["unique_pairs"], len(payload["passes"])))
    p(">>> 分类总数       : %s" % ", ".join(
        "%s=%d" % (k, v) for k, v in t["by_category"].items()))
    p("-" * w)
    p("按 类别 -> 子类 的精确计数:")
    for cat, n in collections.Counter(t["by_category"]).most_common():
        p("  %-18s %6d" % (cat, n))
        for key, m in collections.Counter(t["by_sub"]).most_common():
            c, _, s = key.partition(" / ")
            if c == cat:
                p("      %-34s %6d" % (short(s, 34), m))
    if t["by_rule"]:
        p("按 DRC 规则名 (ruleName) 计数:")
        for r, n in collections.Counter(t["by_rule"]).most_common(12):
            p("      %-52s %6d" % (short(r, 52), n))
    p("-" * w)
    p("明细（每子类最多 %d 条；--limit 0 = 全部 %d 条）:" % (limit, len(items)))
    by_sub_items = collections.defaultdict(list)
    for it in items:
        by_sub_items["%s / %s" % (it["category"], it["subcategory"])].append(it)
    for key, n in collections.Counter(t["by_sub"]).most_common():
        rows = by_sub_items[key]
        p("")
        p("[%s]  %d 条" % (key, n))
        p("   #  距离/要求             层         对象1                    对象2                    坐标(mm)           id1 / id2")
        for i, it in enumerate(rows[:limit] if limit else rows, 1):
            d, req = it["distance_mil"], it["required_mil"]
            dd = ("%.2fmil" % d) if d is not None else "-"
            rr = (">=%.2fmil" % req) if req is not None else "-"
            pos = it["pos_mm"]
            pos_s = "(%.2f,%.2f)" % (pos[0], pos[1]) if pos else "-"
            p("  %3d  %-10s %-10s %-24s %-24s %-17s %s" % (
                i, dd[:10], rr[:10], short(it["obj1"]["suffix"], 24),
                short(it["obj2"]["suffix"], 24), pos_s,
                it["obj1"]["id"] + (" / " + it["obj2"]["id"] if it["obj2"]["id"] else "")))
        if limit and n > limit:
            p("      ... 还有 %d 条 (--limit 0 看全部, 或 --json 导出全量)" % (n - limit))
    p("")
    p("-" * w)
    v = payload["validation"]
    p("自检 / 覆盖率:")
    p("  * DRC 是否全量返回 : %s" % ("是 (每个 group count == 实际条目数, 逐 pass 校验)"
                                   if v["declared_eq_items"] else "否 !! 见 per-pass 计数"))
    p("  * 采样/去重        : %d 次采样并集; 折叠重复上报 %d 条" % (
        len(payload["passes"]), v["duplicates_collapsed"]))
    p("  * 单位标定         : 1 unit = %.3f mm = %.0f mil; param 文本与 raw 交叉校验不一致 %d 条" % (
        UNIT_MM, MIL_PER_UNIT, v["unit_mismatch"]))
    p("  * 坐标缺失         : %d 条     图元 id 缺失 : %d 条" % (v["missing_pos"], v["missing_ids"]))
    p("  * 覆盖率           : %.2f%% (DRC 引擎返回的全部条目均已导出; 无抽样、无截断)"
      % (100.0 if v["declared_eq_items"] else 0.0))
    if v["warnings"]:
        p("  * 警告:")
        for x in v["warnings"]:
            p("      - %s" % x)
    p("=" * w)


# --------------------------------------------------------------------------
# --diff 模式
# --------------------------------------------------------------------------
def do_diff(old_path, payload, stream, top=20):
    try:
        with open(old_path, "r", encoding="utf-8") as f:
            old = json.load(f)
    except Exception as e:
        stream.write("无法读取旧快照 %s: %r\n" % (old_path, e))
        return
    old_items = old.get("violations", [])
    old_map = {it.get("sig_pair", ""): it for it in old_items}
    new_map = {it.get("sig_pair", ""): it for it in payload["violations"]}
    fixed = [k for k in old_map if k not in new_map]
    newv = [k for k in new_map if k not in old_map]
    common = [k for k in new_map if k in old_map]
    w = 100
    stream.write("=" * w + "\n")
    stream.write("DRC 快照对比: %s  ->  now\n" % old_path)
    stream.write("  before: %d 点 (%s)    after: %d 点 (%s)\n" % (
        len(old_items), old.get("generated_at"), len(payload["violations"]),
        payload["generated_at"]))
    stream.write("  修复(消失): %d    新增: %d    仍在: %d\n" % (len(fixed), len(newv), len(common)))

    def sub_counter(keys, src):
        c = collections.Counter()
        for k in keys:
            it = src[k]
            c["%s / %s" % (it.get("category"), it.get("subcategory"))] += 1
        return c

    for title, keys, src in (("修复(消失) 分类", fixed, old_map), ("新增 分类", newv, new_map)):
        stream.write("-" * w + "\n%s:\n" % title)
        for key, n in sub_counter(keys, src).most_common(top):
            stream.write("   %-40s %5d\n" % (short(key, 40), n))
    if common:
        stream.write("-" * w + "\n仍在的违规（距离变化 top%d）:\n" % top)
        deltas = []
        for k in common:
            a, b = old_map[k], new_map[k]
            da, db = a.get("distance_mil"), b.get("distance_mil")
            if da is not None and db is not None and abs(da - db) > 0.05:
                deltas.append((db - da, a, b))
        deltas.sort(key=lambda x: -abs(x[0]))
        for d, a, b in deltas[:top]:
            stream.write("   %+6.2fmil  %-18s %-20s %s <-> %s\n" % (
                d, a.get("category"), short(a.get("subcategory"), 20),
                short(a["obj1"]["suffix"], 20), short(a["obj2"]["suffix"], 20)))
        if not deltas:
            stream.write("   (几何距离无显著变化)\n")
    stream.write("=" * w + "\n")


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="EasyEDA Pro 全量 DRC 导出器（只读）")
    ap.add_argument("--json", metavar="OUT", help="输出结构化全量 JSON")
    ap.add_argument("--limit", type=int, default=25,
                    help="明细里每个子类最多打印多少条 (默认 25, 0=全部)")
    ap.add_argument("--passes", type=int, default=3, help="DRC 采样次数并去重 (默认 3)")
    ap.add_argument("--strict", action="store_true",
                    help="用 check(strict=true)（实测与 false 结果一致）")
    ap.add_argument("--bridge", default=DEFAULT_BRIDGE, help="桥接 URL")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="单次桥接超时秒")
    ap.add_argument("--chunk", type=int, default=150, help="分块拉取条数 (默认 150)")
    ap.add_argument("--diff", metavar="OLD.json", help="与旧快照对比")
    ap.add_argument("--recover", nargs="?", const="auto", metavar="CACHE",
                    help="不跑新 DRC，改为抢救页面里遗留的历史结果缓存 "
                         "(__p0list/__drcFull/__p0…)，用于板子已被改动的情况")
    ap.add_argument("--quiet", action="store_true", help="不打印进度")
    args = ap.parse_args(argv)

    t_start = time.time()
    try:  # 控制台编码兜底
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    # 1) 探测 API 是否可用
    try:
        probe = bridge_json(PROBE_JS, args.bridge, min(args.timeout, 120))
    except DrcUnavailable as e:
        print("DRC API 不可用: %s" % e, file=sys.stderr)
        return 2
    if not isinstance(probe, dict) or not probe.get("has_check"):
        print("DRC API 不可用: eda.pcb_Drc.check 不存在或不可调用 (%s)"
              % json.dumps(probe, ensure_ascii=False)[:300], file=sys.stderr)
        return 2
    if not args.quiet:
        sys.stderr.write("API 探测: check 可用; 规则配置=%s; 实时DRC=%s\n" % (
            probe.get("rule_config_name"), probe.get("realtime_status")))

    # 2) 多次采样 + 并集去重（或 --recover 抢救历史页内缓存）
    recovered = None
    pass_errors = []
    if args.recover:
        try:
            avail = bridge_json(RECOVER_LIST_JS, args.bridge, min(args.timeout, 120))
            caches = (avail or {}).get("caches", {}) if isinstance(avail, dict) else {}
            if not args.quiet:
                sys.stderr.write("可用页内缓存: %s\n" % json.dumps(caches, ensure_ascii=False))
            name = args.recover
            if name == "auto":
                for cand in ("__p0list", "__p1list", "__drcFull", "__p0", "__p1"):
                    if cand in caches:
                        name = cand
                        break
                else:
                    print("DRC API 不可用(无法抢救): 页面里没有可用的历史缓存, 现有 %s"
                          % (caches,), file=sys.stderr)
                    return 2
            r = bridge_json(RECOVER_BUILD_JS.replace("__NAME__", name), args.bridge, args.timeout)
            if not isinstance(r, dict) or r.get("__err"):
                print("DRC API 不可用(恢复失败): %r" % (r,), file=sys.stderr)
                return 2
            recovered = name
            if not args.quiet:
                sys.stderr.write("已恢复缓存 %s: 原始 %d 条 -> 唯一 %d 点 / %d 对\n" % (
                    name, r.get("raw", -1), r.get("unique_points", -1),
                    r.get("unique_pairs", -1)))
            raw_records, page_metas = fetch_union(args.bridge, args.timeout, args.chunk, args.quiet)
        except DrcUnavailable as e:
            print("DRC API 不可用(恢复失败): %s" % e, file=sys.stderr)
            return 2
    else:
        try:
            bridge_json(RESET_JS, args.bridge, min(args.timeout, 60))  # 清掉上一次遗留缓存
            page_metas_all, pass_errors = run_passes(
                args.passes, args.strict, args.bridge, args.timeout, args.quiet)
            if not page_metas_all:
                raise DrcUnavailable("所有 pass 均失败: %s" % "; ".join(pass_errors))
            raw_records, page_metas = fetch_union(args.bridge, args.timeout, args.chunk, args.quiet)
        except DrcUnavailable as e:
            print("DRC API 不可用: %s" % e, file=sys.stderr)
            return 2

    items = [enrich(r) for r in raw_records]
    items.sort(key=lambda it: (it["category"], it["subcategory"],
                              -(it["deficit_mil"] or 0.0), it["obj1"]["suffix"]))
    by_cat, by_sub, by_layer, by_rule, by_net = stats(items)

    # 3) 自检
    declared_eq = all(m.get("raw") == m.get("declared") for m in page_metas)
    first_raw = (page_metas[0].get("raw") or 0) if page_metas else len(items)
    dup_collapsed = max(0, first_raw - len(items))
    unit_mismatch = 0
    for it in items:
        pm = parse_mil(it["param_minDistance"])
        if pm is not None and it["distance_mil"] is not None:
            if abs(pm - it["distance_mil"]) > 0.06:   # param 文本只有 0.1mil 精度
                unit_mismatch += 1
    missing_pos = sum(1 for it in items if not it["pos_mm"])
    missing_ids = sum(1 for it in items if not it["obj1"]["id"])
    warnings = []
    raws = [m.get("raw") for m in page_metas]
    if len(set(raws)) > 1:
        warnings.append("per-pass 原始计数不一致 %s -- 板子/规则在采样期间被改动, "
                        "唯一数取并集; 建议在冻结状态下重跑。" % (raws,))
    if pass_errors:
        warnings.append("有 %d 个采样 pass 失败(已重试): %s -- 本次唯一数是成功 pass 的并集。"
                        % (len(pass_errors), "; ".join(pass_errors)))
    if dup_collapsed:
        warnings.append("检测到 %d 条重复上报（同一图元对/坐标被多次计入, "
                        "多因规则配置切换瞬间同时套用两套规则）, 已按坐标去重。" % dup_collapsed)
    if unit_mismatch:
        warnings.append("有 %d 条 param 文本(mil) 与 raw 换算值不一致, 单位标定可能需复核。"
                        % unit_mismatch)
    if recovered:
        warnings.insert(0, "本快照是抢救自页面遗留缓存 %s，不是本次实测；当时板子的实际状态可能"
                           "与现在不同（元数据里没有当时的板子指纹）。" % recovered)
    rules_seen = collections.Counter()
    for it in items:
        for r in it["rules_seen"]:
            rules_seen[r] += 1
    if len(rules_seen) > 1:
        warnings.append("本次并集里出现多个 ruleName: %s -- 若含 copilot_router_* 说明"
                        "路由器注入的规则仍在生效。" % ", ".join(sorted(rules_seen)))

    payload = {
        "schema": "drc_full/1",
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "board": {
            "project": "tourbox eltie",
            "pcb_uuid": PCB_UUID,
            "api": (("RECOVERED page cache %s (非本次实测)" % recovered) if recovered
                    else API_SIG.format(strict=str(bool(args.strict)).lower())),
            "bridge": args.bridge,
            "strict": bool(args.strict),
            "recovered": recovered,
            "probe": probe,
        },
        "rule_config": (page_metas[0].get("rule_config") if page_metas else {}),
        "fingerprint": (page_metas[-1].get("fingerprint") if page_metas else {}),
        "passes": page_metas,
        "totals": {
            "raw_per_pass": raws,
            "passes_ok": len(page_metas),
            "unique_points": len(items),
            "unique_pairs": len({it["sig_pair"] for it in items}),
            "by_category": dict(by_cat),
            "by_sub": dict(by_sub),
            "by_layer": dict(by_layer),
            "by_rule": dict(by_rule),
            "by_net": dict(by_net),
        },
        "unit_notes": {
            "unit_mm": UNIT_MM, "mil_per_unit": MIL_PER_UNIT,
            "note": "1 DRC internal unit = 0.254 mm = 10 mil; "
                    "mm = raw*0.254, mil = raw*10 (pos 与 minDistance/clearance 同尺度)",
        },
        "validation": {
            "declared_eq_items": declared_eq,
            "duplicates_collapsed": dup_collapsed,
            "unit_mismatch": unit_mismatch,
            "missing_pos": missing_pos,
            "missing_ids": missing_ids,
            "warnings": warnings,
            "pass_errors": pass_errors,
        },
        "violations": items,
    }
    # totals.by_sub 用 "类别 / 子类" 字符串键，便于 JSON 消费
    payload["totals"]["by_sub"] = {"%s / %s" % k: v for k, v in by_sub.items()}

    render_text(payload, args.limit, probe, sys.stdout)
    if args.diff:
        do_diff(args.diff, payload, sys.stdout)
    sys.stdout.write("\n耗时 %.1fs\n" % (time.time() - t_start))

    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            sys.stdout.write("已写出全量 JSON: %s (%d 条违规)\n" % (args.json, len(items)))
        except Exception as e:
            print("写出 JSON 失败: %r" % (e,), file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
