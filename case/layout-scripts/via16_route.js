const NET = '$1N19139';
const P_A = [2317.6, 1200.0], P_B = [2519.69, 1230.31];
const VIA_D = 16, VIA_R = VIA_D / 2, HOLE = 8, TW = 5, HW = TW / 2, CL = 6;
const out = { steps: [] };

function padR(p) { const s = p.pad; const t = Array.isArray(s) ? String(s[0]).toUpperCase() : '';
  const a = Array.isArray(s) ? Number(s[1]) || 0 : 0, b = Array.isArray(s) ? Number(s[2]) || 0 : 0;
  const pg = padSD.bind(null, p); return { t, a, b, pg }; }
// 精确：点到焊盘铜面的距离（0=在铜内）。RECT 用旋转框距，ELLIPSE 用椭圆近似
function padSD(p, x, y) {
  const s = p.pad, t = Array.isArray(s) ? String(s[0]).toUpperCase() : '';
  const a = (Array.isArray(s) ? Number(s[1]) : 0) || 0, b = (Array.isArray(s) ? Number(s[2]) : 0) || 0;
  let dx = x - p.x, dy = y - p.y;
  const rot = ((p.rotation || 0) * Math.PI) / 180;
  if (rot) { const c = Math.cos(-rot), sn = Math.sin(-rot); const nx = dx * c - dy * sn, ny = dx * sn + dy * c; dx = nx; dy = ny; }
  if (t.indexOf('CIRCLE') >= 0 || t.indexOf('ELLIPSE') >= 0) return Math.hypot(dx, dy) - Math.max(a, b) / 2;
  const hx = a / 2, hy = b / 2;
  const qx = Math.abs(dx) - hx, qy = Math.abs(dy) - hy;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0);
}
function segSeg(ax, ay, bx, by, cx, cy, dx2, dy2) {
  function pd(px, py, x1, y1, x2, y2) { const ex = x2 - x1, ey = y2 - y1, L2 = ex * ex + ey * ey;
    let t = L2 > 0 ? ((px - x1) * ex + (py - y1) * ey) / L2 : 0; t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * ex), py - (y1 + t * ey)); }
  return Math.min(pd(ax, ay, cx, cy, dx2, dy2), pd(bx, by, cx, cy, dx2, dy2), pd(cx, cy, ax, ay, bx, by), pd(dx2, dy2, ax, ay, bx, by));
}
function segPt(x1, y1, x2, y2, px, py) { const dx = x2 - x1, dy = y2 - y1, L2 = dx * dx + dy * dy;
  let t = L2 > 0 ? ((px - x1) * dx + (py - y1) * dy) / L2 : 0; t = Math.max(0, Math.min(1, t));
  return { d: Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)), t }; }

const pads = (await eda.pcb_PrimitivePad.getAll()) || [];
const vias = (await eda.pcb_PrimitiveVia.getAll()) || [];
const lines = (await eda.pcb_PrimitiveLine.getAll()) || [];

// 端点焊盘
function nearestPad(pt) { let best = null, bd = 1e9;
  for (const p of pads) { const d = Math.hypot(p.x - pt[0], p.y - pt[1]); if (d < bd) { bd = d; best = p; } }
  return { p: best, d: bd }; }
const padA = nearestPad(P_A), padB = nearestPad(P_B);
out.padA = { net: padA.p.net, x: +padA.p.x.toFixed(2), y: +padA.p.y.toFixed(2), d: +padA.d.toFixed(2), pad: padA.p.pad };
out.padB = { net: padB.p.net, x: +padB.p.x.toFixed(2), y: +padB.p.y.toFixed(2), d: +padB.d.toFixed(2), pad: padB.p.pad };
if (padA.p.net !== NET || padB.p.net !== NET) { out.err = 'endpoint net mismatch'; return JSON.stringify(out); }

// ---- 孔位搜索：要求 (a) 与目标焊盘重叠(同网) (b) 对所有层异物留 6mil ----
function viaSlack(x, y, ignorePad) {
  let worst = 1e9, whom = '';
  for (const l of lines) { if (l.net === NET) continue;
    const d = segPt(l.startX, l.startY, l.endX, l.endY, x, y).d - l.lineWidth / 2 - VIA_R - CL;
    if (d < worst) { worst = d; whom = 'line:' + l.net + '@L' + l.layer; } }
  for (const v of vias) { if (v.net === NET) continue;
    const d = Math.hypot(v.x - x, v.y - y) - v.diameter / 2 - VIA_R - CL;
    if (d < worst) { worst = d; whom = 'via:' + v.net; } }
  for (const p of pads) { if (p.net === NET) continue; if (p === ignorePad) continue;
    const d = padSD(p, x, y) - VIA_R - CL;
    if (d < worst) { worst = d; whom = 'pad:' + p.net + '/' + p.padNumber + '@L' + p.layer; } }
  return { s: worst, w: whom };
}
function findVia(center, tgtPad) {
  let best = null;
  for (let i = -30; i <= 30; i++) for (let j = -30; j <= 30; j++) {
    const x = center[0] + i, y = center[1] + j;
    const ov = padSD(tgtPad, x, y);           // 与目标焊盘重叠 => ov <= VIA_R
    if (ov > VIA_R - 1) continue;
    const s = viaSlack(x, y, tgtPad);
    if (s.s < 0) continue;
    const score = s.s - 0.02 * Math.hypot(i, j);
    if (!best || score > best.score) best = { x: +x.toFixed(2), y: +y.toFixed(2), slack: +s.s.toFixed(2), whom: s.w, off: [i, j], score, ov: +ov.toFixed(2) };
  }
  return best;
}
const vA = findVia([padA.p.x, padA.p.y], padA.p);
const vB = findVia([padB.p.x, padB.p.y], padB.p);
out.viaA = vA; out.viaB = vB;
if (!vA || !vB) { out.err = 'no legal via position'; return JSON.stringify(out, null, 1).slice(0, 1800); }

// ---- 层 16 障碍（只对本层有意义：16 层线、所有过孔、通孔焊盘 L12）----
const obs = [];
for (const l of lines) if (l.net !== NET && (l.layer === 16 || l.layer === 12)) obs.push({ k: 'L', sd: (x, y) => segPt(l.startX, l.startY, l.endX, l.endY, x, y).d - l.lineWidth / 2, need: HW + CL });
for (const v of vias) if (v.net !== NET) obs.push({ k: 'V', sd: (x, y) => Math.hypot(v.x - x, v.y - y) - v.diameter / 2, need: HW + CL });
for (const p of pads) if (p.net !== NET && (p.layer === 12)) obs.push({ k: 'P', sd: (x, y) => padSD(p, x, y), need: HW + CL });
out.obsCount = obs.length;
function free(x, y) { for (const o of obs) if (o.sd(x, y) < o.need) return false; return true; }

// ---- A* on layer 16 ----
const S = [vA.x, vA.y], T = [vB.x, vB.y];
const step = 2, margin = 40;
const x0 = Math.min(S[0], T[0]) - margin, x1 = Math.max(S[0], T[0]) + margin;
const y0 = Math.min(S[1], T[1]) - margin, y1 = Math.max(S[1], T[1]) + margin;
const nx = Math.floor((x1 - x0) / step) + 1, ny = Math.floor((y1 - y0) / step) + 1;
const key = (i, j) => j * nx + i;
const idx = (x, y) => [Math.round((x - x0) / step), Math.round((y - y0) / step)];
const blocked = new Uint8Array(nx * ny);
for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) if (!free(x0 + i * step, y0 + j * step)) blocked[key(i, j)] = 1;
const si = idx(S[0], S[1]), ti = idx(T[0], T[1]);
blocked[key(si[0], si[1])] = 0; blocked[key(ti[0], ti[1])] = 0;
const g = new Float32Array(nx * ny).fill(1e9), prev = new Int32Array(nx * ny).fill(-1);
const open = [[0, si[0], si[1]]]; g[key(si[0], si[1])] = 0;
const D = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, 1.414], [1, -1, 1.414], [-1, 1, 1.414], [-1, -1, 1.414]];
let found = false, guard = 0;
while (open.length && !found && guard++ < 400000) {
  let bi = 0; for (let k = 1; k < open.length; k++) if (open[k][0] < open[bi][0]) bi = k;
  const [f, ci, cj] = open.splice(bi, 1)[0];
  if (ci === ti[0] && cj === ti[1]) { found = true; break; }
  for (const [di, dj, w] of D) { const ni = ci + di, nj = cj + dj;
    if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
    const kk = key(ni, nj); if (blocked[kk]) continue;
    const ng = g[key(ci, cj)] + w;
    if (ng < g[kk] - 1e-6) { g[kk] = ng; prev[kk] = key(ci, cj);
      const h = Math.hypot(ti[0] - ni, ti[1] - nj);
      open.push([ng + h, ni, nj]); } } }
out.routed = found;
if (!found) { out.note = '层16 无通路，需换层或更细网格'; return JSON.stringify(out, null, 1).slice(0, 1800); }

// 回溯 + 拉直
let path = []; let cur = key(ti[0], ti[1]);
while (cur >= 0) { const j = Math.floor(cur / nx), i = cur % nx; path.push([+(x0 + i * step).toFixed(2), +(y0 + j * step).toFixed(2)]); cur = prev[cur]; }
path.reverse(); path[0] = S; path[path.length - 1] = T;
const simp = [path[0]];
let i0 = 0;
while (i0 < path.length - 1) { let j2 = path.length - 1;
  while (j2 > i0 + 1) { const a = path[i0], b = path[j2];
    let ok = true; const L = Math.hypot(b[0] - a[0], b[1] - a[1]); const n = Math.ceil(L / 1.5);
    for (let t = 1; t < n; t++) { const x = a[0] + (b[0] - a[0]) * t / n, y = a[1] + (b[1] - a[1]) * t / n; if (!free(x, y)) { ok = false; break; } }
    if (ok) break; j2--; }
  simp.push(path[j2]); i0 = j2; }
out.path = simp;
out.pathLen = +simp.reduce((s, p, k) => k ? s + Math.hypot(p[0] - simp[k-1][0], p[1] - simp[k-1][1]) : 0, 0).toFixed(1);
return JSON.stringify(out, null, 1).slice(0, 2600);
