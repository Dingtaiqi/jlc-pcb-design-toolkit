/* rmfid.js —— 删掉我手搓的 6 个"铜点线"(与库 mark 焊盘完全重叠, 多余)
 * 保留: 6 条开窗线(L5/L6, Ø2.0mm) + 3 个 FID_KEEPOUT 禁布区(2.2x2.2mm)
 * 安全: 只删 id 命中 且 层=1/2 且 线宽≈39.37mil(Ø1.0mm) 的线; 任一条不符就跳过它
 * 用法: python pcbai.py run tools/rmfid.js
 */
const MIL = 1 / 0.0254;
const DRY = false;                    // true = 只看不删
const IDS = [
  '6d1996eeccb450ae', '0761587c62caca50',   // (42.5,38.3) L1 / L2
  '066af8190df27c2f', 'a17aa7a9861a661b',   // (62.0,54.8) L1 / L2
  'bb7d1348f1588f3b', '873eaec33c0787d5'    // (35.0,14.3) L1 / L2
];
const out = { dry: DRY, willDelete: [], skipped: [], deleted: null };
const ln = (await eda.pcb_PrimitiveLine.getAll()) || [];
const idOf = l => { try { return l.getState_PrimitiveId ? l.getState_PrimitiveId() : (l.primitiveId || null); } catch (e) { return l.primitiveId || null; } };
const WANT = MIL * 1.0;               // Ø1.0mm = 39.37mil
for (const id of IDS) {
  const l = ln.find(x => idOf(x) === id);
  if (!l) { out.skipped.push({ id: id, why: '不存在' }); continue; }
  const w = +l.lineWidth, layer = +l.layer;
  if ((layer === 1 || layer === 2) && Math.abs(w - WANT) < MIL * 0.15) {
    out.willDelete.push({ id: id, layer: layer, wMil: +w.toFixed(2), x: +(l.startX / MIL).toFixed(2), y: +(l.startY / MIL).toFixed(2) });
  } else {
    out.skipped.push({ id: id, why: '层/线宽不符(保护性跳过)', layer: layer, wMil: +w.toFixed(2) });
  }
}
if (!DRY && out.willDelete.length) {
  try {
    out.deleted = await eda.pcb_PrimitiveLine.delete(out.willDelete.map(o => o.id));
    await eda.pcb_Document.save();
  } catch (e) { out.err = String(e && e.message ? e.message : e).slice(0, 110); }
}
out.lineBefore = ln.length;
out.lineAfter = ((await eda.pcb_PrimitiveLine.getAll()) || []).length;
return JSON.stringify(out).slice(0, 1400);
