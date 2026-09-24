const out={};
try {
const RF='RF', TW=5, NEED=TW/2+6, STEP=1.5;
const S=[2717.3,1378], T=[2810,1452.6];
const OLD=[[2717.3,1378,2730.8,1391.5],[2730.8,1391.5,2752.2,1391.5],[2752.2,1391.5,2761.9,1401.2],
           [2761.9,1401.2,2761.9,1404.4],[2761.9,1404.4,2810,1452.6]];
const BADV=[[2745.4,1408],[2759.7,1429.2]], VR=24;
const num=v=>(typeof v==='number'&&isFinite(v))?v:0;
const BX=[2700,1360,2830,1465], MG=40;
function inBox(x,y,m){return x>BX[0]-m&&x<BX[2]+m&&y>BX[1]-m&&y<BX[3]+m;}
function segPt(x1,y1,x2,y2,px,py){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;let t=L2>0?((px-x1)*dx+(py-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy));}
function padSD2(P,x,y){ let dx=x-P.x,dy=y-P.y;
 if(P.rot){const c=P.c,sn=P.s;const nx2=dx*c-dy*sn,ny2=dx*sn+dy*c;dx=nx2;dy=ny2;}
 if(P.ell) return Math.hypot(dx,dy)-P.rmax;
 const qx=Math.abs(dx)-P.hx,qy=Math.abs(dy)-P.hy;
 return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0);}
const lines=(await eda.pcb_PrimitiveLine.getAll())||[], pads=(await eda.pcb_PrimitivePad.getAll())||[];
const L=[], P=[];
for(const l of lines){ if(l.net===RF||l.layer!==1||!l.net) continue;
 if(!(inBox(l.startX,l.startY,0)||inBox(l.endX,l.endY,0))) continue;
 L.push({x1:l.startX,y1:l.startY,x2:l.endX,y2:l.endY,hw:num(l.lineWidth)/2}); }
for(const p of pads){ if(p.net===RF||!(p.layer===1||p.layer===12)) continue;
 if(!inBox(p.x,p.y,0)) continue;
 const s=p.pad,t=Array.isArray(s)?String(s[0]).toUpperCase():'';
 const a=num(Array.isArray(s)?+s[1]:0),b=num(Array.isArray(s)?+s[2]:0);
 const rot=(num(p.rotation)*Math.PI)/180;
 P.push({x:p.x,y:p.y,rot:rot?1:0,c:Math.cos(-rot),s:Math.sin(-rot),
  ell:(t.indexOf('CIRCLE')>=0||t.indexOf('ELLIPSE')>=0),rmax:Math.max(a,b)/2,hx:a/2,hy:b/2}); }
out.nLine=L.length; out.nPad=P.length;
function free(x,y){
 for(let i=0;i<L.length;i++){const l=L[i]; if(segPt(l.x1,l.y1,l.x2,l.y2,x,y)-l.hw<NEED) return false;}
 for(let i=0;i<P.length;i++){ if(padSD2(P[i],x,y)<NEED) return false;}
 for(let i=0;i<BADV.length;i++){ if(Math.hypot(BADV[i][0]-x,BADV[i][1]-y)<VR) return false;}
 return true; }
const t0=Date.now();
const nx=Math.round((BX[2]-BX[0])/STEP)+1, ny=Math.round((BX[3]-BX[1])/STEP)+1, N=nx*ny;
const fr=new Uint8Array(N);
for(let i=0;i<nx;i++)for(let j=0;j<ny;j++) fr[j*nx+i]=free(BX[0]+i*STEP,BX[1]+j*STEP)?1:0;
out.gridMs=Date.now()-t0; out.grid=[nx,ny];
const toI=(x,y)=>[Math.round((x-BX[0])/STEP),Math.round((y-BX[1])/STEP)];
const s2=toI(S[0],S[1]), t2=toI(T[0],T[1]);
let freeCnt=0; for(let k=0;k<N;k++) freeCnt+=fr[k];
out.freeCells=freeCnt; out.sIdx=s2; out.tIdx=t2;
if(s2[0]<0||s2[1]<0||s2[0]>=nx||s2[1]>=ny||t2[0]<0||t2[1]<0||t2[0]>=nx||t2[1]>=ny){out.err='端点越界';return JSON.stringify(out);}
fr[s2[1]*nx+s2[0]]=1; fr[t2[1]*nx+t2[0]]=1;
const gv=new Float32Array(N).fill(1e9),fv=new Float32Array(N).fill(1e9),pv=new Int32Array(N).fill(-1),H=[];
function hpush(k){H.push(k);let c=H.length-1;while(c>0){const p=(c-1)>>1;if(fv[H[p]]<=fv[H[c]])break;const t=H[p];H[p]=H[c];H[c]=t;c=p;}}
function hpop(){const top=H[0],last=H.pop();if(H.length){H[0]=last;let p=0;for(;;){const l=2*p+1,r=l+1;let s3=p;
 if(l<H.length&&fv[H[l]]<fv[H[s3]])s3=l;if(r<H.length&&fv[H[r]]<fv[H[s3]])s3=r;if(s3===p)break;const t=H[s3];H[s3]=H[p];H[p]=t;p=s3;}}return top;}
const kS=s2[1]*nx+s2[0], kT=t2[1]*nx+t2[0];
gv[kS]=0; fv[kS]=Math.hypot(t2[0]-s2[0],t2[1]-s2[1]); hpush(kS);
const DX=[1,-1,0,0,1,1,-1,-1],DY=[0,0,1,-1,1,-1,1,-1],DW=[1,1,1,1,1.414,1.414,1.414,1.414];
let found=false, pops=0;
while(H.length){ const k=hpop(); pops++;
 if(k===kT){found=true;break;}
 const ci=k%nx,cj=Math.floor(k/nx),gc=gv[k];
 for(let d=0;d<8;d++){const ni=ci+DX[d],nj=cj+DY[d];
  if(ni<0||nj<0||ni>=nx||nj>=ny)continue; const kk=nj*nx+ni; if(!fr[kk])continue;
  const ng=gc+DW[d]; if(ng<gv[kk]-1e-6){gv[kk]=ng;pv[kk]=k;fv[kk]=ng+Math.hypot(t2[0]-ni,t2[1]-nj);hpush(kk);}}}
out.found=found; out.pops=pops; out.astarMs=Date.now()-t0;
if(!found){ out.note='RF 段无合法新路径(周围太挤)'; return JSON.stringify(out); }
let path=[],cur=kT;
while(cur>=0){const i=cur%nx,j=Math.floor(cur/nx);path.push([+(BX[0]+i*STEP).toFixed(1),+(BX[1]+j*STEP).toFixed(1)]);cur=pv[cur];}
path.reverse(); path[0]=S; path[path.length-1]=T;
function clr(x1,y1,x2,y2){const LL=Math.hypot(x2-x1,y2-y1),n=Math.ceil(LL/STEP);
 for(let t=1;t<n;t++){const x=x1+(x2-x1)*t/n,y=y1+(y2-y1)*t/n; const i=Math.round((x-BX[0])/STEP),j=Math.round((y-BX[1])/STEP);
  if(i<0||j<0||i>=nx||j>=ny)return false; if(!fr[j*nx+i])return false;} return true;}
const simp=[path[0]]; let i0=0;
while(i0<path.length-1){let j2=path.length-1; while(j2>i0+1&&!clr(path[i0][0],path[i0][1],path[j2][0],path[j2][1]))j2--; simp.push(path[j2]); i0=j2;}
out.path=simp;
out.newLen=+simp.reduce((acc,p,k)=>k?acc+Math.hypot(p[0]-simp[k-1][0],p[1]-simp[k-1][1]):0,0).toFixed(1);
out.oldLen=+OLD.reduce((acc,e)=>acc+Math.hypot(e[2]-e[0],e[3]-e[1]),0).toFixed(1);
let dmin=1e9; for(const p of simp) for(const b of BADV) dmin=Math.min(dmin, Math.hypot(b[0]-p[0],b[1]-p[1])-VR);
out.viaClearance=+dmin.toFixed(1);
const del=[];
for(const l of lines){ if(l.net!==RF) continue;
 for(const e of OLD){ const m1=Math.hypot(l.startX-e[0],l.startY-e[1])+Math.hypot(l.endX-e[2],l.endY-e[3]);
  const m2=Math.hypot(l.startX-e[2],l.startY-e[3])+Math.hypot(l.endX-e[0],l.endY-e[1]);
  if(Math.min(m1,m2)<1.0){ try{ await eda.pcb_PrimitiveLine.delete(l.primitiveId); del.push(l.primitiveId);}catch(err){} break; } } }
out.deleted=del.length;
const ids=[];
for(let k=0;k<simp.length-1;k++){ try{ const r=await eda.pcb_PrimitiveLine.create(RF,1,simp[k][0],simp[k][1],simp[k+1][0],simp[k+1][1],TW,false); ids.push(String((r&&(r.primitiveId||r))||'')); }catch(e){ ids.push('E'); } }
out.created=ids;
try{await eda.pcb_Document.save();out.saved=true;}catch(e){out.saveErr=String(e).slice(0,50);}
} catch(e) { out.fatal=String(e).slice(0,150); out.stack=String((e&&e.stack)||'').split('\n').slice(0,2).join('|').slice(0,200); }
return JSON.stringify(out).slice(0,1800);
