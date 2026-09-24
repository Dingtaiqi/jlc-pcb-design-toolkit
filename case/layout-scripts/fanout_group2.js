const out={};
try {
const num=v=>(typeof v==='number'&&isFinite(v))?v:0;
const CL=6, HH=12.3, SW=8, R=32;
function segPt(x1,y1,x2,y2,px,py){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;let t=L2>0?((px-x1)*dx+(py-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy));}
function padSD2(P,x,y){let dx=x-P.x,dy=y-P.y;
 if(P.rot){const c=P.c,sn=P.s;const nx=dx*c-dy*sn,ny=dx*sn+dy*c;dx=nx;dy=ny;}
 if(P.ell) return Math.hypot(dx,dy)-P.rmax;
 const qx=Math.abs(dx)-P.hx,qy=Math.abs(dy)-P.hy;
 return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0);}
const CLUSTER=['PWM_V','PWM_LU','PWM_U'];
const BX0=340,BY0=1600,BX1=480,BY1=1760;   // 集群局部区域
const inL=(x,y)=>x>BX0&&x<BX1&&y>BY0&&y<BY1;
let aLines=(await eda.pcb_PrimitiveLine.getAll())||[], aPads=(await eda.pcb_PrimitivePad.getAll())||[], aVias=(await eda.pcb_PrimitiveVia.getAll())||[];
let lines=aLines.filter(l=>inL(l.startX,l.startY)||inL(l.endX,l.endY));
let pads=aPads.filter(p=>inL(p.x,p.y));
let vias=aVias;
const P=[];
for(const p of pads){ const s=p.pad,t=Array.isArray(s)?String(s[0]).toUpperCase():'';
 const a=num(Array.isArray(s)?+s[1]:0),b=num(Array.isArray(s)?+s[2]:0);
 const rot=(num(p.rotation)*Math.PI)/180;
 let hr=0; const h=p.hole;
 if(typeof h==='number'&&h>0)hr=h/2; else if(Array.isArray(h)){for(const x of h)if(typeof x==='number'&&x>0){hr=x/2;break;}}
 else if(h&&typeof h==='object'&&typeof h.diameter==='number')hr=h.diameter/2;
 P.push({net:p.net,x:p.x,y:p.y,rot:rot?1:0,c:Math.cos(-rot),s:Math.sin(-rot),
  ell:(t.indexOf('CIRCLE')>=0||t.indexOf('ELLIPSE')>=0),rmax:Math.max(a,b)/2,hx:a/2,hy:b/2,hr}); }
function viaOK(net,x,y,vs){
 const r=8;
 for(const l of lines){ if(l.net===net) continue;
  if(segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-r-CL<0) return false; }
 for(const p of P){ if(p.net===net) continue; if(padSD2(p,x,y)-r-CL<0) return false;
  if(p.hr>0 && Math.hypot(p.x-x,p.y-y)-6-p.hr-HH<0) return false; }
 for(const v of vs){ if(v.net===net&&Math.abs(v._nx-x)<0.01&&Math.abs(v._ny-y)<0.01) continue;
  const px=v._nx!==undefined?v._nx:v.x, py=v._ny!==undefined?v._ny:v.y;
  const d=Math.hypot(px-x,py-y);
  if(d-num(v.diameter)/2-r-CL<0) return false;
  if(d-6-num(v.holeDiameter)/2-HH<0) return false; }
 return true; }
function segFree(net,x0,y0,x1,y1,vs){
 const L=Math.hypot(x1-x0,y1-y0), n=Math.max(3,Math.ceil(L));
 for(let t=0;t<=n;t++){ const x=x0+(x1-x0)*t/n, y=y0+(y1-y0)*t/n;
  for(const l of lines){ if(l.net===net) continue;
   if(segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-SW/2-CL<0) return false; }
  for(const p of P){ if(p.net===net) continue; if(padSD2(p,x,y)-SW/2-CL<0) return false; }
  for(const v of vs){ if(v.net===net) continue;
   const px=v._nx!==undefined?v._nx:v.x, py=v._ny!==undefined?v._ny:v.y;
   if(Math.hypot(px-x,py-y)-num(v.diameter)/2-SW/2-CL<0) return false; }
 }
 return true; }
function findStub(net,x0,y0,x1,y1,vs){
 if(segFree(net,x0,y0,x1,y1,vs)) return [[x1,y1]];
 const mx=(x0+x1)/2, my=(y0+y1)/2, dx=x1-x0, dy=y1-y0, L=Math.hypot(dx,dy)||1, nx=-dy/L, ny=dx/L;
 for(const off of [8,14,20,26,-8,-14,-20,-26]) for(const along of [0,0.25,-0.25]){
  const wx=mx+dx*along+nx*off, wy=my+dy*along+ny*off;
  if(segFree(net,x0,y0,wx,wy,vs)&&segFree(net,wx,wy,x1,y1,vs)) return [[wx,wy],[x1,y1]];
 }
 return null; }
// 群组迭代
const moved=new Map();
for(let iter=0; iter<10; iter++){
 const vs=vias.map(v=>{const m=moved.get(v.primitiveId); return m?{...v,_nx:m.nx,_ny:m.ny}:{...v,_nx:v.x,_ny:v.y};});
 let worst=null;
 for(let i=0;i<vs.length;i++)for(let j=i+1;j<vs.length;j++){
  const a=vs[i],b=vs[j];
  if(!CLUSTER.includes(a.net)&&!CLUSTER.includes(b.net)) continue;
  const g=Math.hypot(a._nx-b._nx,a._ny-b._ny)-6-6;
  if(g<HH && (!worst||g<worst.g)) worst={a,b,g}; }
 if(!worst) break;
 let done=false;
 for(const t of [worst.b, worst.a]){
  const cur=moved.get(t.primitiveId)||{ox:t.x,oy:t.y};
  const ox=cur.ox, oy=cur.oy;
  const others=vs.filter(v=>v.primitiveId!==t.primitiveId);
  let best=null;
  for(let di=-R;di<=R;di++)for(let dj=-R;dj<=R;dj++){
   const dist=Math.hypot(di,dj); if(dist<2||dist>R) continue;
   const x=+(ox+di).toFixed(1), y=+(oy+dj).toFixed(1);
   if(!viaOK(t.net,x,y,others)) continue;
   const st=findStub(t.net,ox,oy,x,y,others);
   if(!st) continue;
   if(!best||dist<best.dist) best={x,y,dist:+dist.toFixed(1),st:st.map(p=>[+p[0].toFixed(1),+p[1].toFixed(1)])};
  }
  if(best){ moved.set(t.primitiveId,{net:t.net,ox,oy,nx:best.x,ny:best.y,stub:best.st,dist:best.dist,id:t.primitiveId});
   // 立刻删旧线/旧孔并落新
   for(const l of lines){ if(l.net!==t.net) continue;
    const a=Math.hypot(l.startX-ox,l.startY-oy), b=Math.hypot(l.endX-ox,l.endY-oy);
    if(Math.min(a,b)<3){ try{ await eda.pcb_PrimitiveLine.delete(l.primitiveId); }catch(e){} } }
   try{ await eda.pcb_PrimitiveVia.delete(t.primitiveId); }catch(e){}
   let px=ox,py=oy;
   for(const [wx,wy] of best.st){ try{ await eda.pcb_PrimitiveLine.create(t.net,1,px,py,wx,wy,SW,false); }catch(e){} px=wx; py=wy; }
   try{ await eda.pcb_PrimitiveVia.create(t.net,best.x,best.y,12,16); }catch(e){}
   lines=((await eda.pcb_PrimitiveLine.getAll())||[]).filter(l=>inL(l.startX,l.startY)||inL(l.endX,l.endY)); vias=(await eda.pcb_PrimitiveVia.getAll())||[];
   done=true; break; }
 }
 if(!done) break;
}
out.moved=[...moved.values()].map(m=>[m.net,m.ox,m.oy,'->',m.nx,m.ny,'dist',m.dist]);
out.nMoved=moved.size;
vias=(await eda.pcb_PrimitiveVia.getAll())||[];
let minG=1e9, at=null;
for(let i=0;i<vias.length;i++)for(let j=i+1;j<vias.length;j++){
 const g=Math.hypot(vias[i].x-vias[j].x,vias[i].y-vias[j].y)-6-6;
 if(g<minG){minG=g;at=[+vias[i].x.toFixed(0),+vias[i].y.toFixed(0),vias[i].net,vias[j].net];} }
out.minGapAfter=+minG.toFixed(2); out.atAfter=at;
try{await eda.pcb_Document.save();out.saved=true;}catch(e){}
} catch(e) { out.fatal=String(e).slice(0,150); }
return JSON.stringify(out).slice(0,1400);
