const NET='$1N19139',CL=6,TW=5,HW=TW/2,TNEED=HW+CL;
const num=v=>(typeof v==='number'&&isFinite(v))?v:0;
function padSD(p,x,y){const s=p.pad,t=Array.isArray(s)?String(s[0]).toUpperCase():'';
 const a=num(Array.isArray(s)?+s[1]:0),b=num(Array.isArray(s)?+s[2]:0);
 let dx=x-p.x,dy=y-p.y;const rot=(num(p.rotation)*Math.PI)/180;
 if(rot){const c=Math.cos(-rot),sn=Math.sin(-rot);const nx2=dx*c-dy*sn,ny2=dx*sn+dy*c;dx=nx2;dy=ny2;}
 if(t.indexOf('CIRCLE')>=0||t.indexOf('ELLIPSE')>=0)return Math.hypot(dx,dy)-Math.max(a,b)/2;
 const qx=Math.abs(dx)-a/2,qy=Math.abs(dy)-b/2;
 return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0);}
function segPt(x1,y1,x2,y2,px,py){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;let t=L2>0?((px-x1)*dx+(py-y1)*dy)/L2:0;t=Math.max(0,Math.min(1,t));return Math.hypot(px-(x1+t*dx),py-(y1+t*dy));}
const pads=(await eda.pcb_PrimitivePad.getAll())||[],vias=(await eda.pcb_PrimitiveVia.getAll())||[],lines=(await eda.pcb_PrimitiveLine.getAll())||[];
const ball=pads.find(p=>p.net===NET&&p.padNumber==='AC5'),cap=pads.find(p=>p.net===NET&&p.padNumber!=='AC5');
const out={ball:[+ball.x.toFixed(2),+ball.y.toFixed(2)],cap:[+cap.x.toFixed(2),+cap.y.toFixed(2)],capPad:JSON.stringify(cap.pad)};
function obsNear(cx,cy,R){const O=[];
 for(const l of lines)if(l.net!==NET&&segPt(l.startX,l.startY,l.endX,l.endY,cx,cy)<R)
  O.push({tag:'L'+l.layer+' '+l.net,sd:(x,y)=>segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2});
 for(const v of vias)if(v.net!==NET&&Math.hypot(v.x-cx,v.y-cy)<R)
  O.push({tag:'via '+v.net,sd:(x,y)=>Math.hypot(v.x-x,v.y-y)-num(v.diameter)/2});
 for(const p of pads)if(p.net!==NET&&padSD(p,cx,cy)<R)
  O.push({tag:'pad '+p.net+'/'+p.padNumber,sd:(x,y)=>padSD(p,x,y)});
 return O;}
const OB=obsNear(ball.x,ball.y,70);out.obsBall=OB.length;
function minSlack(O,x,y,r){let w=1e9,who='';for(const o of O){const s=o.sd(x,y)-r-CL;if(s<w){w=s;who=o.tag;}}return{w,who};}
function stubOK(O,bx,by,vx,vy){const L=Math.hypot(vx-bx,vy-by),n=Math.max(4,Math.ceil(L/0.5));
 for(let t=1;t<n;t++){const x=bx+(vx-bx)*t/n,y=by+(vy-by)*t/n;
  for(const o of O)if(o.sd(x,y)-HW-CL<0)return false;}return true;}
let best=null;
for(const r of [7,6.5,6,8]){
 for(let a=0;a<360;a+=5)for(let dd=7;dd<=22;dd+=1){
  const rad=a*Math.PI/180,vx=+(ball.x+dd*Math.cos(rad)).toFixed(2),vy=+(ball.y+dd*Math.sin(rad)).toFixed(2);
  if(padSD(ball,vx,vy)<r+0.6)continue;
  const s=minSlack(OB,vx,vy,r);if(s.w<0)continue;
  if(!stubOK(OB,ball.x,ball.y,vx,vy))continue;
  const sc=s.w-0.15*dd;
  if(!best||sc>best.sc)best={r,vx,vy,dd,slack:+s.w.toFixed(2),who:s.who,sc};}
 if(best)break;}
out.dogbone=best;
const OC=obsNear(cap.x,cap.y,60);
let bestC=null;
for(const r of [8,7]){
 for(let i=-20;i<=20;i++)for(let j=-20;j<=20;j++){
  const x=+(cap.x+i*0.5).toFixed(2),y=+(cap.y+j*0.5).toFixed(2);
  if(padSD(cap,x,y)>r-1)continue;
  const s=minSlack(OC,x,y,r);if(s.w<0)continue;
  const sc=s.w-0.05*Math.hypot(i,j);
  if(!bestC||sc>bestC.sc)bestC={r,x,y,slack:+s.w.toFixed(2),who:s.who,sc};}
 if(bestC)break;}
out.capVia=bestC;
if(!best||!bestC){out.stage='no-via';return JSON.stringify(out);}
const A=[best.vx,best.vy],Bv=[bestC.x,bestC.y],mx=(A[0]+Bv[0])/2,my=(A[1]+Bv[1])/2;
const o16=[];
for(const l of lines)if(l.net!==NET&&l.layer===16&&segPt(l.startX,l.startY,l.endX,l.endY,mx,my)<250)
 o16.push({sd:(x,y)=>segPt(l.startX,l.startY,l.endX,l.endY,x,y)-num(l.lineWidth)/2});
for(const v of vias)if(v.net!==NET&&Math.hypot(v.x-mx,v.y-my)<250)
 o16.push({sd:(x,y)=>Math.hypot(v.x-x,v.y-y)-num(v.diameter)/2});
for(const p of pads)if(p.net!==NET&&p.layer===12)o16.push({sd:(x,y)=>padSD(p,x,y)});
out.obs16=o16.length;
function free16(x,y){for(const o of o16)if(o.sd(x,y)<TNEED)return false;return true;}
const BX=[Math.min(A[0],Bv[0])-30,Math.min(A[1],Bv[1])-30,Math.max(A[0],Bv[0])+30,Math.max(A[1],Bv[1])+30];
const nx=Math.round(BX[2]-BX[0])+1,ny=Math.round(BX[3]-BX[1])+1,N=nx*ny;
const fr=new Uint8Array(N);
for(let i=0;i<nx;i++)for(let j=0;j<ny;j++)fr[j*nx+i]=free16(BX[0]+i,BX[1]+j)?1:0;
const toI=(x,y)=>[Math.round(x-BX[0]),Math.round(y-BX[1])];
const s2=toI(A[0],A[1]),t2=toI(Bv[0],Bv[1]);
fr[s2[1]*nx+s2[0]]=1;fr[t2[1]*nx+t2[0]]=1;
const gv=new Float32Array(N).fill(1e9),fv=new Float32Array(N).fill(1e9),pv=new Int32Array(N).fill(-1),H=[];
function hpush(k){H.push(k);let c=H.length-1;while(c>0){const p=(c-1)>>1;if(fv[H[p]]<=fv[H[c]])break;const t=H[p];H[p]=H[c];H[c]=t;c=p;}}
function hpop(){const top=H[0],last=H.pop();if(H.length){H[0]=last;let p=0;for(;;){const l=2*p+1,r=l+1;let s3=p;
 if(l<H.length&&fv[H[l]]<fv[H[s3]])s3=l;if(r<H.length&&fv[H[r]]<fv[H[s3]])s3=r;if(s3===p)break;const t=H[s3];H[s3]=H[p];H[p]=t;p=s3;}}return top;}
const kS=s2[1]*nx+s2[0],kT=t2[1]*nx+t2[0];
gv[kS]=0;fv[kS]=Math.hypot(t2[0]-s2[0],t2[1]-s2[1]);hpush(kS);
const DX=[1,-1,0,0,1,1,-1,-1],DY=[0,0,1,-1,1,-1,1,-1],DW=[1,1,1,1,1.414,1.414,1.414,1.414];
let found=false,pops=0;const t0=Date.now();
while(H.length){const k=hpop();pops++;
 if(k===kT){found=true;break;}
 const ci=k%nx,cj=Math.floor(k/nx),gc=gv[k];
 for(let d=0;d<8;d++){const ni=ci+DX[d],nj=cj+DY[d];
  if(ni<0||nj<0||ni>=nx||nj>=ny)continue;const kk=nj*nx+ni;if(!fr[kk])continue;
  const ng=gc+DW[d];if(ng<gv[kk]-1e-6){gv[kk]=ng;pv[kk]=k;fv[kk]=ng+Math.hypot(t2[0]-ni,t2[1]-nj);hpush(kk);}}
 if(Date.now()-t0>30000){out.timeout=true;break;}}
out.astar={found,pops,ms:Date.now()-t0,grid:[nx,ny]};
if(!found)return JSON.stringify(out);
let path=[],cur=kT;
while(cur>=0){const i=cur%nx,j=Math.floor(cur/nx);path.push([+(BX[0]+i).toFixed(1),+(BX[1]+j).toFixed(1)]);cur=pv[cur];}
path.reverse();path[0]=A;path[path.length-1]=Bv;
function clr(x1,y1,x2,y2){const L=Math.hypot(x2-x1,y2-y1),n=Math.ceil(L);
 for(let t=1;t<n;t++){const x=x1+(x2-x1)*t/n,y=y1+(y2-y1)*t/n;
  const i=Math.round(x-BX[0]),j=Math.round(y-BX[1]);
  if(i<0||j<0||i>=nx||j>=ny)return false;if(!fr[j*nx+i])return false;}return true;}
const simp=[path[0]];let i0=0;
while(i0<path.length-1){let j2=path.length-1;
 while(j2>i0+1&&!clr(path[i0][0],path[i0][1],path[j2][0],path[j2][1]))j2--;
 simp.push(path[j2]);i0=j2;}
out.path=simp;out.segs=simp.length-1;
const created={};
try{const vA=await eda.pcb_PrimitiveVia.create(NET,bestC.x,bestC.y,8,bestC.r*2);created.capVia=vA&&(vA.primitiveId||vA);}catch(e){created.capViaErr=String(e).slice(0,60);}
try{const vB=await eda.pcb_PrimitiveVia.create(NET,best.vx,best.vy,8,best.r*2);created.ballVia=vB&&(vB.primitiveId||vB);}catch(e){created.ballViaErr=String(e).slice(0,60);}
try{const st=await eda.pcb_PrimitiveLine.create(NET,1,ball.x,ball.y,best.vx,best.vy,TW,false);created.stub=st&&(st.primitiveId||st);}catch(e){created.stubErr=String(e).slice(0,60);}
const ids=[];
for(let k=0;k<simp.length-1;k++){try{const r2=await eda.pcb_PrimitiveLine.create(NET,16,simp[k][0],simp[k][1],simp[k+1][0],simp[k+1][1],TW,false);ids.push(r2&&(r2.primitiveId||r2));}catch(e){ids.push('E');}}
created.track=ids;out.created=created;
try{await eda.pcb_Document.save();out.saved=true;}catch(e){out.saveErr=String(e).slice(0,70);}
return JSON.stringify(out);
