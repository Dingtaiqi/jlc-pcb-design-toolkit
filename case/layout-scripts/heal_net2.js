const out={};
try {
const num=v=>(typeof v==='number'&&isFinite(v))?v:0;
const CL=6;
function segPt(x1,y1,x2,y2,px,py){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;let t=L2>0?((px-x1)*dx+(py-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy));}
function padSD(p,x,y){const s=p.pad,t=Array.isArray(s)?String(s[0]).toUpperCase():'';
 const a=num(Array.isArray(s)?+s[1]:0),b=num(Array.isArray(s)?+s[2]:0);
 let dx=x-p.x,dy=y-p.y;const rot=(num(p.rotation)*Math.PI)/180;
 if(rot){const c=Math.cos(-rot),sn=Math.sin(-rot);const nx=dx*c-dy*sn,ny=dx*sn+dy*c;dx=nx;dy=ny;}
 if(t.indexOf('CIRCLE')>=0||t.indexOf('ELLIPSE')>=0)return Math.hypot(dx,dy)-Math.max(a,b)/2;
 const qx=Math.abs(dx)-a/2,qy=Math.abs(dy)-b/2;
 return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0);}
function traceOK(net,x0,y0,x1,y1,w,lines,pads,vias){
 const L=Math.hypot(x1-x0,y1-y0), n=Math.max(4,Math.ceil(L));
 for(let t=0;t<=n;t++){ const x=x0+(x1-x0)*t/n, y=y0+(y1-y0)*t/n, hw=w/2;
  for(const l of lines){ if(l.net===net) continue;
   if(segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-hw-CL<0) return false; }
  for(const p of pads){ if(p.net===net) continue; if(padSD(p,x,y)-hw-CL<0) return false; }
  for(const v of vias){ if(v.net===net) continue;
   if(Math.hypot(v.x-x,v.y-y)-num(v.diameter)/2-hw-CL<0) return false; }
 }
 return true; }
let lines=(await eda.pcb_PrimitiveLine.getAll())||[], pads=(await eda.pcb_PrimitivePad.getAll())||[], vias=(await eda.pcb_PrimitiveVia.getAll())||[];
out.report={};
const _nets=[...new Set((((await eda.pcb_PrimitiveLine.getAll())||[]).map(l=>l.net)))].filter(n=>n&&n!=='');
out.scanned=_nets.length;
for(const NET of _nets){
 const mine=lines.filter(l=>l.net===NET), mp=pads.filter(p=>p.net===NET), mv=vias.filter(v=>v.net===NET);
 const ends=[];
 for(const l of mine){ ends.push([l.layer,l.startX,l.startY,l.primitiveId,'s']); ends.push([l.layer,l.endX,l.endY,l.primitiveId,'e']); }
 for(const v of mv) ends.push([1,v.x,v.y,'via','v']);
 const loose=[];
 for(const [ly,x,y,id,kind] of ends){
  let touch=0.0;
  for(const l of mine){ if(l.primitiveId===id&&kind!=='v') { if(Math.hypot(l.startX-x,l.startY-y)>0.6&&Math.hypot(l.endX-x,l.endY-y)>0.6) touch=Math.max(touch,0.6-segPt(l.startX,l.startY,l.endX,l.endY,x,y)+num(l.lineWidth)/2); } }
  let t2=false;
  for(const l of mine){ if(l.primitiveId===id&&kind!=='v') continue;
   if(l.layer!==ly) continue;
   if(Math.hypot(l.startX-x,l.startY-y)<2||Math.hypot(l.endX-x,l.endY-y)<2){t2=true;break;}
   if(segPt(l.startX,l.startY,l.endX,l.endY,x,y)<num(l.lineWidth)/2+1){t2=true;break;} }
  for(const p of mp) if((p.layer===ly||p.layer===12)&&padSD(p,x,y)<2){t2=true;break;}
  for(const v of mv) if(Math.hypot(v.x-x,v.y-y)<num(v.diameter)/2+1){t2=true;break;}
  if(!t2) loose.push([ly,+x.toFixed(1),+y.toFixed(1),String(id),kind]);
 }
 if(loose.length) out.report[NET]={segs:mine.length,loose:loose.length,looseList:loose.slice(0,6)};
 // 对每个悬空端, 找最近的同网铜并连过去
 for(const [ly,x,y] of loose){
  let best=null;
  for(const l of mine){ if(l.layer!==ly) continue;
   if(Math.hypot(l.startX-x,l.startY-y)<1&&Math.hypot(l.endX-x,l.endY-y)<1) continue;
   const dx=l.endX-l.startX, dy=l.endY-l.startY, L2=dx*dx+dy*dy;
   let t=L2>0?((x-l.startX)*dx+(y-l.startY)*dy)/L2:0; t=Math.max(0,Math.min(1,t));
   const cxp=l.startX+t*dx, cyp=l.startY+t*dy, d=Math.hypot(cxp-x,cyp-y);
   if(d<0.6) continue;
   if(!best||d<best.d) best={d,tx:+cxp.toFixed(1),ty:+cyp.toFixed(1),w:num(l.lineWidth),src:'line'};
  }
  for(const v of mv){ const d=Math.hypot(v.x-x,v.y-y); if(d<0.6) continue;
   if(!best||d<best.d) best={d,tx:+v.x.toFixed(1),ty:+v.y.toFixed(1),w:10,src:'via'}; }
  for(const p of mp){ const d=padSD(p,x,y); if(d<0.6) continue;
   if(!best||d<best.d) best={d,tx:+p.x.toFixed(1),ty:+p.y.toFixed(1),w:10,src:'pad'}; }
  if(!best) continue;
  const w=Math.max(8,Math.min(10,best.w));
  if(!traceOK(NET,x,y,best.tx,best.ty,w,lines,pads,vias)) { out.report[NET].fail=(out.report[NET].fail||0)+1; continue; }
  try{ await eda.pcb_PrimitiveLine.create(NET,ly,x,y,best.tx,best.ty,w,false); out.report[NET].healed=(out.report[NET].healed||0)+1; }catch(e){}
  lines=(await eda.pcb_PrimitiveLine.getAll())||[];
 }
}
try{await eda.pcb_Document.save();out.saved=true;}catch(e){}
} catch(e) { out.fatal=String(e).slice(0,150); }
return JSON.stringify(out).slice(0,1500);
