/* 例: 用几何引擎布一段线 / 找一个过孔位
 * 跑法:  python tools/qq.py examples/route_example.js
 * 判据:  跑完必须 repour -> MCP sync -> drc_full 且违规数不增, 才保留
 */
const out = {};

// ---- 1) 单层 A* 布线 ----
const NET = '$1N19139', W = 5, LAYER = 1;
const S = [2317.56, 1200.0], T = [2519.69, 1230.31];
const box = [Math.min(S[0],T[0])-40, Math.min(S[1],T[1])-40, Math.max(S[0],T[0])+40, Math.max(S[1],T[1])+40];
const G = await Geometry.build({ box: box, margin: 60, clearance: 6, holeHH: 11.81 });
out.obstacles = { lines: G.lines.length, pads: G.pads.length, vias: G.vias.length };

const path = G.routeASTAR({ net: NET, layer: LAYER, width: W, from: S, to: T, step: 1 });
out.path = path;
if (path) {
  const ids = [];
  for (let k = 0; k < path.length - 1; k++) {
    const r = await eda.pcb_PrimitiveLine.create(NET, LAYER, path[k][0], path[k][1], path[k+1][0], path[k+1][1], W, false);
    ids.push(String(r && (r.primitiveId || r) || ''));
  }
  out.created = ids;
}

// ---- 2) 过孔择位（自动避开铜 + 孔到孔，并保证仍压住本网铜）----
const best = G.placeVia(NET, T, 16, 12, 30, 1);
out.viaCandidate = best;

// ---- 3) 同一点放一个孔的余量体检 ----
out.slackAtTarget = G.viaSlack(NET, T[0], T[1], 16, 12);

try { await eda.pcb_Document.save(); out.saved = true; } catch (e) { out.saveErr = String(e).slice(0, 60); }
return JSON.stringify(out).slice(0, 1200);
