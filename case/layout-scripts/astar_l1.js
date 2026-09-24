const NET = '$1N19139', TW = 5, NEED = TW / 2 + 6;
const S = [2317.56, 1200.0], T = [2519.69, 1230.31];
const out = {};
const t00 = Date.now();
function padSD(p, x, y) { const s = p.pad, t = Array.isArray(s) ? String(s[0]).toUpperCase() : '';
  const a = (Array.isArray(s) ? Number(s[1]) : 0) || 0, b = (Array.isArray(s) ? Number(s[2]) : 0) || 0;
  let dx = x - p.x, dy = y - p.y; const rot = ((p.rotation || 0) * Math.PI) / 180;
  if (rot) { const c = Math.cos(-rot), sn = Math.sin(-rot); const nx = dx * c - dy * sn, ny = dx * sn + dy * c; dx = nx; dy = ny; }
  if (t.indexOf('CIRCLE') >= 0 || t.indexOf('ELLIPSE') >= 0) return Math.hypot(dx, dy) - Math.max(a, b) / 2;
  const qx = Math.abs(dx) - a / 2, qy = Math.abs(dy) - b / 2;
  return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0);
}
function segPt(x1,y1,x2,y2,px,py){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;let t=L2>0?((px-x1)*dx+(py-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy));}
const BX = [2300, 1185, 2570, 1265], MG = 12;
const inB = (x, y) => x > BX[0]-MG && x < BX[2]+MG && y > BX[1]-MG && y < BX[3]+MG;
const pads = (await eda.pcb_PrimitivePad.getAll()) || [];
const vias = (await eda.pcb_PrimitiveVia.getAll()) || [];
const lines = (await eda.pcb_PrimitiveLine.getAll()) || [];
const obs = [];
for (const l of lines) if (l.net !== NET && l.layer === 1 && (inB(l.startX,l.startY) || inB(l.endX,l.endY)))
  obs.push((x,y) => segPt(l.startX,l.startY,l.endX,l.endY,x,y) - l.lineWidth/2 - NEED);
for (const v of vias) if (v.net !== NET && inB(v.x,v.y))
  obs.push((x,y) => Math.hypot(v.x-x,v.y-y) - v.diameter/2 - NEED);
for (const p of pads) if (p.net !== NET && inB(p.x,p.y))
  obs.push((x,y) => padSD(p,x,y) - NEED);
out.obs = obs.length; out.buildMs = Date.now()-t00;
const step = 1, nx = Math.round((BX[2]-BX[0])/step)+1, ny = Math.round((BX[3]-BX[1])/step)+1, N = nx*ny;
const free = new Uint8Array(N);
for (let i=0;i<nx;i++) for (let j=0;j<ny;j++) { const x=BX[0]+i, y=BX[1]+j; let ok=1;
  for (const o of obs) if (o(x,y) < 0) { ok=0; break; } free[j*nx+i]=ok; }
out.freeMs = Date.now()-t00;
const toI = (x,y) => [Math.round(x-BX[0]), Math.round(y-BX[1])];
const si = toI(S[0],S[1]), ti = toI(T[0],T[1]);
free[si[1]*nx+si[0]] = 1; free[ti[1]*nx+ti[0]] = 1;
out.sIdx = si; out.tIdx = ti;
const gv = new Float32Array(N).fill(1e9), fv = new Float32Array(N).fill(1e9), pv = new Int32Array(N).fill(-1);
const H = [];
function hpush(k){ H.push(k); let c=H.length-1; while(c>0){ const p=(c-1)>>1; if (fv[H[p]]<=fv[H[c]]) break; const t=H[p]; H[p]=H[c]; H[c]=t; c=p; } }
function hpop(){ const top=H[0], last=H.pop(); if (H.length){ H[0]=last; let p=0; for(;;){ const l=2*p+1, r=l+1; let s2=p;
  if (l<H.length && fv[H[l]]<fv[H[s2]]) s2=l; if (r<H.length && fv[H[r]]<fv[H[s2]]) s2=r; if (s2===p) break; const t=H[s2]; H[s2]=H[p]; H[p]=t; p=s2; } } return top; }
const kS = si[1]*nx+si[0], kT = ti[1]*nx+ti[0];
gv[kS]=0; fv[kS]=Math.hypot(ti[0]-si[0], ti[1]-si[1]); hpush(kS);
const DX=[1,-1,0,0,1,1,-1,-1], DY=[0,0,1,-1,1,-1,1,-1], DW=[1,1,1,1,1.414,1.414,1.414,1.414];
let found=false, pops=0;
while (H.length) {
  const k = hpop(); pops++;
  if (k === kT) { found = true; break; }
  const ci = k % nx, cj = (k - ci)/nx, gc = gv[k];
  for (let d=0; d<8; d++) { const ni=ci+DX[d], nj=cj+DY[d];
    if (ni<0||nj<0||ni>=nx||nj>=ny) continue;
    const kk = nj*nx+ni; if (!free[kk]) continue;
    const ng = gc + DW[d];
    if (ng < gv[kk]-1e-6) { gv[kk]=ng; pv[kk]=k; fv[kk]=ng+Math.hypot(ti[0]-ni, ti[1]-nj); hpush(kk); } }
  if (Date.now()-t00 > 40000) { out.timeout = true; break; }
}
out.found = found; out.pops = pops; out.ms = Date.now()-t00;
if (!found) { out.note = 'TOP 层无通路'; return JSON.stringify(out); }
let path=[], cur=kT;
while (cur >= 0) { const i = cur % nx, j = (cur-i)/nx; path.push([+(BX[0]+i).toFixed(1), +(BX[1]+j).toFixed(1)]); cur = pv[cur]; }
path.reverse(); path[0]=S; path[path.length-1]=T;
function clear(x1,y1,x2,y2){ const L=Math.hypot(x2-x1,y2-y1), n=Math.ceil(L/1.0);
  for (let t=1;t<n;t++){ const x=x1+(x2-x1)*t/n, y=y1+(y2-y1)*t/n; const i=Math.round(x-BX[0]), j=Math.round(y-BX[1]);
    if (i<0||j<0||i>=nx||j>=ny) return false; if (!free[j*nx+i]) return false; }
  for (const o of obs) { if (o((x1+x2)/2, (y1+y2)/2) < -2) return false; } return true; }
const simp=[path[0]]; let i0=0;
while (i0 < path.length-1) { let j2 = path.length-1;
  while (j2 > i0+1 && !clear(path[i0][0],path[i0][1],path[j2][0],path[j2][1])) j2--;
  simp.push(path[j2]); i0=j2; }
out.path = simp; out.len = +simp.reduce((s,p,k)=>k? s+Math.hypot(p[0]-simp[k-1][0],p[1]-simp[k-1][1]):0,0).toFixed(1);
const ids=[];
for (let k=0;k<simp.length-1;k++) { try { const r = await eda.pcb_PrimitiveLine.create(NET, 1, simp[k][0], simp[k][1], simp[k+1][0], simp[k+1][1], TW, false); ids.push(r && (r.primitiveId || r)); } catch(e) { ids.push('ERR'); } }
out.ids = ids;
try { await eda.pcb_Document.save(); out.saved = true; } catch(e) { out.saveErr = String(e).slice(0,80); }
return JSON.stringify(out);
