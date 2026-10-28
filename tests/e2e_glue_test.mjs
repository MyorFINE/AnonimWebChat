// app.js E2EE ulanish mantig'ini (kalit yaratish, guruh kaliti, yangi a'zo, lichka, soxta yuboruvchi, kalit o'zgarishi) Node'da tekshiradi.
// Ishlatish: node tests/e2e_glue_test.mjs
import fs from "node:fs"; import vm from "node:vm"; import {webcrypto} from "node:crypto";
const root=new URL("../app/static/js/",import.meta.url).pathname;
let src=fs.readFileSync(root+"app.js","utf8");
const mark="\n})();\n\n\n/* ---------------- Uzun nickname";
if(!src.includes(mark)) throw new Error("marker");
src=src.replace("wraps.push({user_id: m.user_id, wrapped: await E2E.wrapRoomKey(X.rooms.get(ep), ep, X.priv.ecdhPriv, X.id, pk, m.user_id)});\n        } catch (_) {}","wraps.push({user_id: m.user_id, wrapped: await E2E.wrapRoomKey(X.rooms.get(ep), ep, X.priv.ecdhPriv, X.id, pk, m.user_id)});\n        } catch (e) { console.log(\"WRAP ERR\", e.message); }");
src=src.replace(mark,"\nglobalThis.__T={X,S,hydrate,sealFor,keyForActive,loadRoom,serveWraps,xInstall,xGenerate,peer,loadMembers,rotateRoom,e2eFetchBlob};\n})();\n\n\n/* x");
const stub=()=>{const f=function(){};return new Proxy(f,{get:(t,k)=>k===Symbol.toPrimitive?()=>"":k==="value"||k==="textContent"?"":k==="length"?0:k==="then"?undefined:stub(),apply:()=>stub(),construct:()=>stub(),set:()=>true});};
// ---- mock server
const srv={users:[],epochs:[],keys:[],mid:0};
function mkSC(me){
  return {supported:()=>true,wire:[],socket:()=>({send(){},close(){}}),
   async fetch(path,o={}){
     const u=new URL(path,"http://x"),m=(o.method||"GET").toUpperCase();let body={};try{body=o.body&&typeof o.body==="string"?JSON.parse(o.body):{}}catch(_){}
     const J=(s,j)=>({ok:s<300,status:s,async json(){return j},bytes:new TextEncoder().encode(JSON.stringify(j))});
     const p=u.pathname;
     if(p==="/api/members") return J(200,{members:srv.users.map(x=>({id:x.id,username:x.username,nickname:x.username,role:"user",ek:x.ecdh_pub,sk:x.sign_pub})),online_ids:[]});
     if(p==="/api/e2ee/keys"){const id=+u.searchParams.get("ids");const x=srv.users.find(z=>z.id===id);return J(200,{keys:x?{[id]:{e:x.ecdh_pub,s:x.sign_pub}}:{}})}
     if(p==="/api/e2ee/room") return J(200,{epoch:srv.epochs.length,epochs:srv.epochs,mine:srv.keys.filter(k=>k.user===me.id).map(k=>({epoch:k.epoch,wrapped:k.wrapped,by:k.by}))});
     if(p==="/api/e2ee/room/init"){ if(srv.epochs.length) return J(409,{detail:"bor"}); srv.epochs.push({epoch:1,check:body.check,by:me.id});body.wraps.forEach(w=>srv.keys.push({epoch:1,user:w.user_id,wrapped:w.wrapped,by:me.id}));return J(200,{ok:1})}
     if(p==="/api/e2ee/room/missing"){const out=[];srv.epochs.forEach(e=>srv.users.forEach(x=>{if(!srv.keys.some(k=>k.epoch===e.epoch&&k.user===x.id))out.push({epoch:e.epoch,user_id:x.id,ecdh_pub:x.ecdh_pub})}));return J(200,{missing:out})}
     if(p==="/api/e2ee/room/wrap"){body.wraps.forEach(w=>{if(!srv.keys.some(k=>k.epoch===body.epoch&&k.user===w.user_id))srv.keys.push({epoch:body.epoch,user:w.user_id,wrapped:w.wrapped,by:me.id})});return J(200,{ok:1})}
     if(p.startsWith("/api/e2ee/room/wrap/")){srv.keys=srv.keys.filter(k=>!(k.user===me.id&&k.epoch==+p.split("/").pop()));return J(200,{ok:1})}
     return J(404,{detail:"yo'q "+p});
   }};
}
async function client(id,name){
  const ctx={crypto:webcrypto,TextEncoder,TextDecoder,btoa,atob,console,URL,Uint8Array,Promise,setTimeout,clearTimeout,Blob,
    localStorage:{_d:{},getItem(k){return this._d[k]??null},setItem(k,v){this._d[k]=String(v)},removeItem(k){delete this._d[k]}},
    matchMedia:()=>({matches:false}),performance:{now:()=>Date.now()},requestAnimationFrame:()=>0,cancelAnimationFrame(){},
    document:stub(),navigator:{},addEventListener(){},location:{origin:"http://x",host:"x",protocol:"https:"},Image:class{},createImageBitmap:async()=>({width:1,height:1}),
    FormData:class{},MutationObserver:class{observe(){}},HTMLElement:class{},indexedDB:undefined};
  ctx.window=ctx;ctx.globalThis=ctx;vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(root+"e2ee.js","utf8"),ctx);
  ctx.SC=mkSC({id});
  vm.runInContext(src,ctx,{filename:"app.js"});
  const T=ctx.__T,E=ctx.E2E;
  const g=await T.xGenerate(name,"pw",100000);
  srv.users.push({id,username:name,ecdh_pub:g.keys.ecdh_pub,sign_pub:g.keys.sign_pub});
  T.S.me={id,username:name,nickname:name};T.S.token="t";T.S.members=[];
  await T.xInstall({id},name,g.ident,g.keys,100000,false);
  return {T,E,ctx};
}
const A=await client(1,"alice"), B=await client(2,"bob");
for(const c of [A,B]) await c.T.loadMembers();
await A.T.loadRoom();                       // alice yaratadi (epoch 1)
if(!A.T.X.rooms.has(1)) throw new Error("alice kalit yo'q");
await B.T.loadRoom();                       // bob: wrap bor (alice o'ragan)
if(!B.T.X.rooms.has(1)) throw new Error("bob kalit yo'q");
// yangi a'zo
const C3=await client(3,"carol"); await C3.T.loadMembers(); await A.T.loadMembers();
await C3.T.loadRoom(); if(C3.T.X.rooms.has(1)) throw new Error("carol hali kalitsiz bo'lishi kerak");
await A.T.serveWraps(); await new Promise(r=>setTimeout(r,300)); await C3.T.loadRoom(); if(!C3.T.X.rooms.has(1)) throw new Error("carol kalit olmadi");
// xabar: alice -> guruh; bob va carol ochadi
A.T.S.active={kind:"group"};
const ctxA=await A.T.keyForActive(); const env=await A.T.sealFor(ctxA,{t:"salom guruh",r:{id:1,nickname:"x",text:"q"}});
for(const c of [B,C3]){const m={id:5,user:{id:1,nickname:"alice"},to:null,e2e:env};await c.T.hydrate(m);
  if(m.content!=="salom guruh"||!m.verified||m.locked||m.bad) throw new Error("guruh ochilmadi "+JSON.stringify(m)); if(!m.reply||m.reply.nickname!=="x") throw new Error("reply")}
// lichka: bob -> alice
B.T.S.active={kind:"dm",uid:1}; const ctxB=await B.T.keyForActive(); const denv=await B.T.sealFor(ctxB,{t:"sir"});
const dm={id:6,user:{id:2,nickname:"bob"},to:1,e2e:denv}; await A.T.hydrate(dm);
if(dm.content!=="sir"||!dm.verified) throw new Error("dm");
const dm2={id:6,user:{id:2,nickname:"bob"},to:1,e2e:denv}; await C3.T.hydrate(dm2); if(!dm2.bad) throw new Error("carol lichkani ocha olmasligi kerak");
// soxta yuboruvchi
const forged={id:7,user:{id:2,nickname:"bob"},to:null,e2e:env}; await A.T.hydrate(forged); if(forged.verified&&!forged.bad) throw new Error("soxta yuboruvchi o'tdi");
// kalit o'zgarishi (TOFU)
const pins=JSON.parse(A.ctx.localStorage.getItem("termchat_pins_1")); pins[2]="XXXX"; A.ctx.localStorage.setItem("termchat_pins_1",JSON.stringify(pins)); A.T.X.peers.delete(2);
const m8={id:8,user:{id:2,nickname:"bob"},to:1,e2e:denv}; await A.T.hydrate(m8); if(!m8.bad) throw new Error("kalit o'zgarishi aniqlanmadi");
// kalitsiz xabar kutadi, keyin ochiladi
const D=await client(4,"dave"); await D.T.loadMembers(); await D.T.loadRoom();
const m9={id:9,user:{id:1,nickname:"alice"},to:null,e2e:env}; await D.T.hydrate(m9); if(!m9.locked||!D.T.X.pending.has(m9)) throw new Error("locked");
await A.T.serveWraps(); await new Promise(r=>setTimeout(r,300)); await D.T.loadRoom(); await new Promise(r=>setTimeout(r,200)); if(m9.locked||m9.content!=="salom guruh") throw new Error("pending qayta ochilmadi "+JSON.stringify(m9));
console.log("GLUE OK");
