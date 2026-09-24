/* geom_router.js —— PCB-AI Toolkit 几何引擎 + 单层 A* 布线器
 * 在 EasyEDA 里执行:  python tools/qq.py tools/geom_router.js
 * 设计要点(全是踩坑换来的):
 *   - 点到铜边距离: 矩形必须用精确旋转框距; 圆/椭圆用半径; ★不许用对角线半径
 *   - 过孔贯穿所有层: 任何层都要算它; ★孔到孔(>=holeHH)同网也查
 *   - 通孔焊盘的"钻孔"必须单独建模
 *   - 障碍先按局部区域预筛; A* 开放列表用二叉堆(线性扫描会锁死主线程)
 * 用法:
 *   const G = await Geometry.build({box:[x0,y0,x1,y1], margin:60, clearance:6, holeHH:11.81});
 *   G.free(net,x,y,w,layer)                  // 线宽 w 的中心线能否放这里
 *   G.routeASTAR({net,layer,width,from,to})  // -> [[x,y],...] 或 null
 *   G.viaSlack(net,x,y,dia,drill)            // -> {slack,who}, slack>=0 合法
 *   G.placeVia(net,[x,y],dia,drill,search)   // -> {x,y,slack} 或 null(且必须压住本网铜)
 */
const Geometry = (() => {
  const num = v => (typeof v === 'number' && isFinite(v)) ? v : 0;
  const segPt = (x1,y1,x2,y2,px,py) => {
    const dx=x2-x1, dy=y2-y1, L2=dx*dx+dy*dy;
    let t = L2>0 ? ((px-x1)*dx+(py-y1)*dy)/L2 : 0; t = Math.max(0, Math.min(1, t));
    return Math.hypot(px-(x1+t*dx), py-(y1+t*dy));
  };
  const paddR = p => {
    const s=p.pad, t=Array.isArray(s)?String(s[0]).toUpperCase():'';
    const a=num(Array.isArray(s)?+s[1]:0), b=num(Array.isArray(s)?+s[2]:0);
    return (x,y) => {
      let dx=x-p.x, dy=y-p.y;
      const rot=num(p.rotation);   /* ★ EasyEDA 焊盘 rotation 是"弧度"(rad), 不是度! 按度算会把旋转框转反 */
      if (rot) { const c=Math.cos(-rot), sn=Math.sin(-rot), nx=dx*c-dy*sn, ny=dx*sn+dy*c; dx=nx; dy=ny; }
      if (t.indexOf('CIRCLE')>=0 || t.indexOf('ELLIPSE')>=0) return Math.hypot(dx,dy)-Math.max(a,b)/2;
      const qx=Math.abs(dx)-a/2, qy=Math.abs(dy)-b/2;      /* ★ 精确旋转框距 */
      return Math.hypot(Math.max(qx,0),Math.max(qy,0)) + Math.min(Math.max(qx,qy),0);
    };
  };
  const padHoleR = p => {
    const h=p.hole;
    if (typeof h==='number' && h>0) return h/2;
    if (Array.isArray(h)) { for (const v of h) if (typeof v==='number' && v>0) return v/2; }
    return 0;
  };
  /* 焊盘只在本层(或通孔)才挡线: 底层焊盘不该把顶层走线判死(否则过度保守, A* 会找不到路) */
  const padBlocksLayer = (p,layer) => {
    if (layer===undefined) return true;
    if (padHoleR(p)>0) return true;                       // 通孔: 各层都有铜
    return p.layer===undefined || p.layer===layer;
  };
  async function build(opt) {
    const CL=opt.clearance??6, HH=opt.holeHH??11.81, M=opt.margin??60, B=opt.box;
    const inB=(x,y,m)=>x>B[0]-(m||0)&&x<B[2]+(m||0)&&y>B[1]-(m||0)&&y<B[3]+(m||0);
    const lines=(await eda.pcb_PrimitiveLine.getAll())||[];
    const pads=(await eda.pcb_PrimitivePad.getAll())||[];
    const vias=(await eda.pcb_PrimitiveVia.getAll())||[];
    const L=lines.filter(l=>inB(l.startX,l.startY,M)||inB(l.endX,l.endY,M));
    const P=pads.filter(p=>inB(p.x,p.y,M)).map(p=>Object.assign({sd:paddR(p),hr:padHoleR(p)},p));
    const V=vias.filter(v=>inB(v.x,v.y,M));
    return {
      lines:L, pads:P, vias:V, CL:CL, HH:HH,
      /* freeWhy: 与 free 同判据, 但返回"被谁挡住" —— 排查/自检用; 注意 pad 不区分层(偏保守) */
      freeWhy(net,x,y,w,layer) {
        for (const l of L) { if (l.net===net) continue; if (layer!==undefined && l.layer!==layer) continue;
          if (segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-w/2-CL<0)
            return {ok:false,why:'line',obj:'L'+l.layer+' '+(l.net||''),layer:l.layer}; }
        for (const p of P) { if (p.net===net) continue; if (!padBlocksLayer(p,layer)) continue;
          if (p.sd(x,y)-w/2-CL<0)
            return {ok:false,why:'pad',obj:(p.net||'')+'@L'+(p.layer===undefined?'?':p.layer),layer:p.layer}; }
        for (const v of V) { if (v.net===net) continue;
          if (Math.hypot(v.x-x,v.y-y)-num(v.diameter)/2-w/2-CL<0)
            return {ok:false,why:'via',obj:(v.net||''),layer:undefined}; }
        return {ok:true,why:'',obj:'',layer:undefined};
      },
      free(net,x,y,w,layer) { return this.freeWhy(net,x,y,w,layer).ok; },
      viaSlack(net,x,y,dia,drill) {
        const r=num(dia)/2, hr=num(drill)/2; let w=1e9, who='';
        const upd=(s,tag)=>{ if (s<w) { w=s; who=tag; } };
        for (const l of L) if (l.net!==net)
          upd(segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2-r-CL,'L'+l.layer+' '+l.net);
        for (const p of P) { if (p.net!==net) upd(p.sd(x,y)-r-CL,'pad '+p.net);
          if (p.hr>0) upd(Math.hypot(p.x-x,p.y-y)-hr-p.hr-HH,'holePad '+p.net); }
        for (const v of V) { const d=Math.hypot(v.x-x,v.y-y);
          if (d<1e-6) continue;                                  /* ★ 不能把自己算成障碍 */
          if (v.net!==net) upd(d-num(v.diameter)/2-r-CL,'via '+v.net);  /* ★ 同网铜本就相连, 不查间距 */
          upd(d-hr-num(v.holeDiameter)/2-HH,'hh '+v.net); }      /* ★ 孔到孔: 同网也必须查 */
        return {slack:w, who:who};
      },
      placeVia(net,near,dia,drill,search,step) {
        search=search??30; step=step??1;
        const r=num(dia)/2; let best=null;
        for (let i=-search;i<=search;i+=step) for (let j=-search;j<=search;j+=step) {
          const x=near[0]+i, y=near[1]+j;
          const s=this.viaSlack(net,x,y,dia,drill); if (s.slack<0) continue;
          let touch=false;
          for (const l of L) if (l.net===net && segPt(l.startX,l.startY,l.endX,l.endY,x,y)<=r+num(l.lineWidth)/2) { touch=true; break; }
          if (!touch) for (const p of P) if (p.net===net && p.sd(x,y)<=r) { touch=true; break; }
          if (!touch) continue;                                  /* 保证仍与本网铜相连 */
          const sc=-Math.hypot(i,j);
          if (!best || sc>best.sc) best={x:+x.toFixed(2),y:+y.toFixed(2),slack:+s.slack.toFixed(2),who:s.who,sc:sc};
        }
        return best;
      },
      routeASTAR(o) {
        const net=o.net, layer=o.layer, w=o.width??5, step=o.step??1, S=o.from, T=o.to;
        const nx=Math.round((B[2]-B[0])/step)+1, ny=Math.round((B[3]-B[1])/step)+1, N=nx*ny;
        const fr=new Uint8Array(N);
        for (let i=0;i<nx;i++) for (let j=0;j<ny;j++) fr[j*nx+i]=this.free(net,B[0]+i*step,B[1]+j*step,w,layer)?1:0;
        const toI=(x,y)=>[Math.round((x-B[0])/step),Math.round((y-B[1])/step)];
        const s=toI(S[0],S[1]), t=toI(T[0],T[1]);
        if (s[0]<0||s[1]<0||s[0]>=nx||s[1]>=ny||t[0]<0||t[1]<0||t[0]>=nx||t[1]>=ny) return null;
        fr[s[1]*nx+s[0]]=1; fr[t[1]*nx+t[0]]=1;
        const g=new Float32Array(N).fill(1e9), f=new Float32Array(N).fill(1e9), pv=new Int32Array(N).fill(-1), H=[];
        const push=k=>{H.push(k);let c=H.length-1;while(c>0){const p=(c-1)>>1;if(f[H[p]]<=f[H[c]])break;const x=H[p];H[p]=H[c];H[c]=x;c=p;}};
        const pop=()=>{const top=H[0],last=H.pop();if(H.length){H[0]=last;let p=0;for(;;){const l=2*p+1,r=l+1;let m=p;
          if(l<H.length&&f[H[l]]<f[H[m]])m=l; if(r<H.length&&f[H[r]]<f[H[m]])m=r; if(m===p)break;const x=H[m];H[m]=H[p];H[p]=x;p=m;}}return top;};
        const kS=s[1]*nx+s[0], kT=t[1]*nx+t[0];
        g[kS]=0; f[kS]=Math.hypot(t[0]-s[0],t[1]-s[1]); push(kS);
        const DX=[1,-1,0,0,1,1,-1,-1], DY=[0,0,1,-1,1,-1,1,-1], DW=[1,1,1,1,1.414,1.414,1.414,1.414];
        let ok=false, guard=0;
        while (H.length && guard++<3000000) {
          const k=pop(); if (k===kT) { ok=true; break; }
          const ci=k%nx, cj=(k-ci)/nx, gc=g[k];
          for (let d=0; d<8; d++) { const ni=ci+DX[d], nj=cj+DY[d];
            if (ni<0||nj<0||ni>=nx||nj>=ny) continue; const kk=nj*nx+ni; if (!fr[kk]) continue;
            const ng=gc+DW[d]; if (ng<g[kk]-1e-6) { g[kk]=ng; pv[kk]=k; f[kk]=ng+Math.hypot(t[0]-ni,t[1]-nj); push(kk); } }
        }
        if (!ok) return null;
        let path=[], cur=kT;
        while (cur>=0) { const i=cur%nx, j=(cur-i)/nx; path.push([+(B[0]+i*step).toFixed(2),+(B[1]+j*step).toFixed(2)]); cur=pv[cur]; }
        path.reverse(); path[0]=S; path[path.length-1]=T;
        const freeAt=(x,y)=>{const i=Math.round((x-B[0])/step),j=Math.round((y-B[1])/step);return i>=0&&j>=0&&i<nx&&j<ny&&fr[j*nx+i];};
        const clr=(a,b)=>{const d=Math.hypot(b[0]-a[0],b[1]-a[1]),n=Math.ceil(d/step);
          for(let q=1;q<n;q++) if(!freeAt(a[0]+(b[0]-a[0])*q/n, a[1]+(b[1]-a[1])*q/n)) return false; return true;};
        const out=[path[0]]; let i0=0;
        while (i0<path.length-1) { let j2=path.length-1; while (j2>i0+1 && !clr(path[i0],path[j2])) j2--; out.push(path[j2]); i0=j2; }
        return out;
      }
    };
  }
  return { build: build, paddR: paddR, segPt: segPt, padHoleR: padHoleR };
})();
