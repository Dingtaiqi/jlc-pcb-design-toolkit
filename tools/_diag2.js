/* _diag2.js —— 关键取证: getAll() 返回的普通对象里到底有哪些字段? (引擎依赖的字段是否真实存在) */
const out={};
const L=(await eda.pcb_PrimitiveLine.getAll())||[];
const V=(await eda.pcb_PrimitiveVia.getAll())||[];
const P=(await eda.pcb_PrimitivePad.getAll())||[];
const l=L.find(o=>typeof o.startX==='number')||L[0];
const v=V[0], p=P.find(o=>o.hole)||P[0];
out.lineKeys=Object.keys(l||{});
out.lineVals={startX:l&&l.startX,startY:l&&l.startY,endX:l&&l.endX,endY:l&&l.endY,lineWidth:l&&l.lineWidth,net:l&&String(l.net),layer:l&&l.layer,
  gs_width:l&&(l.getState_LineWidth?l.getState_LineWidth():'NO_GETTER')};
out.viaKeys=Object.keys(v||{});
out.viaVals={x:v&&v.x,y:v&&v.y,diameter:v&&v.diameter,holeDiameter:v&&v.holeDiameter,net:v&&String(v.net),
  gs_dia:v&&(v.getState_Diameter?v.getState_Diameter():'NO_GETTER'),gs_hole:v&&(v.getState_HoleDiameter?v.getState_HoleDiameter():'NO_GETTER')};
out.padKeys=Object.keys(p||{});
out.padVals={x:p&&p.x,y:p&&p.y,pad:JSON.stringify(p&&p.pad),hole:JSON.stringify(p&&p.hole),rotation:p&&p.rotation,layer:p&&p.layer,
  gs_rot:p&&(p.getState_Rotation?p.getState_Rotation():'NO_GETTER')};
/* 统计: 有多少线的 lineWidth 是数字 */
out.lineWidthOK=L.filter(o=>typeof o.lineWidth==='number'&&o.lineWidth>0).length; out.lineTotal=L.length;
out.viaDiaOK=V.filter(o=>typeof o.diameter==='number'&&o.diameter>0).length;
out.viaHoleOK=V.filter(o=>typeof o.holeDiameter==='number'&&o.holeDiameter>0).length; out.viaTotal=V.length;
return JSON.stringify(out).slice(0,2000);
