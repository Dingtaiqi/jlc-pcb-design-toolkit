/* mkfid3.js —— 用"极短粗线"补齐 3 个 Mark 点(幂等: 已存在的跳过)
 *
 * 为什么用线条而不是填充: 实测 pcb_PrimitiveFill.create 的 7 种调用写法全部失败,
 *   而 PrimitiveLine.create(net, layer, x1,y1,x2,y2, width, lock) 稳定可用。
 * 每个位置 4 个对象: L1 铜点Ø1.0 / L5 顶层开窗Ø2.0 / L2 铜点Ø1.0 / L6 底层开窗Ø2.0
 * (多层禁布区 2.2x2.2 已由 mkfid2.js 建好)
 */
const MIL = 1 / 0.0254, MM = v => v * MIL;
const EPS = MM(0.02);                       // 线长 0.02mm -> 视觉上就是一个圆点
const out = { created: [], skipped: [], errors: [] };

const POS = [[42.5, 38.3], [62.0, 54.8], [35.0, 14.3]];   // ★示例坐标: 换成你板上扫描出来的位置
const SPEC = [
  ['topCu', 1, 1.0], ['topMask', 5, 2.0],
  ['botCu', 2, 1.0], ['botMask', 6, 2.0]
];
const lines = (await eda.pcb_PrimitiveLine.getAll()) || [];
const has = (x, y, layer, w) => lines.some(l =>
  l.layer === layer && Math.abs(l.startX - x) < 1.5 && Math.abs(l.startY - y) < 1.5 &&
  Math.abs((l.lineWidth || 0) - MM(w)) < MM(0.15));

for (const [xmm, ymm] of POS) {
  const x = MM(xmm), y = MM(ymm);
  for (const [name, layer, w] of SPEC) {
    if (has(x, y, layer, w)) { out.skipped.push(name + '@' + xmm + ',' + ymm); continue; }
    try {
      const r = await eda.pcb_PrimitiveLine.create('', layer, x, y, x + EPS, y, MM(w), false);
      out.created.push({ obj: name, pos: [xmm, ymm], id: (r && r.getState_PrimitiveId) ? r.getState_PrimitiveId() : 'ok' });
    } catch (e) {
      out.errors.push(name + '@' + xmm + ',' + ymm + ' -> ' + String(e && e.message ? e.message : e).slice(0, 80));
    }
  }
}
try { await eda.pcb_Document.save(); out.saved = true; } catch (e) { out.saved = 'ERR ' + String(e).slice(0, 70); }
out.total = { created: out.created.length, skipped: out.skipped.length, errors: out.errors.length };
out.spec = '铜点Ø1.0mm(线宽1.0mm) / 开窗Ø2.0mm; 禁布区2.2x2.2mm; 3 角不对称; 离板边>=5mm';
return JSON.stringify(out).slice(0, 2000);
