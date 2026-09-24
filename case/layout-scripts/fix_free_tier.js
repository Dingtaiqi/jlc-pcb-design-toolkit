const out={};
try {
const num=v=>(typeof v==='number'&&isFinite(v))?v:0;
const p2m=x=>x/0.0254, m2p=x=>x*0.0254;   // mm<->mil
const lines0=(await eda.pcb_PrimitiveLine.getAll())||[], vias0=(await eda.pcb_PrimitiveVia.getAll())||[], pads0=(await eda.pcb_PrimitivePad.getAll())||[];
// ---------- PART 1: PGND↔U 线到线 ----------
const T1=[p2m(15.07),p2m(38.47)];
const near1=[];
for(const l of lines0) if(l.net==='PGND'||l.net==='U'){ const d=Math.min(Math.hypot(l.startX-T1[0],l.startY-T1[1]),Math.hypot(l.endX-T1[0],l.endY-T1[1]));
 if(d<40) near1.push([l.net,'L'+l.layer,+l.lineWidth.toFixed(2),[+l.startX.toFixed(0),+l.startY.toFixed(0),+l.endX.toFixed(0),+l.endY.toFixed(0)],l.primitiveId]); }
out.near1=near1.slice(0,8);
let narrowed=0;
for(const l of lines0){ if(l.net!=='PGND'&&l.net!=='U') continue;
 const d=Math.min(Math.hypot(l.startX-T1[0],l.startY-T1[1]),Math.hypot(l.endX-T1[0],l.endY-T1[1]));
 if(d>=40) continue;
 const w=+l.lineWidth.toFixed(2); if(w<20) continue;                       // 只缩加宽过的粗线
 try{ await eda.pcb_PrimitiveLine.delete(l.primitiveId);
      await eda.pcb_PrimitiveLine.create(l.net,l.layer,l.startX,l.startY,l.endX,l.endY,w-1.2,false); narrowed++; }catch(e){}
}
out.narrowed=narrowed;
// ---------- PART 2: dogbone 孔移动 ----------
const NEW=[2536.0,1228.5];
let dg=null; for(const v of vias0) if(v.net==='$1N19139'&&Math.abs(v.diameter-16)<0.6&&num(v.holeDiameter)>10) dg=v;
out.dogboneOld=dg?[+dg.x.toFixed(2),+dg.y.toFixed(2),+dg.diameter.toFixed(2)]:null;
if(dg){
 const oldX=dg.x, oldY=dg.y;
 try{ await eda.pcb_PrimitiveVia.delete(dg.primitiveId); }catch(e){}
 try{ await eda.pcb_PrimitiveVia.create('$1N19139',NEW[0],NEW[1],12,16); out.viaMoved=true; }catch(e){ out.viaMoved=String(e).slice(0,60); }
 // 短桩: 球心 -> 新孔位 (5mil)
 const ball=pads0.find(p=>p.net==='$1N19139'&&p.padNumber==='AC5');
 if(ball){ try{ await eda.pcb_PrimitiveLine.create('$1N19139',1,ball.x,ball.y,NEW[0],NEW[1],5,false); out.stub=true; }catch(e){} }
 // L16 走线: 把落在旧孔位的那段端点改到新孔位
 for(const l of lines0){ if(l.net!=='$1N19139'||l.layer!==16) continue;
  const ends=[[Math.hypot(l.startX-oldX,l.startY-oldY),'s'],[Math.hypot(l.endX-oldX,l.endY-oldY),'e']].sort((a,b)=>a[0]-b[0]);
  if(ends[0][0]>1.5) continue;
  try{ await eda.pcb_PrimitiveLine.delete(l.primitiveId);
   const sx=ends[0][1]==='s'?NEW[0]:l.startX, sy=ends[0][1]==='s'?NEW[1]:l.startY;
   const ex=ends[0][1]==='e'?NEW[0]:l.endX, ey=ends[0][1]==='e'?NEW[1]:l.endY;
   await eda.pcb_PrimitiveLine.create('$1N19139',16,sx,sy,ex,ey,l.lineWidth,false); out.trackFixed=true; }catch(e){}
 }
}
// ---------- PART 3: 孔到孔松弛 ----------
const P=[ [62.25,34.04,['UART0_RX','UART0_TX']], [10.08,42.57,['PWM_V','PWM_LU']], [63.75,37.38,['$1N17367','$1N17527']],
          [67.90,38.03,['$1N17981','VCC_NRF']], [6.83,38.41,['ADC1.1','ADC2.1']], [31.12,56.30,['NSLEEP','VCC']],
          [56.51,78.54,['GND','$2N1599']], [67.54,37.76,['$1N18259','VCC_NRF']], [10.64,42.71,['PWM_LU','PWM_U']],
          [41.11,53.64,['QSPI_SCLK','QSPI_SD0']], [13.13,42.65,['$1N8548','NSLEEP']] ];
const vias=(await eda.pcb_PrimitiveVia.getAll())||[];
const pairs=[], used=new Set();
for(const [mx0,my0,ns] of P){ const mx=p2m(mx0), my=p2m(my0);
 let best=null;
 for(const a of vias){ if(a.net!==ns[0]) continue; for(const b of vias){ if(b.net!==ns[1]) continue;
   const mid=[(a.x+b.x)/2,(a.y+b.y)/2]; const d=Math.hypot(mid[0]-mx,mid[1]-my);
   if(!best||d<best.d) best={a,b,d}; } }
 if(best&&best.d<25){ pairs.push(best); used.add(best.a.primitiveId); used.add(best.b.primitiveId); }
}
out.pairsFound=pairs.length;
const pos=new Map();
for(const id of used){ const v=vias.find(x=>x.primitiveId===id); pos.set(id,[v.x,v.y]); }
const MIN=24.2;
for(let it=0; it<60; it++){
 let moved=0;
 for(const pr of pairs){
  const A=pos.get(pr.a.primitiveId), B=pos.get(pr.b.primitiveId);
  let dx=B[0]-A[0], dy=B[1]-A[1], d=Math.hypot(dx,dy);
  if(d<1e-6){ dx=1; dy=0; d=1; }
  if(d<MIN){ const need=(MIN-d)/2, ux=dx/d, uy=dy/d;
   A[0]-=ux*need; A[1]-=uy*need; B[0]+=ux*need; B[1]+=uy*need; moved++; }
 }
 if(!moved) break;
}
let maxMove=0; for(const id of used){ const v=vias.find(x=>x.primitiveId===id); const p=pos.get(id);
 maxMove=Math.max(maxMove, Math.hypot(p[0]-v.x,p[1]-v.y)); }
out.maxMoveMil=+maxMove.toFixed(2);
// 应用: 先删后建
let mv=0;
for(const id of used){ try{ await eda.pcb_PrimitiveVia.delete(id); mv++; }catch(e){} }
await new Promise(r=>setTimeout(r,400));
for(const id of used){ const v=vias.find(x=>x.primitiveId===id); const p=pos.get(id);
 try{ await eda.pcb_PrimitiveVia.create(v.net, +p[0].toFixed(2), +p[1].toFixed(2), num(v.holeDiameter), num(v.diameter)); }catch(e){} }
out.viasMoved=mv;
try{await eda.pcb_Document.save();out.saved=true;}catch(e){}
} catch(e) { out.fatal=String(e).slice(0,150); }
return JSON.stringify(out).slice(0,1400);
