const out = {};
const P = (await eda.pcb_PrimitivePour.getAll()) || [];
out.n = P.length;
for (const p of P) {
  try { await p.rebuildCopperRegion(); out[p.layer] = 'ok'; } catch (e) { out[p.layer] = 'ERR ' + String(e).slice(0, 80); }
  await new Promise(r => setTimeout(r, 2500));
}
await new Promise(r => setTimeout(r, 5000));
try { await eda.pcb_Document.save(); out.saved = true; } catch (e) {}
out.after = ((await eda.pcb_PrimitivePour.getAll()) || []).length;
out.poured = ((await eda.pcb_PrimitivePoured.getAll()) || []).length;
return JSON.stringify(out, null, 1).slice(0, 900);
