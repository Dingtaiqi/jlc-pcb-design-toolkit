/* _ping.js —— 最小探活: EDA 主线程还转不转 (只读) */
const L=(await eda.pcb_PrimitiveLine.getAll())||[];
const P=(await eda.pcb_PrimitivePad.getAll())||[];
const V=(await eda.pcb_PrimitiveVia.getAll())||[];
return JSON.stringify({lines:L.length,pads:P.length,vias:V.length,ok:true});
