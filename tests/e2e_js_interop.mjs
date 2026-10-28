// Node: e2ee.js (brauzer kodi) <-> Python mijoz mosligi. Ishlatish: node e2e_js_interop.mjs gen|check <fayl>
import fs from "node:fs";
import vm from "node:vm";
import {webcrypto} from "node:crypto";
const ctx = {crypto: webcrypto, TextEncoder, TextDecoder, btoa, atob, console};
ctx.globalThis = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(new URL("../app/static/js/e2ee.js", import.meta.url), "utf8"), ctx);
const E = ctx.E2E, mode = process.argv[2], file = process.argv[3];
const dec = new TextDecoder();

if (mode === "gen") {                       // JS yaratadi -> Python ochadi
  const kd = await E.deriveFromPassword("Alice", "secret-pass", 100000);
  const idA = await E.generateIdentity(), idB = await E.generateIdentity();
  const privA = await E.importPrivate(idA), privB = await E.importPrivate(idB);
  const blob = await E.wrapIdentity(idA, kd.kek, "Alice");
  const back = await E.unwrapIdentity(blob, kd.kek, "Alice");
  if (E.b64u(back.ecdhPkcs8) !== E.b64u(idA.ecdhPkcs8)) throw new Error("blob roundtrip");
  const rk = await E.newRoomKey();
  const peerB = await E.importPeer({e: idB.ecdhPub, s: idB.signPub});
  const peerA = await E.importPeer({e: idA.ecdhPub, s: idA.signPub});
  const wrapped = await E.wrapRoomKey(rk, 1, privA.ecdhPriv, 1, peerB.ecdh, 2);
  const check = await E.epochCheck(rk, 1);
  const gEnv = await E.sealMessage({sender: 1, peer: null, ep: 1, key: rk, signKey: privA.signPriv, payload: {t: "salom guruh 🌍"}});
  const kAB = await E.dmKey(privA.ecdhPriv, peerB.ecdh, 1, 2);
  const dEnv = await E.sealMessage({sender: 1, peer: 2, ep: 0, key: kAB, signKey: privA.signPriv, payload: {t: "lichka matni"}});
  const f = await E.encryptFile(new TextEncoder().encode("fayl mazmuni"));
  // JS o'zi ham ochadi
  const o = await E.openMessage(gEnv, {sender: 1, peer: null, key: rk, signKey: peerA.sign});
  if (!o.verified || o.payload.t !== "salom guruh 🌍") throw new Error("js roundtrip");
  fs.writeFileSync(file, JSON.stringify({auth: kd.auth, blob, idA: {e: idA.ecdhPub, s: idA.signPub}, idB: {e: idB.ecdhPub, s: idB.signPub},
    bPkcs8: {e: E.b64u(idB.ecdhPkcs8), s: E.b64u(idB.signPkcs8)}, rk: E.b64u(new Uint8Array(await ctx.crypto.subtle.exportKey("raw", rk))),
    wrapped, check, gEnv, dEnv, file: {key: f.key, blob: E.b64u(f.blob)}}));
} else if (mode === "check") {              // Python yaratadi -> JS ochadi
  const j = JSON.parse(fs.readFileSync(file, "utf8"));
  const kd = await E.deriveFromPassword("Alice", "secret-pass", 100000);
  if (kd.auth !== j.auth) throw new Error("kdf mos emas");
  const ident = await E.unwrapIdentity(j.blob, kd.kek, "Alice");
  const priv = await E.importPrivate(ident);
  const peer = await E.importPeer(j.peer);       // yuboruvchi (Python) ommaviy kalitlari
  const rk = await E.importRoomKey(E.unb64u(j.rk));
  const un = await E.unwrapRoomKey(j.wrapped, 1, priv.ecdhPriv, 2, peer.ecdh, 1);
  if (E.b64u(new Uint8Array(await ctx.crypto.subtle.exportKey("raw", un))) !== j.rk) throw new Error("unwrap");
  if (!(await E.verifyEpochCheck(j.check, rk, 1))) throw new Error("epoch check");
  const g = await E.openMessage(j.gEnv, {sender: 1, peer: null, key: rk, signKey: peer.sign});
  if (!g.verified || g.payload.t !== "py guruh") throw new Error("guruh");
  const kab = await E.dmKey(priv.ecdhPriv, peer.ecdh, 1, 2);
  const d = await E.openMessage(j.dEnv, {sender: 1, peer: 2, key: kab, signKey: peer.sign});
  if (!d.verified || d.payload.t !== "py lichka") throw new Error("lichka");
  const pt = await E.decryptFile(E.unb64u(j.file.blob), j.file.key);
  if (dec.decode(pt) !== "py fayl") throw new Error("fayl");
  // buzilgan imzo / boshqa yuboruvchi id -> rad
  let bad = false; try { const r = await E.openMessage(j.gEnv, {sender: 3, peer: null, key: rk, signKey: peer.sign}); bad = r.verified; } catch (_) { bad = false; }
  if (bad) throw new Error("soxta yuboruvchi qabul qilindi");
  console.log("JS<-PY OK");
}
