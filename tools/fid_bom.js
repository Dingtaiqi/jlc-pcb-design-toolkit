/* fid_bom.js —— 把 MARK1..6 设为"不加入 BOM"(避免污染物料表), 并报告结果
 * 用法: python pcbai.py run tools/fid_bom.js
 */
const out = { before: [], after: [], errors: [] };
const MIL = 1 / 0.0254;
let C = (await eda.pcb_PrimitiveComponent.getAll()) || [];
const marks = C.filter(c => /^MARK\d*$/i.test(String(c.designator || '')));
for (const m of marks) out.before.push({ d: String(m.designator), addIntoBom: m.addIntoBom, x: +(m.x / MIL).toFixed(1), y: +(m.y / MIL).toFixed(1), layer: m.layer });
for (const m of marks) {
  if (m.addIntoBom === false) continue;
  try { await eda.pcb_PrimitiveComponent.modify(m.primitiveId, { addIntoBom: false }); }
  catch (e) { out.errors.push(String(m.designator) + ': ' + String(e && e.message ? e.message : e).slice(0, 70)); }
}
C = (await eda.pcb_PrimitiveComponent.getAll()) || [];
for (const m of C.filter(c => /^MARK\d*$/i.test(String(c.designator || ''))))
  out.after.push({ d: String(m.designator), addIntoBom: m.addIntoBom });
out.bomCount = C.filter(c => c.addIntoBom !== false).length;
out.total = C.length;
try { await eda.pcb_Document.save(); out.saved = true; } catch (e) { out.saved = 'ERR'; }
return JSON.stringify(out).slice(0, 1500);
