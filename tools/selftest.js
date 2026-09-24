/* selftest.js —— 工具包只读自检 (需要桥接连上 EDA)
 * 用法:  python pcbai.py selftest      (pcbai.py 会自动前置注入 geom_router.js)
 *
 * 设计原则(★不要写死坐标 —— 板子天天被人手改, 写死必假报警):
 *   1) 样本全部从现场数据自适应挑取(工作框取"最密的一格", 不是板中心)
 *   2) 与"这块板子已 DRC 0 违规"这一事实互相印证: 用比板规更宽松的阈值跑引擎
 *   3) 正向/负向对照成对出现, 避免"永远返回 true"的假通过
 * 阈值故意取宽(clearance 5mil / holeHH 6mil), 用途是抓"模型级错误"
 * (例: 矩形焊盘误用对角线半径、过孔漏判孔到孔、把自己算成障碍), 不是评判设计余量。
 */
const out={pass:[],fail:[],info:{}};
const chk=(c,m)=>{(c?out.pass:out.fail).push(m);};
const fin=v=>typeof v==='number'&&isFinite(v);
try{
  const L0=((await eda.pcb_PrimitiveLine.getAll())||[]).filter(l=>fin(l.startX)&&fin(l.startY)&&fin(l.endX)&&fin(l.endY));
  const P0=(await eda.pcb_PrimitivePad.getAll())||[];
  const V0=(await eda.pcb_PrimitiveVia.getAll())||[];
  chk(L0.length>500 && P0.length>300, '图元读取: 线'+L0.length+' 焊盘'+P0.length+' 过孔'+V0.length);

  /* ---- 自适应工作框: 100mil 网格统计密度, 取最密一格为中心(板中心往往是空的) ---- */
  let X0=1e9,X1=-1e9,Y0=1e9,Y1=-1e9;
  const hist=new Map();
  const bump=(x,y)=>{ const k=Math.floor(x/100)+','+Math.floor(y/100); hist.set(k,(hist.get(k)||0)+1); };
  for (const l of L0){ X0=Math.min(X0,l.startX,l.endX); X1=Math.max(X1,l.startX,l.endX);
                       Y0=Math.min(Y0,l.startY,l.endY); Y1=Math.max(Y1,l.startY,l.endY);
                       bump(l.startX,l.startY); bump(l.endX,l.endY); }
  for (const v of V0) if (fin(v.x)&&fin(v.y)) bump(v.x,v.y);
  let best=null; for (const [k,c] of hist) if (!best||c>best.c) best={k:k,c:c};
  const bc=best.k.split(',').map(Number), cxm=bc[0]*100+50, cym=bc[1]*100+50;
  out.info.boardBox=[X0,Y0,X1,Y1].map(v=>+v.toFixed(0)); out.info.densestCell={cell:best.k,count:best.c};

  const inB=(l,B)=>l.startX>B[0]&&l.startX<B[2]&&l.startY>B[1]&&l.startY<B[3];
  let HW=160, B=null, G=null, cand=[];
  for (const hw of [160,240,320]){                       // 样本不够就扩大工作框
    HW=hw; B=[cxm-HW,cym-HW,cxm+HW,cym+HW];
    G=await Geometry.build({box:B,margin:60,clearance:5,holeHH:6});     // 宽松: 一致性/合法性
    cand=L0.filter(l=>inB(l,B)).slice(0,250);
    if (cand.length>=60) break;
  }
  out.info.box=B; out.info.halfWidth=HW;
  chk(G.lines.length>0&&G.pads.length>0&&G.vias.length>0,
      '几何构建: 框内 线'+G.lines.length+' 盘'+G.pads.length+' 孔'+G.vias.length);
  chk(G.lines.length<L0.length, '局部预筛生效: '+G.lines.length+' / 全板 '+L0.length+' 条线');

  /* ---- 正向/负向成对: 既有线中点本网必须"自由", 换个不存在的网名必须"被挡" ----
     板子已 DRC 0 违规 => 5mil 判据下既有线中点都应畅通; 不畅通 = 引擎模型错了 */
  let ok=0, badSame=[], badOtherLayer=0, negOk=0;
  for (const l of cand){
    const mx=(l.startX+l.endX)/2, my=(l.startY+l.endY)/2, w=fin(l.lineWidth)?l.lineWidth:5;
    const r=G.freeWhy(l.net,mx,my,w,l.layer);
    if (r.ok) ok++;
    else if (r.why==='pad' && r.layer!==l.layer) badOtherLayer++;   // 层不符: 说明 pad 层过滤没生效
    else badSame.push({net:l.net,layer:l.layer,why:r.why,obj:r.obj,x:+mx.toFixed(0),y:+my.toFixed(0)});
    if (!G.freeWhy('__no_such_net__',mx,my,w,l.layer).ok) negOk++;
  }
  out.info.lineSamples={n:cand.length,free:ok,blockedByOtherLayerPad:badOtherLayer,badSame:badSame.slice(0,5),negCtl:negOk};
  chk(cand.length>=50, '采样量足够: 框内 '+cand.length+' 条既有线(半宽 '+HW+'mil)');
  chk(badSame.length<=Math.max(1,Math.round(cand.length*0.01)),
      '引擎模型 ⇄ DRC 互证: '+ok+'/'+cand.length+' 条既有线中点判畅通, 同层误判 '+badSame.length+
      (badSame.length?(' 例 '+JSON.stringify(badSame[0])):''));
  chk(negOk===cand.length, '负向对照: 改不存在的网名后 '+negOk+'/'+cand.length+' 点判"被挡"(证明 free 真在看网)');

  /* ---- A* 算法功能测试: 挑一条中等长度既有线, 以它为中心单独开框(框必须装下两个端点!) ---- */
  let path=null, aerr='';
  const seeds=L0.filter(l=>fin(l.lineWidth)&&l.lineWidth>=4)
                .map(l=>({l:l,d:Math.hypot(l.endX-l.startX,l.endY-l.startY)}))
                .filter(o=>o.d>=40&&o.d<=300).sort((a,b)=>b.d-a.d);
  const seed=seeds.find(o=>Math.hypot(o.l.startX-cxm,o.l.startY-cym)<500)||seeds[0];
  if (!seed) aerr='全板没有 40~300mil 的样本线';
  else {
    const l=seed.l, pad=60;
    const AB=[Math.floor(Math.min(l.startX,l.endX)-pad),Math.floor(Math.min(l.startY,l.endY)-pad),
              Math.ceil(Math.max(l.startX,l.endX)+pad), Math.ceil(Math.max(l.startY,l.endY)+pad)];
    const GA=await Geometry.build({box:AB,margin:40,clearance:3,holeHH:6});
    path=GA.routeASTAR({net:l.net,layer:l.layer,width:l.lineWidth,step:1,
                        from:[l.startX,l.startY],to:[l.endX,l.endY]});
    out.info.astar={net:l.net,layer:l.layer,len:+seed.d.toFixed(1),box:AB,points:path?path.length:0};
    if (!path) aerr='A* 返回 null (net='+l.net+' L'+l.layer+', 框 '+JSON.stringify(AB)+')';
    else if (path.length<2) aerr='折线点太少';
    else {
      const e1=Math.hypot(path[0][0]-l.startX,path[0][1]-l.startY);
      const e2=Math.hypot(path[path.length-1][0]-l.endX,path[path.length-1][1]-l.endY);
      if (e1>0.01||e2>0.01) aerr='首尾未贴合(起'+e1.toFixed(2)+' 终'+e2.toFixed(2)+')';
    }
  }
  chk(path&&path.length>=2, 'A* 单层布线可算: '+(path?('折线 '+path.length+' 点, net '+out.info.astar.net+', '+out.info.astar.len+'mil'):('失败 - '+aerr)));

  /* ---- 过孔择位(dry-run, 不创建任何图元) ---- */
  const vs=G.vias.filter(v=>fin(v.x)&&fin(v.y)&&v.net)[0];
  let vc=null;
  if (vs) vc=G.placeVia(vs.net,[vs.x+20,vs.y+20],16,12,40,1);
  out.info.placeVia=vs?{net:vs.net,near:[+vs.x.toFixed(1),+vs.y.toFixed(1)],cand:vc}:null;
  chk(!!vc, '过孔择位(dry-run): '+(vc?('候选 '+vc.x+','+vc.y+' 余量 '+vc.slack+'mil 约束 '+vc.who):'未找到'));

  /* ---- 真实性对照: 框内既有过孔必须全部合法 ---- */
  let bad=[], minCL=1e9, n=0;
  for (const v of G.vias){
    if (!fin(v.x)||!fin(v.y)) continue; n++;
    const s=G.viaSlack(v.net,v.x,v.y,v.diameter||16,v.holeDiameter||12);
    if (s.slack<0) bad.push({net:v.net,x:+v.x.toFixed(0),y:+v.y.toFixed(0),slack:+s.slack.toFixed(2),who:s.who});
    if (s.slack<minCL) minCL=s.slack;
  }
  out.info.vias={n:n,illegal:bad.length,worst:bad.slice(0,4),minMargin5mil:+(minCL===1e9?0:minCL).toFixed(2)};
  chk(bad.length===0, '真实性对照: 框内 '+n+' 个既有过孔在 5mil/6mil 判据下全部合法'+
      (bad.length?(' (违规 '+bad.length+', 例 '+JSON.stringify(bad[0])+')'):''));

  /* ---- 全板孔到孔: 暴力扫全部过孔 + 通孔焊盘(与 pcbai.py holes 同判据) ----
     ★不要用"某条最紧约束是不是孔到孔"去反推最小孔距(哨兵值会自己骗自己) */
  const MM=39.3700787, HO=[];
  for (const v of V0){ if (!fin(v.x)||!fin(v.y)) continue;
    HO.push({k:'via',net:String(v.net),x:v.x,y:v.y,d:(fin(v.holeDiameter)&&v.holeDiameter>0)?v.holeDiameter:12}); }
  for (const p of P0){ const hr=Geometry.padHoleR(p)*2; if (!(hr>0)||!fin(p.x)) continue;
    HO.push({k:'pad',net:String(p.net),x:p.x,y:p.y,d:hr}); }
  let minGap=1e9, minWho=null, lt025=0;
  for (let i=0;i<HO.length;i++) for (let j=i+1;j<HO.length;j++){
    const a=HO[i], b=HO[j], gap=Math.hypot(a.x-b.x,a.y-b.y)-a.d/2-b.d/2;
    if (gap<minGap){ minGap=gap; minWho={gap:+gap.toFixed(2),mm:+(gap/MM).toFixed(3),
      a:{k:a.k,net:a.net,x:+a.x.toFixed(1),y:+a.y.toFixed(1)},b:{k:b.k,net:b.net,x:+b.x.toFixed(1),y:+b.y.toFixed(1)}}; }
    if (gap<0.25*MM) lt025++;
  }
  out.info.holeGap={holes:HO.length,minMils:+minGap.toFixed(2),minMm:+(minGap/MM).toFixed(3),below025mm:lt025,worst:minWho};
  chk(minGap>=0.25*MM, '全板孔到孔: '+out.info.holeGap.holes+' 孔, 最小 '+out.info.holeGap.minMm+
      ' mm ('+out.info.holeGap.minMils+' mil) vs 0.25mm 厂规 → '+(lt025===0?'达标':'不达标 '+lt025+' 对'));
  out.info.note='全板 '+out.info.holeGap.holes+' 个孔, 最小孔间距 '+out.info.holeGap.minMm+' mm';
}catch(e){ out.fail.push('异常: '+String(e).slice(0,160)); }
out.verdict=out.fail.length===0?'PASS':'FAIL';
return JSON.stringify(out).slice(0,2200);
