/* mkfid.js —— 给双面贴片打 Mark 点(基准点 / fiducial)
 *
 * 方案(不加任何器件 —— 避免 PCB 出现原理图里没有的元件, 触发 Netlist Error):
 *   每个位置 5 个对象:
 *     TOP 铜点 Ø1.0mm (Fill, layer 1) + TOP 开窗 Ø2.0mm (Fill, layer 5)
 *     BOT 铜点 Ø1.0mm (Fill, layer 2) + BOT 开窗 Ø2.0mm (Fill, layer 6)
 *     一个多层禁布区 2.2x2.2mm (Region, layer 12 = Multi) —— 保证开窗内除中心铜点外无铜
 *   3 个位置取三个角(不对称, 视觉可辨方向), 每个位置离板边 >=5mm。
 *   圆用 32 边形点列(顶点完全可控, 不依赖 CIRCLE 参数语义); 方框用 ["R",X,Ytop,W,H,0,0]。
 *
 * 用法: python pcbai.py run tools/mkfid.js
 * 结果: 打印每个位置的校验与创建结果(含回滚用的 primitiveId)
 */
const MIL = 1 / 0.0254;
const MM = v => v * MIL;
const out = { plan: [], created: [], errors: [] };

/* ---- 几何校验: 候选点周围 1.1mm 内不能有任何铜(用不存在的网名, 这样所有物体都算"别人的") ---- */
let X0 = 1e9, X1 = -1e9, Y0 = 1e9, Y1 = -1e9;
const Lall = (await eda.pcb_PrimitiveLine.getAll()) || [];
for (const l of Lall) {
  if (typeof l.startX !== 'number') continue;
  X0 = Math.min(X0, l.startX, l.endX); X1 = Math.max(X1, l.startX, l.endX);
  Y0 = Math.min(Y0, l.startY, l.endY); Y1 = Math.max(Y1, l.startY, l.endY);
}
const B = [X0 - 50, Y0 - 50, X1 + 50, Y1 + 50];
const G = await Geometry.build({ box: B, margin: 0, clearance: 0, holeHH: 6 });
const RAD = MM(2.2);                      // 校验直径 2.2mm = 禁布区尺寸
const candidates = [
  [7, 7], [83, 7], [83, 76],              // 首选: 左下 / 右下 / 右上
  [7, 76], [45, 7], [45, 76]              // 备选
];
const chosen = [];
for (const [xmm, ymm] of candidates) {
  if (chosen.length >= 3) break;
  const x = MM(xmm), y = MM(ymm);
  if (x < X0 + 5 * MIL || x > X1 - 5 * MIL || y < Y0 + 5 * MIL || y > Y1 - 5 * MIL) {
    out.plan.push({ pos: [xmm, ymm], skip: '离板边不足 5mm' }); continue;
  }
  const f1 = G.freeWhy('__fid__', x, y, RAD, 1);
  const f2 = G.freeWhy('__fid__', x, y, RAD, 2);
  if (f1.ok && f2.ok) { chosen.push([xmm, ymm]); out.plan.push({ pos: [xmm, ymm], ok: true, mm: [+x.toFixed(1), +y.toFixed(1)] }); }
  else out.plan.push({ pos: [xmm, ymm], skip: '铜太近', L1: f1.ok ? null : f1, L2: f2.ok ? null : f2 });
}

/* ---- 工具: 圆点列 / 方框 ---- */
const circlePts = (x, y, r, n) => {
  const pts = [];
  for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2; pts.push({ x: x + r * Math.cos(a), y: y + r * Math.sin(a) }); }
  return pts;
};
const M = eda.pcb_MathPolygon;
async function complexOf(shape) {
  const p = await M.createPolygon(shape);
  return await M.createComplexPolygon([p]);
}
const newId = o => { try { return o && o.getState_PrimitiveId ? o.getState_PrimitiveId() : null; } catch (e) { return null; } };

/* ---- 创建 ---- */
const R_DOT = MM(0.5);        // 铜点半径 = 0.5mm (Ø1.0mm)
const R_OPEN = MM(1.0);       // 开窗半径 = 1.0mm (Ø2.0mm)
const KEEP_HALF = MM(1.1);    // 禁布区半边长 = 1.1mm (2.2x2.2mm)
const NAME = 'FID_KEEPOUT';

for (const [xmm, ymm] of chosen) {
  const x = MM(xmm), y = MM(ymm);
  const rec = { pos: [xmm, ymm], mil: [+x.toFixed(1), +y.toFixed(1)], ids: {} };
  const dot = await complexOf(circlePts(x, y, R_DOT, 32));
  const open = await complexOf(circlePts(x, y, R_OPEN, 32));
  const keep = await complexOf(['R', x - KEEP_HALF, y + KEEP_HALF, KEEP_HALF * 2, KEEP_HALF * 2, 0, 0]);
  const mk = async (label, fn) => { try { const r = await fn(); rec.ids[label] = newId(r) || 'ok'; } catch (e) { out.errors.push(label + ' @' + xmm + ',' + ymm + ' -> ' + String(e && e.message ? e.message : e).slice(0, 90)); } };
  await mk('topCu', () => eda.pcb_PrimitiveFill.create('', 1, dot));
  await mk('topMask', () => eda.pcb_PrimitiveFill.create('', 5, open));
  await mk('botCu', () => eda.pcb_PrimitiveFill.create('', 2, dot));
  await mk('botMask', () => eda.pcb_PrimitiveFill.create('', 6, open));
  await mk('keepout', () => eda.pcb_PrimitiveRegion.create(12, keep, [7, 6], NAME, 0, false));
  out.created.push(rec);
}
try { await eda.pcb_Document.save(); out.saved = true; } catch (e) { out.saved = 'ERR ' + String(e).slice(0, 80); }
/* 复核: 现在有几个禁布区 */
try { const ids = await eda.pcb_PrimitiveRegion.getAllPrimitiveId(); out.keepoutCount = (ids || []).length; } catch (e) { out.keepoutCount = 'ERR'; }
out.note = '铜点Ø1.0mm/开窗Ø2.0mm/禁布区2.2mm; 3 角不对称; 离板边>=5mm; 圆用32边形';
return JSON.stringify(out).slice(0, 2600);
