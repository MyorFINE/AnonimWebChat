/* Anonim Chat by Hevorix — shifrlangan kanal (brauzer tomoni).
   ECDH P-256 -> HKDF-SHA256 -> AES-256-GCM (WebCrypto). Barcha /api so'rovlari, WebSocket kadrlari va rasmlar
   shifrlanadi: Network/WebSocket oynasida va Wireshark'da faqat `iv|ciphertext` ko'rinadi. */
"use strict";
(() => {
const enc = new TextEncoder(), dec = new TextDecoder();
const AAD = {req: enc.encode("termchat/v1/http-req"), res: enc.encode("termchat/v1/http-res"),
             c2s: enc.encode("termchat/v1/ws-c2s"), s2c: enc.encode("termchat/v1/ws-s2c")};
const WS_REKEY = 4428;
let sess = null, pending = null;
const wire = [];                                   // inspektor uchun: oxirgi WebSocket kadrlari (ilova JSON'i va tarmoqdagi shifrlangan ko'rinishi)
const wnote = (dir, app, net) => { wire.push({ts: Date.now(), dir, app: String(app).replace(/"a":"[^"]*"/, '"a":"•••"').slice(0, 1800), net: net.slice(0, 160), bytes: net.length}); while (wire.length > 12) wire.shift(); };

const b64e = u8 => { let s = ""; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); };
const b64d = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const cat = (...parts) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };

const supported = () => !!(window.crypto && crypto.subtle && window.isSecureContext !== false);

async function handshake() {
  if (!supported()) throw new Error("Xavfsiz ulanish (HTTPS) kerak — shifrlash bu brauzerda ishlamaydi");
  if (pending) return pending;
  pending = (async () => {
    const kp = await crypto.subtle.generateKey({name: "ECDH", namedCurve: "P-256"}, false, ["deriveBits"]);
    const pub = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
    const r = await fetch("/api/handshake", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({pub: b64e(pub)})});
    if (!r.ok) throw new Error(r.status === 429 ? "Juda ko'p urinish, biroz kuting" : "Xavfsiz kanal ochilmadi");
    const j = await r.json();
    const srv = b64d(j.pub);
    const peer = await crypto.subtle.importKey("raw", srv, {name: "ECDH", namedCurve: "P-256"}, false, []);
    const bits = await crypto.subtle.deriveBits({name: "ECDH", public: peer}, kp.privateKey, 256);
    const hk = await crypto.subtle.importKey("raw", bits, "HKDF", false, ["deriveKey"]);
    const salt = cat(pub, srv);
    const mk = info => crypto.subtle.deriveKey({name: "HKDF", hash: "SHA-256", salt, info: enc.encode(info)}, hk,
      {name: "AES-GCM", length: 256}, false, ["encrypt", "decrypt"]);
    sess = {kid: j.kid, up: await mk("termchat/v1/c2s"), down: await mk("termchat/v1/s2c")};
  })().finally(() => { pending = null; });
  return pending;
}
const ready = async () => { if (!sess) await handshake(); return sess; };

async function seal(key, iv, plain, aad) { return new Uint8Array(await crypto.subtle.encrypt({name: "AES-GCM", iv, additionalData: aad}, key, plain)); }
async function open(key, iv, ct, aad) { return new Uint8Array(await crypto.subtle.decrypt({name: "AES-GCM", iv, additionalData: aad}, key, ct)); }

/* ---- HTTP: hamma narsa POST /api/x orqali, tana shifrlangan ---- */
class SecRes {
  constructor(status, type, bytes) { this.status = status; this.ok = status >= 200 && status < 300; this.type = type; this.bytes = bytes; }
  async json() { return JSON.parse(dec.decode(this.bytes)); }
  async text() { return dec.decode(this.bytes); }
  blob() { return new Blob([this.bytes], {type: this.type}); }
}
async function sfetch(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = Object.assign({}, opts.headers || {});
  let token = null, ctype = headers["Content-Type"] || headers["content-type"] || "";
  const auth = headers.Authorization || headers.authorization || "";
  if (/^bearer /i.test(auth)) token = auth.slice(7).trim();
  if (!token && /^\/uploads\//.test(path)) { try { token = localStorage.getItem("termchat_token") || null; } catch (_) {} }   // fayllar faqat tizimga kirganlarga beriladi
  let body = new Uint8Array(0);
  if (opts.body instanceof FormData) {                                   // multipart: boundary bilan baytlarga aylantiramiz
    const rq = new Request(location.origin + "/", {method: "POST", body: opts.body});
    ctype = rq.headers.get("content-type") || ""; body = new Uint8Array(await rq.arrayBuffer());
  } else if (typeof opts.body === "string") body = enc.encode(opts.body);
  else if (opts.body instanceof Uint8Array) body = opts.body;                    // shifrlangan fayl baytlari
  for (let attempt = 0; attempt < 2; attempt++) {
    const s = await ready();
    const meta = JSON.stringify({t: Date.now(), m: method, p: path, a: token, c: ctype || null});
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = await seal(s.up, iv, cat(enc.encode(meta + "\n"), body), AAD.req);
    const r = await fetch("/api/x", {method: "POST", headers: {"X-Kid": s.kid, "Content-Type": "application/octet-stream"}, body: cat(iv, ct)});
    if (r.status === 428) { sess = null; continue; }                     // server qayta ishga tushgan: qayta qo'l siqish
    const buf = new Uint8Array(await r.arrayBuffer());
    if (r.status !== 200) { let d = ""; try { d = JSON.parse(dec.decode(buf)).detail; } catch (_) {} return new SecRes(r.status, "application/json", enc.encode(JSON.stringify({detail: d || "Xato"}))); }
    const plain = await open(s.down, buf.subarray(0, 12), buf.subarray(12), AAD.res);
    const nl = plain.indexOf(10), m = JSON.parse(dec.decode(plain.subarray(0, nl)));
    return new SecRes(m.s, m.c || "", plain.subarray(nl + 1));
  }
  throw new Error("Xavfsiz kanal qayta o'rnatilmadi");
}

/* ---- WebSocket: har bir kadr shifrlangan; token birinchi kadrda ---- */
class SecSocket {
  constructor(token) {
    this.readyState = 0; this.onopen = this.onmessage = this.onclose = null;
    this._token = token; this._tx = 0; this._rx = -1; this._pre = crypto.getRandomValues(new Uint8Array(4)); this._q = Promise.resolve();
    this._start();
  }
  async _start() {
    try {
      const s = await ready(); this._s = s;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = this._ws = new WebSocket(proto + "://" + location.host + "/ws?k=" + encodeURIComponent(s.kid));
      ws.onopen = async () => { await this._sendRaw(JSON.stringify({a: this._token})); this.readyState = 1; this.onopen && this.onopen({}); };
      ws.onmessage = ev => { this._q = this._q.then(() => this._recv(ev.data)).catch(() => this.close()); };
      ws.onclose = ev => { this.readyState = 3; if (ev.code === WS_REKEY) sess = null; this.onclose && this.onclose({code: ev.code}); };
    } catch (_) { this.readyState = 3; this.onclose && this.onclose({code: 1006}); }
  }
  async _sendRaw(text) {
    const iv = new Uint8Array(12); iv.set(this._pre); const dv = new DataView(iv.buffer); const n = ++this._tx;
    dv.setUint32(4, Math.floor(n / 4294967296)); dv.setUint32(8, n >>> 0);
    const ct = await seal(this._s.up, iv, enc.encode(text), AAD.c2s);
    const net = b64e(cat(iv, ct)); wnote("→", text, net);
    this._ws.send(net);
  }
  send(text) { this._out = (this._out || Promise.resolve()).then(() => this._sendRaw(text)); }
  async _recv(data) {
    const blob = b64d(data), iv = blob.subarray(0, 12), dv = new DataView(blob.buffer, blob.byteOffset + 4, 8);
    const ctr = dv.getUint32(0) * 4294967296 + dv.getUint32(4);
    if (ctr <= this._rx) throw new Error("replay");
    const plain = await open(this._s.down, iv, blob.subarray(12), AAD.s2c);
    this._rx = ctr; wnote("←", dec.decode(plain), data);
    this.onmessage && this.onmessage({data: dec.decode(plain)});
  }
  close() { try { this._ws && this._ws.close(); } catch (_) {} }
}

/* ---- Rasmlar (/uploads, /avatars) ham shifrlangan kanal orqali olinadi ---- */
const imgCache = new Map();
function blobUrl(path) {
  if (!imgCache.has(path)) {
    imgCache.set(path, sfetch(path).then(r => { if (!r.ok) throw new Error("img"); return URL.createObjectURL(r.blob()); })
      .catch(e => { imgCache.delete(path); throw e; }));
  }
  return imgCache.get(path);
}
const SECURE_IMG = /^\/(uploads|avatars)\//;
const srcDesc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
Object.defineProperty(HTMLImageElement.prototype, "src", {
  configurable: true, enumerable: true,
  get() { return srcDesc.get.call(this); },
  set(v) {
    if (typeof v === "string" && SECURE_IMG.test(v)) {
      this.dataset.sec = v;
      blobUrl(v).then(u => { if (this.dataset.sec === v) srcDesc.set.call(this, u); }).catch(() => {});
    } else { delete this.dataset.sec; srcDesc.set.call(this, v); }
  },
});
const nativeSet = Element.prototype.setAttribute;
Element.prototype.setAttribute = function (name, value) {
  if (this instanceof HTMLImageElement && String(name).toLowerCase() === "src") { this.src = value; return; }
  return nativeSet.call(this, name, value);
};

window.SC = {wire, supported, handshake, fetch: sfetch, socket: token => new SecSocket(token), blobUrl};
})();
