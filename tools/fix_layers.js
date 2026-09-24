// 把 layer 21 -> 15 (INNER_1), layer 22 -> 16 (INNER_2)
const L=await eda.pcb_PrimitiveLine.getAll();
const V=await eda.pcb_PrimitiveVia.getAll();
let movedL=0, movedV=0, errL=0, errV=0;
for(const l of L){
  let lay=null; try{ lay=Number(l.getState_Layer()); }catch(e){}
  let tgt=null;
  if(lay===21) tgt=15; else if(lay===22) tgt=16;
  if(tgt===null) continue;
  try{ l.setState_Layer(tgt); await l.done(); movedL++; }catch(e){ errL++; }
}
for(const v of V){
  let lay=null; try{ lay=Number(v.getState_Layer()); }catch(e){}
  let tgt=null;
  if(lay===21) tgt=15; else if(lay===22) tgt=16;
  if(tgt===null) continue;
  try{ v.setState_Layer(tgt); await v.done(); movedV++; }catch(e){ errV++; }
}
// 复核
const after={};
for(const l of L){ let lay=null; try{ lay=String(l.getState_Layer()); }catch(e){} after[lay]=(after[lay]||0)+1; }
return JSON.stringify({movedLines:movedL, movedVias:movedV, errLines:errL, errVias:errV, afterLayers:after});
