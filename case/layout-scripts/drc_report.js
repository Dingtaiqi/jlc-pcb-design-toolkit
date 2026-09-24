// 官方 DRC 全量分解 + net rule 卫生检查（导 SES 之后跑）
const out = {};
// 1) net rules 卫生
try {
  const nr = await eda.pcb_Drc.getNetRules();
  let dirty = 0, total = 0;
  const names = [];
  for (const e of (nr || [])) {
    total++;
    let d = false;
    for (const k of Object.keys(e)) {
      const v = e[k];
      if (typeof v === 'string' && v.indexOf('copilot_router') >= 0) { d = true; dirty++; break; }
    }
    if (d) names.push(e.name);
  }
  out.netRules = { total: total, entriesWithCopilotRouter: dirty, dirtyNets: names.slice(0, 20) };
} catch (e) { out.netRules = { err: String(e && e.message ? e.message : e) }; }

// 2) 官方 DRC
const t0 = Date.now();
let r;
try { r = await eda.pcb_Drc.check(false, false, true); }
catch (e) { out.drc = { err: String(e && e.message ? e.message : e) }; return JSON.stringify(out); }
out.drcMs = Date.now() - t0;
const groups = Array.isArray(r) ? r : [r];
const items = [];
groups.forEach(function (g) {
  ((g && g.list) || []).forEach(function (s) {
    ((s && s.list) || []).forEach(function (it) { items.push(it); });
  });
});
function num(x) { if (typeof x === 'number') return x; if (typeof x === 'string') { const f = parseFloat(x); if (!isNaN(f)) return f; } return null; }
function netOf(s) { if (!s) return null; const m = String(s).match(/^\(([^)]*)\)/); return m ? m[1] : String(s); }

const byType = {}, byLayer = {}, byRule = {}, byRuleType = {};
const hist = { 'lt0.10': 0, '0.10-0.152': 0, '0.152-0.20': 0, '0.20-0.30': 0, '0.30-0.60': 0, 'ge0.60': 0, 'n/a': 0 };
const realByType = {}, realByLayer = {}, realPairs = [];
let realTotal = 0;
const connNets = {};
for (const it of items) {
  const ed = (it.explanation || {}).errData || {};
  byType[it.errorObjType] = (byType[it.errorObjType] || 0) + 1;
  byLayer[it.layer] = (byLayer[it.layer] || 0) + 1;
  byRule[String(it.ruleName)] = (byRule[String(it.ruleName)] || 0) + 1;
  byRuleType[String(it.ruleTypeName)] = (byRuleType[String(it.ruleTypeName)] || 0) + 1;
  if (it.errorType === 'Connection Error') {
    const n = it.net ? String(it.net) : '?';
    connNets[n] = (connNets[n] || 0) + 1;
    continue;
  }
  const md = num(ed.minDistance);
  let k;
  if (md === null) k = 'n/a';
  else if (md < 0.10) k = 'lt0.10';
  else if (md < 0.152) k = '0.10-0.152';
  else if (md < 0.20) k = '0.152-0.20';
  else if (md < 0.30) k = '0.20-0.30';
  else if (md < 0.60) k = '0.30-0.60';
  else k = 'ge0.60';
  hist[k]++;
  if (md !== null && md < 0.152) {
    realTotal++;
    realByType[it.errorObjType] = (realByType[it.errorObjType] || 0) + 1;
    realByLayer[it.layer] = (realByLayer[it.layer] || 0) + 1;
    if (realPairs.length < 60) realPairs.push([it.errorObjType, it.layer, Math.round(md * 10000) / 10000, ed.obj1Suffix, ed.obj2Suffix]);
  }
}
out.drc = { total: items.length, groups: groups.map(function (g) { return [g.name, g.count]; }),
            byType: byType, byLayer: byLayer, byRule: byRule, byRuleType: byRuleType,
            minDistanceHist: hist, realLt0152: realTotal, realByType: realByType, realByLayer: realByLayer,
            connectionNets: connNets, sampleReal: realPairs };
return JSON.stringify(out);
