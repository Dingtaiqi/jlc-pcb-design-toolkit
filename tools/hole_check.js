/* hole_check.js —— 全板钻孔可制造性检查(只读, 不创建/不修改任何图元)
 * 用途: 投板前拿真数字对照工厂能力(例: JLC 4 层 孔到孔 >= 0.25mm; 免加钱档 0.3mm 钻 / 0.4mm 盘)
 * 用法:  python pcbai.py holes
 * 说明: 孔到孔按"孔壁到孔壁"(edge to edge)算, 同网也算 —— 同网孔太近一样钻不出来。
 */
const MIL=1/0.0254;
const fin=v=>typeof v==='number'&&isFinite(v);
const out={pass:[],fail:[],info:{}};
const chk=(c,m)=>{(c?out.pass:out.fail).push(m);};
try{
  const V=(await eda.pcb_PrimitiveVia.getAll())||[];
  const P=(await eda.pcb_PrimitivePad.getAll())||[];
  const L=(await eda.pcb_PrimitiveLine.getAll())||[];

  let X0=1e9,X1=-1e9,Y0=1e9,Y1=-1e9;
  for (const l of L){ if(!fin(l.startX))continue;
    X0=Math.min(X0,l.startX,l.endX); X1=Math.max(X1,l.startX,l.endX);
    Y0=Math.min(Y0,l.startY,l.endY); Y1=Math.max(Y1,l.startY,l.endY); }
  const G=await Geometry.build({box:[X0-50,Y0-50,X1+50,Y1+50],margin:0,clearance:5,holeHH:9.84});

  /* 收集所有孔: 过孔钻孔 + 通孔焊盘钻孔 */
  const H=[];
  for (const v of G.vias){ if(!fin(v.x)||!fin(v.y))continue;
    const d=(fin(v.holeDiameter)&&v.holeDiameter>0)?v.holeDiameter:12;
    H.push({k:'via',net:v.net,x:+v.x.toFixed(2),y:+v.y.toFixed(2),drill:+d.toFixed(2),pad:v.diameter}); }
  for (const p of G.pads){ const hr=Geometry.padHoleR(p)*2; if(!(hr>0)||!fin(p.x))continue;
    H.push({k:'pad',net:p.net,x:+p.x.toFixed(2),y:+p.y.toFixed(2),drill:+hr.toFixed(2),pad:null,no:p.padNumber,layer:p.layer}); }
  out.info.holes=H.length;
  out.info.byKind={via:H.filter(h=>h.k==='via').length, thPad:H.filter(h=>h.k==='pad').length};

  /* 全对全: 孔壁间距(同网也算) */
  let pairs=0, buckets={lt020:0,lt025:0,lt030:0,lt040:0}, worst=[];
  const TH=[0.20,0.25,0.30,0.40].map(v=>v*MIL);
  for (let i=0;i<H.length;i++) for (let j=i+1;j<H.length;j++){
    const a=H[i], b=H[j];
    const gap=Math.hypot(a.x-b.x,a.y-b.y)-a.drill/2-b.drill/2;
    pairs++;
    if (gap<TH[0]) buckets.lt020++; if (gap<TH[1]) buckets.lt025++;
    if (gap<TH[2]) buckets.lt030++; if (gap<TH[3]) buckets.lt040++;
    if (gap<TH[2]) worst.push({gap:+gap.toFixed(2), mm:+(gap/MIL).toFixed(3),
      a:{k:a.k,net:a.net,x:a.x,y:a.y,drill:a.drill}, b:{k:b.k,net:b.net,x:b.x,y:b.y,drill:b.drill}});
  }
  worst.sort((p,q)=>p.gap-q.gap);
  out.info.pairs=pairs;
  out.info.belowThreshold=buckets;
  out.info.worst=worst.slice(0,8);
  const minGap=worst.length?worst[0].gap:1e9;

  /* 钻孔直径与环宽 */
  let minDrill=1e9, minAnn=1e9, annWho='';
  for (const v of G.vias){ if(!fin(v.holeDiameter))continue;
    if (v.holeDiameter<minDrill) minDrill=v.holeDiameter;
    const a=(v.diameter-v.holeDiameter)/2; if (a<minAnn){minAnn=a;annWho='via '+v.net+' '+v.diameter+'/'+v.holeDiameter;} }
  for (const h of H) if (h.k==='pad' && h.drill<minDrill) minDrill=h.drill;
  out.info.minDrillMils=+(minDrill===1e9?0:minDrill).toFixed(2);
  out.info.minDrillMm=+((minDrill===1e9?0:minDrill)/MIL).toFixed(3);
  out.info.minAnnularMils=+(minAnn===1e9?0:minAnn).toFixed(2);
  out.info.minAnnularMm=+((minAnn===1e9?0:minAnn)/MIL).toFixed(3);
  out.info.minAnnularWho=annWho;

  chk(minGap>=0.25*MIL, '孔到孔最小间距 '+(worst.length?(worst[0].mm+' mm ('+worst[0].gap+' mil)'):'>=0.30mm')+
      ' 对照 0.25mm 厂规'+(minGap<0.25*MIL?(' ★差 '+(0.25*MIL-minGap).toFixed(2)+' mil'):''));
  chk(minDrill>=0.30*MIL-0.02, '最小钻孔 '+out.info.minDrillMm+' mm (免加钱档 0.3mm)');
  chk(minAnn>=0.05*MIL, '最小环宽 '+out.info.minAnnularMm+' mm ('+out.info.minAnnularMils+' mil)');
  out.info.note='孔壁间距分档: <0.20mm '+buckets.lt020+' 对, <0.25mm '+buckets.lt025+
                ' 对, <0.30mm '+buckets.lt030+' 对, <0.40mm '+buckets.lt040+' 对';
}catch(e){ out.fail.push('异常: '+String(e).slice(0,160)); }
out.verdict=out.fail.length===0?'PASS':'FAIL';
return JSON.stringify(out).slice(0,2400);
