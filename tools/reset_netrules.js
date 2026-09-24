const D = eda.pcb_Drc;
const raw = await D.getNetRules();
const before = (JSON.stringify(raw).match(/copilot_router/g) || []).length;

// 备份原始规则到 window，方便回滚
window.__netrules_backup = JSON.stringify(raw);

let cleaned;
if (Array.isArray(raw)) {
  cleaned = raw.map(function(rule){
    const o = {};
    for (const k of Object.keys(rule)) {
      let v = rule[k];
      if (typeof v === "string" && v.indexOf("copilot_router") === 0) v = "default";
      o[k] = v;
    }
    return o;
  });
} else {
  cleaned = raw;
}

let wrote = "skip";
try { await D.overwriteNetRules(cleaned); wrote = "ok"; } catch(e){ wrote = "ERR " + String(e).slice(0,120); }

const after = await D.getNetRules();
const s2 = JSON.stringify(after);
return JSON.stringify({
  before: before,
  wrote: wrote,
  after_copilot: (s2.match(/copilot_router/g)||[]).length,
  rules_count: Array.isArray(after) ? after.length : -1,
  sample: s2.slice(0,420)
});
