const NETS=['U','V','W','PGND'], TARGET=25, CL=6, VIA_D=16, VIA_R=8, HOLE=8;
const num=v=>(typeof v==='number'&&isFinite(v))?v:0;
function segPt(x1,y1,x2,y2,px,py){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;let t=L2>0?((px-x1)*dx+(py-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy));}
function padSD(p,x,y){const s=p.pad,t=Array.isArray(s)?String(s[0]).toUpperCase():'';
 const a=num(Array.isArray(s)?+s[1]:0),b=num(Array.isArray(s)?+s[2]:0);
 let dx=x-p.x,dy=y-p.y;const rot=(num(p.rotation)*Math.PI)/180;
 if(rot){const c=Math.cos(-rot),sn=Math.sin(-rot);const nx2=dx*c-dy*sn,ny2=dx*sn+dy*c;dx=nx2;dy=ny2;}
 if(t.indexOf('CIRCLE')>=0||t.indexOf('ELLIPSE')>=0)return Math.hypot(dx,dy)-Math.max(a,b)/2;
 const qx=Math.abs(dx)-a/2,qy=Math.abs(dy)-b/2;
 return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0);}
const out={steps:[],log:[]};
for (const NET of NETS) {
  let lines=(await eda.pcb_PrimitiveLine.getAll())||[], vias=(await eda.pcb_PrimitiveVia.getAll())||[], pads=(await eda.pcb_PrimitivePad.getAll())||[];
  const mine=lines.filter(l=>l.net===NET), before=[...new Set(mine.map(l=>+num(l.lineWidth).toFixed(2)))];
  // 每段: 计算合法最大线宽
  const plan=[];
  for (const l of mine) {
    const O=[];
    for(const o of lines) if(o.net!==NET&&o.layer===l.layer) O.push({sd:(x,y)=>segPt(o.startX,o.startY,o.endX,o.endY,x,y)-num(o.lineWidth)/2});
    for(const v of vias) if(v.net!==NET) O.push({sd:(x,y)=>Math.hypot(v.x-x,v.y-y)-num(v.diameter)/2});
    for(const p of pads) if(p.net!==NET&&(p.layer===12||p.layer===l.layer)) O.push({sd:(x,y)=>padSD(p,x,y)});
    const L=Math.hypot(l.endX-l.startX,l.endY-l.startY), n=Math.max(6,Math.ceil(L/2));
    let dmin=1e9;
    for(let t=0;t<=n;t++){const x=l.startX+(l.endX-l.startX)*t/n,y=l.startY+(l.endY-l.startY)*t/n;
      for(const o of O){const d=o.sd(x,y); if(d<dmin)dmin=d;}}
    const wmax=Math.max(0, 2*(dmin-CL));
    const wn=Math.min(TARGET, Math.floor(wmax*10)/10);
    plan.push({l, wn, dmin:+dmin.toFixed(2), cur:+num(l.lineWidth).toFixed(2)});
  }
  const ids=[];
  for (const p of plan) {
    if (p.wn <= p.cur + 0.4) { continue; }
    try { await eda.pcb_PrimitiveLine.delete(p.l.primitiveId);
      const r=await eda.pcb_PrimitiveLine.create(NET,p.l.layer,p.l.startX,p.l.startY,p.l.endX,p.l.endY,p.wn,false);
      ids.push(r&&(r.primitiveId||r)); } catch(e){ out.log.push('ERR '+NET+' '+String(e).slice(0,40)); }
  }
  await new Promise(r=>setTimeout(r,200));
  const after=((await eda.pcb_PrimitiveLine.getAll())||[]).filter(l=>l.net===NET);
  out.steps.push({net:NET, segs:mine.length, rebuilt:ids.length, wBefore:before,
    wAfter:[...new Set(after.map(l=>+num(l.lineWidth).toFixed(2)))],
    minSlack:+Math.min(...plan.map(p=>p.wn<=p.cur+0.4?99:(p.dmin-p.wn/2-CL))).toFixed(2),
    capped:plan.filter(p=>p.wn<TARGET-0.05&&p.wn>p.cur+0.4).length});
}
// 并联过孔: 每个相位网在原有孔附近补 1 个
const vids=[];
for (const NET of NETS) {
  const lines=(await eda.pcb_PrimitiveLine.getAll())||[], vias=(await eda.pcb_PrimitiveVia.getAll())||[], pads=(await eda.pcb_PrimitivePad.getAll())||[];
  const mine=vias.filter(v=>v.net===NET), myLines=lines.filter(l=>l.net===NET);
  if (!mine.length) continue;
  for (const mv of mine) {
    let best=null;
    for (let i=-30;i<=30;i+=2) for (let j=-30;j<=30;j+=2) {
      const x=mv.x+i, y=mv.y+j;
      if (Math.hypot(i,j)<12) continue;
      // 必须碰到同网铜(原有孔或线)
      let touch=false;
      for(const v of vias) if(v.net===NET){ if(Math.hypot(v.x-x,v.y-y) < VIA_R+num(v.diameter)/2-1){touch=true;break;} }
      if(!touch) for(const l of myLines){ if(segPt(l.startX,l.startY,l.endX,l.endY,x,y) < VIA_R+num(l.lineWidth)/2-1){touch=true;break;} }
      if(!touch) continue;
      let w=1e9, who='';
      for(const l of lines) if(l.net!==NET){const d=segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-VIA_R-CL; if(d<w){w=d;who='L'+l.layer+' '+l.net;}}
      for(const v of vias) if(v.net!==NET){const d=Math.hypot(v.x-x,v.y-y)-num(v.diameter)/2-VIA_R-CL; if(d<w){w=d;who='via '+v.net;}}
      for(const p of pads) if(p.net!==NET){const d=padSD(p,x,y)-VIA_R-CL; if(d<w){w=d;who='pad '+p.net;}}
      if(w<0) continue;
      const sc=w-0.05*Math.hypot(i,j);
      if(!best||sc>best.sc) best={x:+x.toFixed(2),y:+y.toFixed(2),slack:+w.toFixed(2),who,sc};
    }
    if(best){ try{ const r=await eda.pcb_PrimitiveVia.create(NET,best.x,best.y,HOLE,VIA_D); vids.push([NET,r&&(r.primitiveId||r),best.x,best.y,best.slack,best.who]); }catch(e){ out.log.push('VIA ERR '+String(e).slice(0,30)); } }
  }
}
out.addedVias=vids;
out.viaCounts={}; for(const v of ((await eda.pcb_PrimitiveVia.getAll())||[])) if(NETS.includes(v.net)) out.viaCounts[v.net]=(out.viaCounts[v.net]||0)+1;
try{await eda.pcb_Document.save();out.saved=true;}catch(e){out.saveErr=String(e).slice(0,60);}
return JSON.stringify(out);
