/* _diag.js —— 取证: 焊盘形状到底长什么样? 为什么 A* 找不到路? (只读) */
const out={};
const fin=v=>typeof v==='number'&&isFinite(v);
const L=((await eda.pcb_PrimitiveLine.getAll())||[]).filter(l=>fin(l.startX)&&fin(l.endX));
const P=(await eda.pcb_PrimitivePad.getAll())||[];
const V=(await eda.pcb_PrimitiveVia.getAll())||[];

/* 1) 焊盘原始字段长什么样(取几种不同的) */
const seen={};
for (const p of P){
  const k=String(p.pad).slice(0,40).replace(/[0-9.]+/g,'#');
  if (!seen[k]) seen[k]={raw:JSON.stringify(p.pad).slice(0,120),typeof:typeof p.pad,isArr:Array.isArray(p.pad),keys:Object.keys(p).slice(0,14),n:0};
  seen[k].n++;
}
out.padShapes=seen;

/* 2) 抽一块具体区域: 之前被判"被焊盘挡"的 GND 线中点 (1595,1961) */
const g=L.filter(l=>Math.abs((l.startX+l.endX)/2-1595)<3&&Math.abs((l.startY+l.endY)/2-1961)<3)[0];
if (g){
  const mx=(g.startX+g.endX)/2,my=(g.startY+g.endY)/2;
  out.blockCase={line:{net:g.net,layer:g.layer,w:g.lineWidth,mx:+mx.toFixed(1),my:+my.toFixed(1)},
    padsNear:P.filter(p=>fin(p.x)&&Math.hypot(p.x-mx,p.y-my)<15).map(p=>({
      net:p.net,layer:p.layer,d:+Math.hypot(p.x-mx,p.y-my).toFixed(2),
      pad:JSON.stringify(p.pad).slice(0,90),hole:JSON.stringify(p.hole),rot:p.rotation}))};
}else out.blockCase='没找到那条线';

/* 3) A* 失败的那条: net 1V1 / L1 最长(293.6mil) —— 看端点周围 */
const s=L.filter(l=>l.net==='1V1'&&l.layer===1).map(l=>({l:l,d:Math.hypot(l.endX-l.startX,l.endY-l.startY)})).sort((a,b)=>b.d-a.d)[0];
if (s){
  const l=s.l;
  const probe=(x,y,tag)=>{
    const o={tag:tag,x:+x.toFixed(1),y:+y.toFixed(1),pads:[],lines:[],vias:[]};
    for (const p of P) { if (!fin(p.x)) continue; const d=Math.hypot(p.x-x,p.y-y); if (d<14)
      o.pads.push({net:p.net,layer:p.layer,d:+d.toFixed(2),sd:+Geometry.paddR(p)(x,y).toFixed(2),pad:JSON.stringify(p.pad).slice(0,50)}); }
    for (const q of L) { if (q===l||q.net===l.net||q.layer!==l.layer) continue;
      const d=Geometry.segPt(q.startX,q.startY,q.endX,q.endY,x,y);
      if (d<14) o.lines.push({net:q.net,layer:q.layer,w:q.lineWidth,d:+d.toFixed(2),gap:+(d-q.lineWidth/2-l.lineWidth/2).toFixed(2)}); }
    for (const v of V) { if (!fin(v.x)||v.net===l.net) continue; const d=Math.hypot(v.x-x,v.y-y);
      if (d<14) o.vias.push({net:v.net,d:+d.toFixed(2),dia:v.diameter,hole:v.holeDiameter}); }
    return o;
  };
  out.astarCase={line:{net:l.net,layer:l.layer,w:l.lineWidth,len:+s.d.toFixed(1)},
                 start:probe(l.startX,l.startY,'start'),end:probe(l.endX,l.endY,'end'),
                 mid:probe((l.startX+l.endX)/2,(l.startY+l.endY)/2,'mid')};
  /* 沿线粗采样: 找出第一处"过不去"的位置 */
  const bad=[];
  for (let t=0;t<=1;t+=0.02){
    const x=l.startX+(l.endX-l.startX)*t, y=l.startY+(l.endY-l.startY)*t;
    let worst=null;
    for (const p of P) { if (p.net===l.net||!fin(p.x)) continue; const sd=Geometry.paddR(p)(x,y)-l.lineWidth/2-3;
      if (sd<0&&(!worst||sd<worst.v)) worst={v:+sd.toFixed(2),who:'pad '+(p.net||'')+'@L'+p.layer}; }
    for (const q of L) { if (q.net===l.net||q.layer!==l.layer) continue;
      const sd=Geometry.segPt(q.startX,q.startY,q.endX,q.endY,x,y)-q.lineWidth/2-l.lineWidth/2-3;
      if (sd<0&&(!worst||sd<worst.v)) worst={v:+sd.toFixed(2),who:'line '+q.net}; }
    if (worst) bad.push({t:+t.toFixed(2),x:+x.toFixed(0),y:+y.toFixed(0),v:worst.v,who:worst.who});
  }
  out.astarPathBlockers=bad.slice(0,10);
  out.astarPathBlockersCount=bad.length;
}
return JSON.stringify(out).slice(0,2400);
