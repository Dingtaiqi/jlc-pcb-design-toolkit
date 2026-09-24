const out={};
try {
const num=v=>(typeof v==='number'&&isFinite(v))?v:0;
const CL=6, HH=12.3, STUBW=8, SR=32;
function segPt(x1,y1,x2,y2,px,py){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;let t=L2>0?((px-x1)*dx+(py-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy));}
function padSD2(P,x,y){let dx=x-P.x,dy=y-P.y;
 if(P.rot){const c=P.c,sn=P.s;const nx=dx*c-dy*sn,ny=dx*sn+dy*c;dx=nx;dy=ny;}
 if(P.ell) return Math.hypot(dx,dy)-P.rmax;
 const qx=Math.abs(dx)-P.hx,qy=Math.abs(dy)-P.hy;
 return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0);}
const lines=(await eda.pcb_PrimitiveLine.getAll())||[], pads=(await eda.pcb_PrimitivePad.getAll())||[];
let vias=(await eda.pcb_PrimitiveVia.getAll())||[];
const P=[];
for(const p of pads){ const s=p.pad,t=Array.isArray(s)?String(s[0]).toUpperCase():'';
 const a=num(Array.isArray(s)?+s[1]:0),b=num(Array.isArray(s)?+s[2]:0);
 const rot=(num(p.rotation)*Math.PI)/180;
 let hr=0; const h=p.hole;
 if(typeof h==='number'&&h>0)hr=h/2; else if(Array.isArray(h)){for(const x of h)if(typeof x==='number'&&x>0){hr=x/2;break;}}
 else if(h&&typeof h==='object'&&typeof h.diameter==='number')hr=h.diameter/2;
 P.push({net:p.net,x:p.x,y:p.y,rot:rot?1:0,c:Math.cos(-rot),s:Math.sin(-rot),
  ell:(t.indexOf('CIRCLE')>=0||t.indexOf('ELLIPSE')>=0),rmax:Math.max(a,b)/2,hx:a/2,hy:b/2,hr}); }
function viaOK(net,x,y,r,hR,vs){
 for(const l of lines){ if(l.net===net) continue;
  if(segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-r-CL<0) return false; }
 for(const p of P){ if(p.net===net) continue; if(padSD2(p,x,y)-r-CL<0) return false;
  if(p.hr>0 && Math.hypot(p.x-x,p.y-y)-hR-p.hr-HH<0) return false; }
 for(const v of vs){ if(v.net===net&&Math.abs(v.x-x)<0.01&&Math.abs(v.y-y)<0.01) continue;
  const d=Math.hypot(v.x-x,v.y-y);
  if(d-num(v.diameter)/2-r-CL<0) return false;
  if(d-hR-num(v.holeDiameter)/2-HH<0) return false; }
 return true; }
function stubOK(net,x0,y0,x1,y1,vs){
 const L=Math.hypot(x1-x0,y1-y0), n=Math.max(4,Math.ceil(L));
 for(let t=0;t<=n;t++){ const x=x0+(x1-x0)*t/n, y=y0+(y1-y0)*t/n;
  for(const l of lines){ if(l.net===net) continue;
   if(segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-STUBW/2-CL<0) return false; }
  for(const p of P){ if(p.net===net) continue; if(padSD2(p,x,y)-STUBW/2-CL<0) return false; }
  for(const v of vs){ if(v.net===net&&Math.abs(v.x-x1)<0.01&&Math.abs(v.y-y1)<0.01) continue;
   const d=Math.hypot(v.x-x,v.y-y);
   if(d-num(v.diameter)/2-STUBW/2-CL<0) return false; }
 }
 return true; }
const tight=[];
for(let i=0;i<vias.length;i++)for(let j=i+1;j<vias.length;j++){
 const g=Math.hypot(vias[i].x-vias[j].x,vias[i].y-vias[j].y)-(num(vias[i].holeDiameter)+num(vias[j].holeDiameter))/2;
 if(g<HH-0.05) tight.push([i,j,+g.toFixed(2)]); }
tight.sort((a,b)=>a[2]-b[2]);
out.tight=tight.length; out.tightList=tight.slice(0,5);
const plan=new Map();
for(const [i,j] of tight){
 let chosen=null;
 for(const idx of [j,i]){
  const t=vias[idx];
  if(plan.has(t.primitiveId)) continue;
  const r=num(t.diameter)/2, hR=num(t.holeDiameter)/2;
  const others=vias.filter(v=>v.primitiveId!==t.primitiveId).concat([...plan.values()].map(m=>({net:m.net,x:m.nx,y:m.ny,diameter:m.d,holeDiameter:m.h,primitiveId:'m'})));
  let best=null;
  for(let di=-SR;di<=SR;di++)for(let dj=-SR;dj<=SR;dj++){
   const dist=Math.hypot(di,dj); if(dist<0.9||dist>SR) continue;
   const x=+(t.x+di).toFixed(1), y=+(t.y+dj).toFixed(1);
   if(!viaOK(t.net,x,y,r,hR,others)) continue;
   if(!stubOK(t.net,t.x,t.y,x,y,others)) continue;
   const sc=-dist*0.02 + 0.0;                       // 越近越好(同样合法时)
   if(!best||dist<best.dist) best={x,y,dist:+dist.toFixed(1)};
  }
  if(best){ chosen={id:t.primitiveId,ox:t.x,oy:t.y,nx:best.x,ny:best.y,net:t.net,d:t.diameter,h:t.holeDiameter,dist:best.dist}; break; }
 }
 if(chosen) plan.set(chosen.id,chosen);
}
out.toMove=plan.size;
out.moves=[...plan.values()].map(m=>[m.net,+m.ox.toFixed(0),+m.oy.toFixed(0),m.nx,m.ny,m.dist]);
for(const m of plan.values()){ try{ await eda.pcb_PrimitiveVia.delete(m.id); }catch(e){} }
await new Promise(r=>setTimeout(r,300));
let st=0;
for(const m of plan.values()){ try{ await eda.pcb_PrimitiveLine.create(m.net,1,m.ox,m.oy,m.nx,m.ny,STUBW,false); st++; }catch(e){} }
for(const m of plan.values()){ try{ await eda.pcb_PrimitiveVia.create(m.net,m.nx,m.ny,num(m.h),num(m.d)); }catch(e){} }
out.stubs=st;
vias=(await eda.pcb_PrimitiveVia.getAll())||[];
let minG=1e9, at=null;
for(let i=0;i<vias.length;i++)for(let j=i+1;j<vias.length;j++){
 const g=Math.hypot(vias[i].x-vias[j].x,vias[i].y-vias[j].y)-(num(vias[i].holeDiameter)+num(vias[j].holeDiameter))/2;
 if(g<minG){minG=g;at=[+vias[i].x.toFixed(0),+vias[i].y.toFixed(0),vias[i].net,vias[j].net];} }
out.minGapAfter=+minG.toFixed(2); out.atAfter=at;
try{await eda.pcb_Document.save();out.saved=true;}catch(e){}
} catch(e) { out.fatal=String(e).slice(0,150); }
return JSON.stringify(out).slice(0,1400);
