/* _diag3.js —— net 到底是什么类型? 以及 viaSlack 报出的最小孔距是谁? (只读) */
const out={};
const L=(await eda.pcb_PrimitiveLine.getAll())||[];
const V=(await eda.pcb_PrimitiveVia.getAll())||[];
const P=(await eda.pcb_PrimitivePad.getAll())||[];
/* 1) net 类型 */
const g1=L.filter(o=>String(o.net)==='GND')[0], g2=L.filter(o=>String(o.net)==='GND')[1];
out.netType={typeof:typeof g1.net, isString:typeof g1.net==='string', name:g1.net&&g1.net.name,
  keys:g1.net&&typeof g1.net==='object'?Object.keys(g1.net).slice(0,8):null,
  sameNetStrictEqual:(g1.net===g2.net), sameNetStringEqual:(String(g1.net)===String(g2.net)),
  json:JSON.stringify(g1.net).slice(0,80)};
const vg=V.filter(o=>String(o.net)==='GND')[0];
out.viaNet={typeof:typeof vg.net,sameAsLineNet:(vg.net===g1.net),strEq:(String(vg.net)===String(g1.net))};
/* 2) 全板 build, 复算 viaSlack 的最小 hh */
let X0=1e9,X1=-1e9,Y0=1e9,Y1=-1e9;
for (const l of L){ X0=Math.min(X0,l.startX,l.endX); X1=Math.max(X1,l.startX,l.endX);
                    Y0=Math.min(Y0,l.startY,l.endY); Y1=Math.max(Y1,l.startY,l.endY); }
const G=await Geometry.build({box:[X0-50,Y0-50,X1+50,Y1+50],margin:0,clearance:5,holeHH:9.84});
/* 全对全真值 */
const H=[];
for (const v of G.vias) H.push({k:'via',net:String(v.net),x:v.x,y:v.y,d:v.holeDiameter||12});
for (const p of G.pads){ const hr=Geometry.padHoleR(p)*2; if(hr>0) H.push({k:'pad',net:String(p.net),x:p.x,y:p.y,d:hr}); }
let minGap=1e9, minPair=null;
for (let i=0;i<H.length;i++) for (let j=i+1;j<H.length;j++){
  const a=H[i],b=H[j], gap=Math.hypot(a.x-b.x,a.y-b.y)-a.d/2-b.d/2;
  if (gap<minGap){ minGap=gap; minPair={gap:+gap.toFixed(2),a:a,b:b}; } }
out.truthMinGap={mils:+minGap.toFixed(2),mm:+(minGap*0.0254).toFixed(3),pair:minPair};
/* 引擎判定的最小 hh */
let worst=null;
for (const v of G.vias){
  const s=G.viaSlack(v.net,v.x,v.y,v.diameter,v.holeDiameter);
  if (String(s.who||'').indexOf('hh')===0 && (!worst||s.slack<worst.slack))
    worst={slack:+s.slack.toFixed(2),who:String(s.who),x:v.x,y:v.y,dia:v.diameter,drill:v.holeDiameter,net:String(v.net)};
}
out.modelMinHH=worst;
if (worst){
  const near=H.filter(h=>h!==null&&Math.abs(h.x-worst.x)<60&&Math.abs(h.y-worst.y)<60)
    .map(h=>({k:h.k,net:h.net,d:h.d,gap:+(Math.hypot(h.x-worst.x,h.y-worst.y)-h.d/2-worst.drill/2).toFixed(2),
              dc:+Math.hypot(h.x-worst.x,h.y-worst.y).toFixed(2)}))
    .filter(h=>h.gap<15).sort((a,b)=>a.gap-b.gap);
  out.nearHolesOfWorst=near.slice(0,6);
}
return JSON.stringify(out).slice(0,2200);
