/* Anonim Chat by Hevorix — uchdan-uchga shifrlash (E2EE), brauzer tomoni (WebCrypto).
   Bu fayl protokolning YAGONA mijoz tomoni: serverda ochiq matn, guruh kaliti yoki maxfiy kalit hech qachon bo'lmaydi.

   Primitivlar:  ECDH P-256 · ECDSA P-256/SHA-256 · HKDF-SHA256 · AES-256-GCM · PBKDF2-SHA256 (parol -> kalit)
   Konvert:      "e2e1:" + b64url(JSON {v:1, k:"g"|"d", ep, n:iv, c:shifr, s:imzo})
   AAD:          "ac/e2e1|<xona>|<yuboruvchi id>|<epoch>"  (xona: "g" yoki "d:<kichik id>:<katta id>")
   Imzo:         ECDSA(AAD || iv || shifr) — server yoki boshqa a'zo yuboruvchi nomidan soxta xabar yarata olmaydi. */
"use strict";
(root => {
const enc = new TextEncoder(), dec = new TextDecoder();
const subtle = () => root.crypto.subtle;
const KDF_DEFAULT = 600000;

/* ---------------- baytlar ---------------- */
const b64u = u8 => { let s = ""; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); };
const unb64u = s => { s = String(s).replace(/-/g, "+").replace(/_/g, "/"); s += "=".repeat((4 - s.length % 4) % 4); return Uint8Array.from(atob(s), c => c.charCodeAt(0)); };
const cat = (...p) => { const o = new Uint8Array(p.reduce((n, x) => n + x.length, 0)); let k = 0; for (const x of p) { o.set(x, k); k += x.length; } return o; };
const hex = u8 => Array.from(u8, b => b.toString(16).padStart(2, "0")).join("");
const rnd = n => root.crypto.getRandomValues(new Uint8Array(n));
const ECDH = {name: "ECDH", namedCurve: "P-256"}, ECDSA = {name: "ECDSA", namedCurve: "P-256"};

/* ---------------- inspektor uchun izlar (faqat xotirada, oxirgi 40 ta) ---------------- */
const trace = [];
function note(entry) { entry.ts = Date.now(); trace.push(entry); while (trace.length > 40) trace.shift(); }

/* ---------------- parol -> (kalit o'rash kaliti, serverga boradigan kirish kaliti) ---------------- */
async function deriveFromPassword(username, password, iter) {
  iter = iter || KDF_DEFAULT;
  const salt = new Uint8Array(await subtle().digest("SHA-256", enc.encode("anonim-chat/e2ee/v1/" + String(username).trim().toLowerCase())));
  const base = await subtle().importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = new Uint8Array(await subtle().deriveBits({name: "PBKDF2", hash: "SHA-256", salt, iterations: iter}, base, 512));
  const kek = await subtle().importKey("raw", bits.slice(0, 32), "AES-GCM", false, ["encrypt", "decrypt"]);
  return {kek, auth: hex(bits.slice(32, 64)), iter};      // `auth` serverga ketadi; `kek` hech qachon qurilmadan chiqmaydi
}

/* ---------------- shaxsiy kalitlar ---------------- */
async function generateIdentity() {
  const e = await subtle().generateKey(ECDH, true, ["deriveBits"]);
  const s = await subtle().generateKey(ECDSA, true, ["sign", "verify"]);
  return {
    ecdhPkcs8: new Uint8Array(await subtle().exportKey("pkcs8", e.privateKey)),
    signPkcs8: new Uint8Array(await subtle().exportKey("pkcs8", s.privateKey)),
    ecdhPub: b64u(new Uint8Array(await subtle().exportKey("raw", e.publicKey))),
    signPub: b64u(new Uint8Array(await subtle().exportKey("raw", s.publicKey))),
  };
}
async function importPrivate(ident) {            // qurilmada saqlanadigan nusxa: EKSPORT QILIB BO'LMAYDI
  return {
    ecdhPriv: await subtle().importKey("pkcs8", ident.ecdhPkcs8, ECDH, false, ["deriveBits"]),
    signPriv: await subtle().importKey("pkcs8", ident.signPkcs8, ECDSA, false, ["sign"]),
  };
}
const blobAad = username => enc.encode("ac/keyblob/v1|" + String(username).trim().toLowerCase());
async function wrapIdentity(ident, kek, username) {
  const iv = rnd(12);
  const plain = enc.encode(JSON.stringify({e: b64u(ident.ecdhPkcs8), s: b64u(ident.signPkcs8)}));
  const ct = new Uint8Array(await subtle().encrypt({name: "AES-GCM", iv, additionalData: blobAad(username)}, kek, plain));
  return JSON.stringify({v: 1, n: b64u(iv), c: b64u(ct)});
}
async function unwrapIdentity(blob, kek, username) {      // noto'g'ri parol -> istisno (AES-GCM teg tekshiruvi)
  const o = JSON.parse(blob);
  const plain = await subtle().decrypt({name: "AES-GCM", iv: unb64u(o.n), additionalData: blobAad(username)}, kek, unb64u(o.c));
  const j = JSON.parse(dec.decode(plain));
  return {ecdhPkcs8: unb64u(j.e), signPkcs8: unb64u(j.s)};
}
async function fingerprint(ecdhPub, signPub) {
  const h = new Uint8Array(await subtle().digest("SHA-256", cat(unb64u(ecdhPub), unb64u(signPub))));
  return (hex(h.slice(0, 16)).match(/.{4}/g) || []).join(" ").toUpperCase();
}
const importEcdhPub = b => subtle().importKey("raw", unb64u(b), ECDH, false, []);
async function importPeer(keys) {                         // keys = {e, s} (b64u) — serverdan kelgan OMMAVIY kalitlar
  return {
    e: keys.e, s: keys.s,
    ecdh: await subtle().importKey("raw", unb64u(keys.e), ECDH, false, []),
    sign: await subtle().importKey("raw", unb64u(keys.s), ECDSA, false, ["verify"]),
    fp: await fingerprint(keys.e, keys.s),
  };
}

/* ---------------- xabar konverti ---------------- */
const roomTag = (a, b) => (a == null ? "g" : "d:" + Math.min(a, b) + ":" + Math.max(a, b));
const aadOf = (room, sender, ep) => enc.encode("ac/e2e1|" + room + "|" + sender + "|" + ep);

async function dmKey(myEcdhPriv, peerEcdhPub, a, b) {
  const bits = await subtle().deriveBits({name: "ECDH", public: peerEcdhPub}, myEcdhPriv, 256);
  const hk = await subtle().importKey("raw", bits, "HKDF", false, ["deriveKey"]);
  return subtle().deriveKey({name: "HKDF", hash: "SHA-256", salt: enc.encode("ac/dm/v1|" + Math.min(a, b) + "|" + Math.max(a, b)), info: enc.encode("msg")},
    hk, {name: "AES-GCM", length: 256}, false, ["encrypt", "decrypt"]);
}

function padded(obj) {                                    // uzunlikni yashirish: 64 baytga to'ldiriladi
  const L = enc.encode(JSON.stringify(Object.assign({}, obj, {p: ""}))).length;
  return enc.encode(JSON.stringify(Object.assign({}, obj, {p: "0".repeat((64 - L % 64) % 64)})));
}

/* a: yuboruvchi id, b: lichkada qabul qiluvchi id (guruhda null), ep: guruh kaliti avlodi (lichkada 0) */
async function sealMessage({sender, peer, ep, key, signKey, payload, label}) {
  const room = peer == null ? "g" : roomTag(sender, peer), aad = aadOf(room, sender, ep || 0);
  const iv = rnd(12), plain = padded(payload);
  const ct = new Uint8Array(await subtle().encrypt({name: "AES-GCM", iv, additionalData: aad}, key, plain));
  const sig = new Uint8Array(await subtle().sign({name: "ECDSA", hash: "SHA-256"}, signKey, cat(aad, iv, ct)));
  const env = "e2e1:" + b64u(enc.encode(JSON.stringify({v: 1, k: peer == null ? "g" : "d", ep: ep || 0, n: b64u(iv), c: b64u(ct), s: b64u(sig)})));
  note({kind: "seal", room, ep: ep || 0, plain: dec.decode(plain).replace(/,"p":"0*"\}$/, "}"), plainBytes: plain.length, iv: b64u(iv), ctBytes: ct.length, sigBytes: sig.length, env, label: label || ""});
  return env;
}
function parseEnvelope(env) {
  if (typeof env !== "string" || !env.startsWith("e2e1:")) throw new Error("konvert emas");
  const o = JSON.parse(dec.decode(unb64u(env.slice(5))));
  if (o.v !== 1) throw new Error("versiya");
  return o;
}
/* {sender, peer, key, signKey}: kalit va imzo kaliti chaqiruvchi tomonidan topilgan. Qaytadi {payload, verified} yoki istisno. */
async function openMessage(env, {sender, peer, key, signKey}) {
  const o = parseEnvelope(env), room = peer == null ? "g" : roomTag(sender, peer), aad = aadOf(room, sender, o.ep);
  if ((o.k === "g") !== (peer == null)) throw new Error("xona mos emas");
  const iv = unb64u(o.n), ct = unb64u(o.c);
  let verified = false;
  if (signKey) verified = await subtle().verify({name: "ECDSA", hash: "SHA-256"}, signKey, unb64u(o.s), cat(aad, iv, ct));
  const plain = await subtle().decrypt({name: "AES-GCM", iv, additionalData: aad}, key, ct);   // teg noto'g'ri bo'lsa — istisno
  return {payload: JSON.parse(dec.decode(plain)), verified, ep: o.ep};
}

/* ---------------- guruh kaliti: avlodlar, o'rash, tekshirish ---------------- */
async function newRoomKey() { return subtle().generateKey({name: "AES-GCM", length: 256}, true, ["encrypt", "decrypt"]); }
async function importRoomKey(raw) { return subtle().importKey("raw", raw, "AES-GCM", true, ["encrypt", "decrypt"]); }
async function wrapKeyBytes(myEcdhPriv, peerEcdhPub, epoch, from, to) {
  const bits = await subtle().deriveBits({name: "ECDH", public: peerEcdhPub}, myEcdhPriv, 256);
  const hk = await subtle().importKey("raw", bits, "HKDF", false, ["deriveKey"]);
  return subtle().deriveKey({name: "HKDF", hash: "SHA-256", salt: enc.encode("ac/wrap/v1|" + epoch), info: enc.encode(from + "|" + to)},
    hk, {name: "AES-GCM", length: 256}, false, ["encrypt", "decrypt"]);
}
const wrapAad = (epoch, from, to) => enc.encode("ac/wrap|" + epoch + "|" + from + "|" + to);
async function wrapRoomKey(roomKey, epoch, myPriv, from, peerEcdhPub, to) {
  const k = await wrapKeyBytes(myPriv, peerEcdhPub, epoch, from, to), iv = rnd(12);
  const raw = new Uint8Array(await subtle().exportKey("raw", roomKey));
  return b64u(cat(iv, new Uint8Array(await subtle().encrypt({name: "AES-GCM", iv, additionalData: wrapAad(epoch, from, to)}, k, raw))));
}
async function unwrapRoomKey(wrapped, epoch, myPriv, me, wrapperPubKey, wrapper) {
  const k = await wrapKeyBytes(myPriv, wrapperPubKey, epoch, wrapper, me), w = unb64u(wrapped);
  const raw = await subtle().decrypt({name: "AES-GCM", iv: w.slice(0, 12), additionalData: wrapAad(epoch, wrapper, me)}, k, w.slice(12));
  return importRoomKey(raw);
}
async function epochCheck(roomKey, epoch) {
  const iv = rnd(12);
  return b64u(cat(iv, new Uint8Array(await subtle().encrypt({name: "AES-GCM", iv, additionalData: enc.encode("ac/epoch|" + epoch)}, roomKey, enc.encode("ok")))));
}
async function verifyEpochCheck(check, roomKey, epoch) {      // o'ralgan kalit haqiqiy guruh kaliti ekanini tekshiradi
  try {
    const w = unb64u(check);
    return dec.decode(await subtle().decrypt({name: "AES-GCM", iv: w.slice(0, 12), additionalData: enc.encode("ac/epoch|" + epoch)}, roomKey, w.slice(12))) === "ok";
  } catch (_) { return false; }
}
async function keyId(roomKey) {                               // kalitning ko'rsatiladigan qisqa identifikatori (kalitning o'zi emas)
  const raw = new Uint8Array(await subtle().exportKey("raw", roomKey));
  return (hex(new Uint8Array(await subtle().digest("SHA-256", cat(enc.encode("ac/keyid"), raw)))).slice(0, 12).match(/.{4}/g) || []).join(" ").toUpperCase();
}

/* ---------------- fayllar ---------------- */
async function encryptFile(bytes) {
  const raw = rnd(32), key = await subtle().importKey("raw", raw, "AES-GCM", false, ["encrypt"]), iv = rnd(12);
  const ct = new Uint8Array(await subtle().encrypt({name: "AES-GCM", iv, additionalData: enc.encode("ac/blob/v1")}, key, bytes));
  return {key: b64u(raw), blob: cat(iv, ct)};
}
async function decryptFile(blob, keyB64) {
  const key = await subtle().importKey("raw", unb64u(keyB64), "AES-GCM", false, ["decrypt"]);
  return new Uint8Array(await subtle().decrypt({name: "AES-GCM", iv: blob.slice(0, 12), additionalData: enc.encode("ac/blob/v1")}, key, blob.slice(12)));
}

/* ---------------- qurilmada saqlash (IndexedDB: eksport qilib bo'lmaydigan CryptoKey'lar) ---------------- */
const idb = () => new Promise((res, rej) => {
  if (!root.indexedDB) return rej(new Error("IndexedDB yo'q"));
  const r = root.indexedDB.open("termchat_e2ee", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("ids", {keyPath: "uid"});
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const tx = async (mode, fn) => { const db = await idb(); return new Promise((res, rej) => { const t = db.transaction("ids", mode), r = fn(t.objectStore("ids")); t.oncomplete = () => { db.close(); res(r && r.result); }; t.onerror = () => { db.close(); rej(t.error); }; }); };
const saveIdentity = (uid, rec) => tx("readwrite", s => s.put(Object.assign({uid}, rec))).catch(() => {});
const loadIdentity = uid => tx("readonly", s => s.get(uid)).catch(() => null);
const clearIdentity = () => tx("readwrite", s => s.clear()).catch(() => {});

root.E2E = {
  KDF_DEFAULT, b64u, unb64u, trace, note,
  deriveFromPassword, generateIdentity, importPrivate, wrapIdentity, unwrapIdentity, fingerprint, importPeer, importEcdhPub,
  dmKey, sealMessage, openMessage, parseEnvelope, roomTag,
  newRoomKey, importRoomKey, wrapRoomKey, unwrapRoomKey, epochCheck, verifyEpochCheck, keyId,
  encryptFile, decryptFile, saveIdentity, loadIdentity, clearIdentity,
};
})(typeof globalThis !== "undefined" ? globalThis : window);
