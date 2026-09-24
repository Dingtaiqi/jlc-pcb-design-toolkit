/* mkfid2.js —— 全板扫描找空位, 打 3 个 Mark 点(双面), 不加任何器件
 *
 * 约束: 两层铜都净空 >=1.2mm; 离真实板边 >=5mm; 避开轮子挖空区/天线禁布区;
 *       离元件中心 >=4mm(尽量不被器件压住); 3 个点分散(>=25mm)且不对称。
 * 对象: TOP 铜点Ø1.0 + TOP 开窗Ø2.0 + BOT 铜点Ø1.0 + BOT 开窗Ø2.0 + 多层禁布区2.2x2.2
 * 圆用 32 边形点列(顶点可控); 方框用 ["R",X,Ytop,W,H,0,0] (Y=上边)。
 */
const MIL = 1 / 0.0254, MM = v => v * MIL;
const out = { board: {}, scan: {}, chosen: [], created: [], errors: [] };

/* 真实板边(mm) —— 90x90 板, y 从 -7.239 到 82.761 */
const BX0 = 0, BX1 = 90, BY0 = -7.239, BY1 = 82.761;
const CUT = { x0: 16.36, x1: 21.34, y0: 50.80, y1: 75.44 };      // 轮子挖空区(不能放)
const ANT = { x0: 84.0, x1: 90.5, y0: 31.0, y1: 39.0 };           // 天线禁布区
out.board = { BX0, BX1, BY0, BY1, cutout: CUT, antenna: ANT };

const C = (await eda.pcb_PrimitiveComponent.getAll()) || [];
out.scan.comps = C.length;
const comps = C.filter(c => typeof c.x === 'number').map(c => ({ d: String(c.designator || ''), x: c.x, y: c.y }));

let X0 = 1e9, X1 = -1e9, Y0 = 1e9, Y1 = -1e9;
for (const l of ((await eda.pcb_PrimitiveLine.getAll()) || [])) {
  if (typeof l.startX !== 'number') continue;
  X0 = Math.min(X0, l.startX, l.endX); X1 = Math.max(X1, l.startX, l.endX);
  Y0 = Math.min(Y0, l.startY, l.endY); Y1 = Math.max(Y1, l.startY, l.endY);
}
const G = await Geometry.build({ box: [X0 - 60, Y0 - 60, X1 + 60, Y1 + 60], margin: 0, clearance: 0, holeHH: 6 });

const inRect = (x, y, r) => x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
const ok = (xmm, ymm) => {
  if (xmm < BX0 + 5 || xmm > BX1 - 5 || ymm < BY0 + 5 || ymm > BY1 - 5) return null;   // 离板边 >=5mm
  if (inRect(xmm, ymm, CUT) || inRect(xmm, ymm, ANT)) return null;
  for (const c of comps) if (Math.hypot(c.x / MIL - xmm, c.y / MIL - ymm) < 4) return null;  // 尽量别被器件压住
  const x = MM(xmm), y = MM(ymm);
  for (const w of [4.0, 3.2, 2.4]) {                              // 净空等级: 越大越好
    const a = G.freeWhy('__fid__', x, y, MM(w), 1), b = G.freeWhy('__fid__', x, y, MM(w), 2);
    if (a.ok && b.ok) return w;
  }
  return null;
};

/* 1.5mm 网格扫描 */
const cands = [];
for (let x = BX0 + 5; x <= BX1 - 5; x += 1.5)
  for (let y = BY0 + 5; y <= BY1 - 5; y += 1.5) {
    const g = ok(Math.round(x * 10) / 10, Math.round(y * 10) / 10);
    if (g) cands.push({ x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, g });
  }
out.scan.free = cands.length;
out.scan.byGrade = cands.reduce((a, c) => (a[c.g] = (a[c.g] || 0) + 1, a), {});

/* 选 3 个: 优先净空等级高 + 互相 >=25mm + 尽量分三角(不对称) */
cands.sort((a, b) => b.g - a.g || Math.hypot(a.x - 45, a.y - 38) - Math.hypot(b.x - 45, b.y - 38));
for (const c of cands) {
  if (out.chosen.length >= 3) break;
  if (out.chosen.every(o => Math.hypot(o.x - c.x, o.y - c.y) >= 25)) out.chosen.push(c);
}
if (out.chosen.length < 3) out.warn = '只找到 ' + out.chosen.length + ' 个满足条件的空位';

/* ---- 创建 ---- */
const circlePts = (x, y, r, n) => { const p = []; for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2; p.push({ x: x + r * Math.cos(a), y: y + r * Math.sin(a) }); } return p; };
const M = eda.pcb_MathPolygon;
const cplx = async s => await M.createComplexPolygon([await M.createPolygon(s)]);
const nid = o => { try { return o && o.getState_PrimitiveId ? o.getState_PrimitiveId() : 'ok'; } catch (e) { return 'ok'; } };
for (const c of out.chosen) {
  const x = MM(c.x), y = MM(c.y);
  const dot = await cplx(circlePts(x, y, MM(0.5), 32));
  const open = await cplx(circlePts(x, y, MM(1.0), 32));
  const keep = await cplx(['R', x - MM(1.1), y + MM(1.1), MM(2.2), MM(2.2), 0, 0]);
  const rec = { pos: [c.x, c.y], grade: c.g, ids: {} };
  const mk = async (k, fn) => { try { rec.ids[k] = nid(await fn()); } catch (e) { out.errors.push(k + '@' + c.x + ',' + c.y + ': ' + String(e && e.message ? e.message : e).slice(0, 80)); } };
  await mk('topCu', () => eda.pcb_PrimitiveFill.create('', 1, dot));
  await mk('topMask', () => eda.pcb_PrimitiveFill.create('', 5, open));
  await mk('botCu', () => eda.pcb_PrimitiveFill.create('', 2, dot));
  await mk('botMask', () => eda.pcb_PrimitiveFill.create('', 6, open));
  await mk('keepout', () => eda.pcb_PrimitiveRegion.create(12, keep, [7, 6], 'FID_KEEPOUT', 0, false));
  out.created.push(rec);
}
try { await eda.pcb_Document.save(); out.saved = true; } catch (e) { out.saved = 'ERR ' + String(e).slice(0, 70); }
try { const ids = await eda.pcb_PrimitiveRegion.getAllPrimitiveId(); out.keepoutTotal = (ids || []).length; } catch (e) { out.keepoutTotal = 'ERR'; }
return JSON.stringify(out).slice(0, 2600);
