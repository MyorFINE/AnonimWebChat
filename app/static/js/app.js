"use strict";
(() => {
/* =====================================================================
   Anonim Chat by Hevorix — veb-mijoz
   Matn DOM'ga faqat textContent orqali chiqariladi (XSS yo'q, CSP qat'iy).
   ===================================================================== */
const NS = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);
const APP_NAME = "Anonim Chat by Hevorix";
const LS_TOKEN = "termchat_token", LS_THEME = "termchat_theme";
const WS_UNAUTHORIZED = 4401, WS_FORBIDDEN = 4403, WS_IP_BLOCKED = 4410;
const PALETTE = ["#e17076", "#e0954f", "#a695e7", "#7bc862", "#4fb6b9", "#65aadd", "#ee7aae"];
const MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"];
const COARSE = matchMedia("(pointer: coarse)").matches;
const isMobile = () => matchMedia("(max-width: 760px)").matches;

const S = {
  token: null, me: null, ws: null, retry: 0, wantClose: false, mode: "login",
  users: new Map(),            // id -> foydalanuvchi
  members: [],                 // a'zolar ro'yxati (serverdan)
  online: new Set(),
  group: {msgs: [], unread: 0},
  dms: new Map(),              // uid -> {msgs, loaded, buffer, unread, last}
  active: null,                // {kind:"group"} | {kind:"dm", uid}
  tab: "chats", query: "", editing: null, away: 0, modal: null,
  replying: null,              // {id, nickname, text, image} — javob berilayotgan xabar
  pendingImg: null,            // {blob, url, name} — yuborishga tayyor rasm
  sending: false,
  rec: null, recBusy: false, recTimer: 0,   // ovozli xabar yozilmoqda: Voice.record() obyekti
  imgs: new Map(),             // xabar id -> "loading" | "open" (rasm yuklash holati)
  sel: null,                   // Set<id> — belgilash rejimi yoqilgan bo'lsa
  played: new Map(),           // xabar id -> blob URL (ijro etilgan video/audio)
  chat: {slowmode: 0, locked: false},   // umumiy chat moderatsiya holati (serverdan)
};

/* ---------------- yordamchilar ---------------- */
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}
function svgUse(href, cls) {
  const s = document.createElementNS(NS, "svg"); s.setAttribute("class", cls);
  const u = document.createElementNS(NS, "use"); u.setAttribute("href", href); s.append(u);
  return s;
}
const icon = (name, cls) => svgUse("#i-" + name, cls || "ic");
const pad2 = n => String(n).padStart(2, "0");
const hhmm = ts => { const d = new Date(ts * 1000); return pad2(d.getHours()) + ":" + pad2(d.getMinutes()); };
const dayKey = ts => { const d = new Date(ts * 1000); return d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate(); };
function dayLabel(ts) {
  const d = new Date(ts * 1000), now = new Date();
  if (dayKey(ts) === dayKey(now / 1000)) return "Bugun";
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (dayKey(ts) === dayKey(y / 1000)) return "Kecha";
  return d.getDate() + "-" + MONTHS[d.getMonth()] + (d.getFullYear() !== now.getFullYear() ? ", " + d.getFullYear() : "");
}
function listTime(ts) {
  const d = new Date(ts * 1000), now = new Date();
  if (dayKey(ts) === dayKey(now / 1000)) return hhmm(ts);
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (dayKey(ts) === dayKey(y / 1000)) return "Kecha";
  return pad2(d.getDate()) + "." + pad2(d.getMonth() + 1) + "." + String(d.getFullYear()).slice(2);
}
const colorOf = id => PALETTE[Math.abs(id) % PALETTE.length];
const isStaff = u => !!u && (u.role === "owner" || u.role === "admin");
const HEX = /^#[0-9a-f]{6}$/i, TONES = {owner: "#f7b733", admin: "#7b61ff"};
const hexRgb = x => { const n = parseInt(x.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const mixHex = (x, to, t) => "#" + hexRgb(x).map((v, i) => Math.round(v + (to[i] - v) * t).toString(16).padStart(2, "0")).join("");
function toneOf(u) {
  const base = HEX.test(u.color || "") ? u.color.toLowerCase() : TONES[u.role];
  const [r, g, b] = hexRgb(base);
  return {p2: base, p1: mixHex(base, [255, 255, 255], .55), p3: mixHex(base, [0, 0, 0], .4), pr: r + "," + g + "," + b,
    pt: (0.299 * r + 0.587 * g + 0.114 * b) / 255 > .6 ? "#2b2000" : "#fff"};
}
/** Ega/admin elementiga o'zi tanlagan rangni beradi (CSS o'zgaruvchilari; CSP uchun CSSOM orqali). */
function tint(el, u) {
  if (!isStaff(u)) return el;
  const t = toneOf(u);
  ["p1", "p2", "p3", "pr", "pt"].forEach(k => el.style.setProperty("--" + k, t[k]));
  return el;
}
const roleLabel = r => r === "owner" ? "Platforma egasi" : r === "admin" ? "Administrator" : "";
const U = id => S.users.get(id) || {id, nickname: "Noma'lum", username: "?", role: "user", bio: "", avatar: null};
const isOnline = id => S.me && (id === S.me.id || S.online.has(id));
const onlineCount = () => new Set([...S.online, S.me.id]).size;
const amAdmin = () => isStaff(S.me);
const dmOf = uid => {
  if (!S.dms.has(uid)) S.dms.set(uid, {msgs: [], loaded: false, buffer: [], unread: 0, last: null});
  return S.dms.get(uid);
};
function upsertUser(u) {
  if (!u || u.id == null) return;
  const merged = Object.assign({}, S.users.get(u.id), u);
  S.users.set(u.id, merged);
  if (S.me && u.id === S.me.id) S.me = Object.assign({}, S.me, u);
}

function toast(text, level) {
  const t = h("div", {class: "toast " + (level || "info"), text});
  $("toasts").append(t);
  while ($("toasts").children.length > 4) $("toasts").firstChild.remove();
  setTimeout(() => t.remove(), level === "error" ? 5000 : 3500);
}

async function api(path, opts = {}) {
  const headers = Object.assign({Authorization: "Bearer " + S.token}, opts.headers || {});
  let body = opts.body;
  if (body && !(body instanceof FormData)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  const r = await SC.fetch("/api" + path, {method: opts.method || "GET", headers, body});
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { showAuth("Sessiya tugagan, qayta kiring"); throw new Error("401"); }
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Xato, qayta urinib ko'ring");
  return j;
}
function wsSend(obj) {
  if (!S.ws || S.ws.readyState !== 1) { toast("Ulanish yo'q, biroz kuting…", "error"); return false; }
  S.ws.send(JSON.stringify(obj));
  return true;
}

/* ---------------- E2EE: kalitlar, guruh kaliti, xabarlarni shifrlash/ochish ----------------
   Serverga faqat shifrlangan konvert ketadi. Maxfiy kalitlar qurilmada (IndexedDB, eksport qilib bo'lmaydigan) va
   parol bilan o'ralgan zaxirada (serverda, ochib bo'lmaydigan) saqlanadi. Protokol: js/e2ee.js */
const LS_PINS = "termchat_pins";
const X = {id: 0, username: "", priv: null, ecdhPub: "", signPub: "", fp: "", iter: 0, self: null, rooms: new Map(), keyIds: new Map(),
           epoch: 0, state: null, peers: new Map(), pending: new Set(), changed: new Map(), ready: null, serving: false, rotating: false};
function xReset() {
  X.id = 0; X.priv = null; X.self = null; X.rooms = new Map(); X.keyIds = new Map(); X.epoch = 0; X.state = null; X.peers = new Map();
  X.pending = new Set(); X.changed = new Map(); X.ready = null; X.serving = false; X.rotating = false;
}
const pinStore = () => { try { return JSON.parse(localStorage.getItem(LS_PINS + "_" + X.id) || "{}"); } catch (_) { return {}; } };
const savePins = p => { try { localStorage.setItem(LS_PINS + "_" + X.id, JSON.stringify(p)); } catch (_) {} };

/* --- shaxsiy kalitlarni sessiyaga o'rnatish --- */
async function xInstall(me, username, ident, pubs, iter, remember) {
  const priv = await E2E.importPrivate(ident);
  X.id = me.id; X.username = username; X.priv = priv; X.ecdhPub = pubs.ecdh_pub; X.signPub = pubs.sign_pub; X.iter = iter;
  X.self = await E2E.importPeer({e: pubs.ecdh_pub, s: pubs.sign_pub}); X.fp = X.self.fp;
  if (remember) await E2E.saveIdentity(me.id, {ecdhPriv: priv.ecdhPriv, signPriv: priv.signPriv, ecdhPub: pubs.ecdh_pub, signPub: pubs.sign_pub, iter});
}
async function xGenerate(username, password, iter) {
  const kd = await E2E.deriveFromPassword(username, password, iter);
  const ident = await E2E.generateIdentity();
  const keys = {ecdh_pub: ident.ecdhPub, sign_pub: ident.signPub, key_blob: await E2E.wrapIdentity(ident, kd.kek, username), kdf_iter: iter};
  return {kd, ident, keys};
}
/* --- tizimga kirgandan keyin: kalitlarni tayyorlash (yangi akkaunt, eski akkauntni yangilash yoki parol bilan ochish) --- */
async function xUnlock(info, me, username, password) {
  if (info.upgrade) {                                           // eski akkaunt: kalitlar brauzerda yaratiladi, parol hash'i almashadi
    const g = await xGenerate(username, password, E2E.KDF_DEFAULT);
    await api("/e2ee/setup", {method: "POST", body: {old: password, auth: g.kd.auth, keys: g.keys}});
    await xInstall(me, username, g.ident, g.keys, E2E.KDF_DEFAULT, true);
    return;
  }
  const e = info.e2ee, kd = await E2E.deriveFromPassword(username, password, e.kdf_iter || E2E.KDF_DEFAULT);
  let ident;
  try { ident = await E2E.unwrapIdentity(e.key_blob, kd.kek, username); } catch (_) { throw new Error("Parol noto'g'ri (kalitlarni ochib bo'lmadi)"); }
  await xInstall(me, username, ident, e, e.kdf_iter || E2E.KDF_DEFAULT, true);
}
/* --- sahifa yangilanganda: kalitlar qurilmada bo'lsa parolsiz, bo'lmasa parol so'rab --- */
async function xRestore(info, me) {
  if (!info.upgrade && info.e2ee.ecdh_pub) {
    const rec = await E2E.loadIdentity(me.id);
    if (rec && rec.ecdhPub === info.e2ee.ecdh_pub && rec.signPub === info.e2ee.sign_pub) {
      X.id = me.id; X.username = me.username; X.priv = {ecdhPriv: rec.ecdhPriv, signPriv: rec.signPriv};
      X.ecdhPub = rec.ecdhPub; X.signPub = rec.signPub; X.iter = rec.iter || info.e2ee.kdf_iter;
      X.self = await E2E.importPeer({e: rec.ecdhPub, s: rec.signPub}); X.fp = X.self.fp;
      return true;
    }
  }
  for (let tries = 0; tries < 5; tries++) {
    const pw = await promptDlg(info.upgrade ? "Shifrlashni yoqish" : "Kalitlarni ochish",
      info.upgrade ? "Xabarlaringiz endi uchdan-uchga shifrlanadi. Davom etish uchun parolingizni kiriting (kalitlar shu qurilmada yaratiladi)."
        : "Shifrlash kalitlari bu qurilmada yo'q. Ularni ochish uchun parolingizni kiriting.", "", {type: "password", okText: "Ochish"});
    if (pw === null) return false;
    try { await xUnlock(info, me, me.username, pw); return true; } catch (err) { toast(err.message, "error"); }
  }
  return false;
}

/* --- boshqa foydalanuvchilarning ommaviy kalitlari (+ barmoq izini qadash, TOFU) --- */
async function peer(uid) {
  if (uid === X.id) return X.self;
  let p = X.peers.get(uid);
  if (p) return p;
  const m = S.members.find(x => x.id === uid);
  let keys = m && m.ek ? {e: m.ek, s: m.sk} : null;
  if (!keys) { const j = await api("/e2ee/keys?ids=" + uid); keys = j.keys[String(uid)]; }
  if (!keys) throw new Error("Bu foydalanuvchida E2EE kalitlari yo'q");
  p = await E2E.importPeer(keys);
  const pins = pinStore();
  if (pins[uid] && pins[uid] !== p.fp) { p.changed = true; X.changed.set(uid, {old: pins[uid], now: p.fp}); }
  else if (!pins[uid]) { pins[uid] = p.fp; savePins(pins); }
  X.peers.set(uid, p);
  return p;
}
function acceptKeyChange(uid) {
  const c = X.changed.get(uid); if (!c) return;
  const pins = pinStore(); pins[uid] = c.now; savePins(pins);
  X.changed.delete(uid); const p = X.peers.get(uid); if (p) p.changed = false;
}

/* --- guruh kaliti --- */
async function loadRoom() {
  const st = await api("/e2ee/room"); X.state = st; X.epoch = st.epoch;
  for (const w of st.mine) {
    if (X.rooms.has(w.epoch)) continue;
    const ep = st.epochs.find(e => e.epoch === w.epoch);
    try {
      const wp = await peer(w.by);
      const key = await E2E.unwrapRoomKey(w.wrapped, w.epoch, X.priv.ecdhPriv, X.id, wp.ecdh, w.by);
      if (!ep || !(await E2E.verifyEpochCheck(ep.check, key, w.epoch))) throw new Error("tekshiruv");
      X.rooms.set(w.epoch, key); X.keyIds.set(w.epoch, await E2E.keyId(key));
    } catch (_) {                                              // soxta/buzilgan o'ralgan kalit: o'chirib, boshqa a'zodan qayta so'raymiz
      try { await api("/e2ee/room/wrap/" + w.epoch, {method: "DELETE"}); } catch (__) {}
    }
  }
  if (st.epoch === 0) await initRoom();
  else if (X.rooms.has(st.epoch)) { rehydratePending(); serveWraps(); }
  if (!X.rooms.has(X.epoch) && X.epoch) renderHeader();
}
async function initRoom() {
  const key = await E2E.newRoomKey(), withKeys = S.members.filter(m => m.ek && !m.banned && !m.deleted);
  const list = withKeys.some(m => m.id === X.id) ? withKeys : withKeys.concat([{id: X.id, ek: X.ecdhPub}]);
  const wraps = [];
  for (const m of list) wraps.push({user_id: m.id, wrapped: await E2E.wrapRoomKey(key, 1, X.priv.ecdhPriv, X.id, (await peer(m.id)).ecdh, m.id)});
  try { await api("/e2ee/room/init", {method: "POST", body: {check: await E2E.epochCheck(key, 1), wraps}}); }
  catch (_) { /* boshqa a'zo oldinroq yaratdi */ }
  const st = await api("/e2ee/room"); if (st.epoch) { X.state = st; X.epoch = st.epoch; await loadRoomKeysOnly(); }
}
async function loadRoomKeysOnly() { if (X.epoch) await loadRoom(); }
async function serveWraps() {                                   // yangi a'zolarga (kaliti hali yo'qlarga) kalitni o'rab beramiz
  if (X.serving || !X.rooms.size) return;
  X.serving = true;
  try {
    const j = await api("/e2ee/room/missing"), byEp = new Map();
    j.missing.forEach(m => { if (X.rooms.has(m.epoch) && m.user_id !== X.id) (byEp.get(m.epoch) || byEp.set(m.epoch, []).get(m.epoch)).push(m); });
    for (const [ep, list] of byEp) {
      const wraps = [];
      for (const m of list.slice(0, 100)) {
        try {
          const pk = await E2E.importEcdhPub(m.ecdh_pub);
          wraps.push({user_id: m.user_id, wrapped: await E2E.wrapRoomKey(X.rooms.get(ep), ep, X.priv.ecdhPriv, X.id, pk, m.user_id)});
        } catch (_) {}
      }
      if (wraps.length) await api("/e2ee/room/wrap", {method: "POST", body: {epoch: ep, wraps}});
    }
  } catch (_) {}
  X.serving = false;
}
async function rotateRoom(reason) {                              // ban/chiqib ketishdan keyin: yangi kalit, faqat joriy a'zolarga
  if (X.rotating || !amAdmin() || !X.rooms.has(X.epoch)) return;
  X.rotating = true;
  try {
    await loadMembers();
    const key = await E2E.newRoomKey(), ep = X.epoch + 1, wraps = [];
    for (const m of S.members.filter(m => m.ek && !m.banned && !m.deleted))
      wraps.push({user_id: m.id, wrapped: await E2E.wrapRoomKey(key, ep, X.priv.ecdhPriv, X.id, (await peer(m.id)).ecdh, m.id)});
    await api("/e2ee/room/rotate", {method: "POST", body: {from_epoch: X.epoch, check: await E2E.epochCheck(key, ep), wraps, reason: (reason || "rotate").slice(0, 20)}});
    toast("Guruh kaliti yangilandi (yangi xabarlar eski a'zolar uchun yopiq)", "ok");
  } catch (_) {}
  X.rotating = false;
  try { await loadRoom(); } catch (_) {}
}

/* --- xabar konvertini ochish --- */
const replyInfo = m => ({id: m.id, uid: m.user.id, nickname: m.user.nickname, text: snippetOf(m.content), image: !!m.image, file: !!m.file, voice: !!(m.file && m.file.voice), file_name: m.file ? (m.file.voice ? "Ovozli xabar" : m.file.name) : null});
async function hydrate(m) {
  if (!m || m.service || !m.e2e) { if (m && !m.service && !m.e2e) m.legacy = true; return m; }
  m.locked = false; m.bad = false; m.verified = false;
  try {
    const env = E2E.parseEnvelope(m.e2e), sender = m.user.id, me = X.id;
    let key;
    if (m.to == null) {
      key = X.rooms.get(env.ep);
      if (!key) { m.locked = true; m.content = ""; X.pending.add(m); return m; }
    } else {
      const other = sender === me ? m.to : sender, op = await peer(other);
      if (op.changed) throw new Error("kalit o'zgargan");
      key = await E2E.dmKey(X.priv.ecdhPriv, op.ecdh, sender, m.to);
    }
    const sp = await peer(sender);
    const r = await E2E.openMessage(m.e2e, {sender, peer: m.to, key, signKey: sp.sign});
    const p = r.payload; m.verified = r.verified && !sp.changed;
    m.content = typeof p.t === "string" ? p.t : "";
    m.reply = p.r ? Object.assign({deleted: false}, p.r) : null;
    m._r = p.r || null; m._f = p.f || null;
    if (p.f) {
      m.mkey = p.f.k;
      if (p.f.img) { m.image = "e2e"; m.thumb = p.f.th || null; m.w = p.f.w || null; m.h = p.f.h || null; }
      else m.file = {url: m.blob ? m.blob.url : "", name: p.f.name || "fayl", size: p.f.size || 0, mime: p.f.mime || "application/octet-stream", e2e: true, key: p.f.k,
        voice: p.f.vo === 1 && p.f.mime === "audio/wav", dur: typeof p.f.d === "number" && p.f.d > 0 && p.f.d < 900 ? p.f.d : 0};
    }
    X.pending.delete(m);
  } catch (err) { m.bad = true; m.content = ""; X.pending.delete(m); }
  return m;
}
async function rehydratePending() {
  const list = [...X.pending]; if (!list.length) return;
  for (const m of list) await hydrate(m);
  renderMessages(false); renderList();
}
const hydrateAll = list => Promise.all(list.map(hydrate));

/* --- shifrlangan fayllar --- */
async function e2eFetchBlob(m) {
  const url = m.blob ? m.blob.url : (m.file && m.file.url);
  const r = await SC.fetch(url, {headers: {Authorization: "Bearer " + S.token}});
  if (!r.ok) throw new Error("fayl");
  return E2E.decryptFile(r.bytes, m.mkey || m.file.key);
}
const blobUrls = new Map();                                       // xabar id -> ochilgan rasm URL'i
function e2eImageUrl(m) {
  if (!blobUrls.has(m.id)) blobUrls.set(m.id, e2eFetchBlob(m).then(b => URL.createObjectURL(new Blob([b], {type: (m._f && m._f.mime) || "image/jpeg"}))).catch(e => { blobUrls.delete(m.id); throw e; }));
  return blobUrls.get(m.id);
}
const imgSrcOf = m => m.e2e ? e2eImageUrl(m) : Promise.resolve(m.image);

async function cleanImage(blob) {                                 // EXIF/GPS metama'lumot olib tashlanadi (qayta kodlash) + xira kichik nusxa
  const out = {blob, w: 0, h: 0, th: null};
  try {
    const bmp = await createImageBitmap(blob);
    out.w = bmp.width; out.h = bmp.height;
    if (blob.type !== "image/gif") {
      const c = document.createElement("canvas"); c.width = bmp.width; c.height = bmp.height;
      c.getContext("2d").drawImage(bmp, 0, 0);
      const png = blob.type === "image/png", re = await new Promise(r => c.toBlob(r, png ? "image/png" : "image/jpeg", 0.92));
      if (re) out.blob = re;
    }
    const k = 40 / Math.max(bmp.width, bmp.height), t = document.createElement("canvas");
    t.width = Math.max(1, Math.round(bmp.width * k)); t.height = Math.max(1, Math.round(bmp.height * k));
    t.getContext("2d").drawImage(bmp, 0, 0, t.width, t.height);
    out.th = t.toDataURL("image/jpeg", 0.5);
  } catch (_) {}
  return out;
}

/* --- yuborish: konvertni yasab, serverga FAQAT shifrni beramiz --- */
async function keyForActive() {
  if (S.active.kind === "group") {
    const key = X.rooms.get(X.epoch);
    if (!key) throw new Error(X.epoch ? "Guruh kaliti hali kelmagan: kalitli a'zo onlayn bo'lishi kerak. Biroz kuting…" : "Guruh kaliti yaratilmoqda, biroz kuting…");
    return {key, peer: null, ep: X.epoch};
  }
  const uid = S.active.uid, p = await peer(uid);
  if (p.changed) throw new Error("Bu foydalanuvchining shifrlash kaliti o'zgargan! 🔒 tugmasida tekshirib, qabul qiling");
  return {key: await E2E.dmKey(X.priv.ecdhPriv, p.ecdh, X.id, uid), peer: uid, ep: 0};
}
async function sealFor(ctx, payload) {
  return E2E.sealMessage({sender: X.id, peer: ctx.peer, ep: ctx.ep, key: ctx.key, signKey: X.priv.signPriv, payload});
}

/* ---------------- ko'rinish bo'laklari: avatar, nom, galochka ---------------- */
function paintAv(el, u) {
  el.textContent = "";
  el.style.setProperty("--avc", colorOf(u.id));
  if (u.deleted) { el.classList.add("del"); el.append(icon("ghost")); return; }          // o'chirilgan akkaunt: arvoh belgisi
  if (u.avatar) el.append(h("img", {src: u.avatar, alt: "", draggable: "false"}));
  else el.append(h("span", {text: (Array.from((u.nickname || "?").trim())[0] || "?").toUpperCase()}));
}
function avatar(u, size, withDot) {
  const el = h("div", {class: "av av-" + size + (isStaff(u) ? " ring " + u.role : "")});
  tint(el, u); paintAv(el, u);
  if (withDot && !u.deleted && isOnline(u.id)) el.append(h("span", {class: "dot-on"}));
  return el;
}
function groupAvatar(size) { return h("div", {class: "av av-" + size + " grp"}, icon("group")); }
const hasEmoji = u => !!u && !!u.badge && u.badge !== "none";
function badge(u, big) {
  if (hasEmoji(u)) {                                   // ega/admin tanlagan yoki ular bergan emoji nishon (animatsiya bilan)
    return h("span", {class: "eb" + (u.badge_anim ? " a-" + u.badge_anim : "") + (big ? " big" : ""),
      title: isStaff(u) ? roleLabel(u.role) : "Maxsus nishon", "aria-label": "Nishon", text: u.badge});
  }
  if (!isStaff(u) || u.badge === "none") return null;
  const s = svgUse("#i-vb", "vb " + u.role + (big ? " big" : ""));
  const t = document.createElementNS(NS, "title");
  t.textContent = u.role === "owner" ? "Tasdiqlangan — platforma egasi" : "Tasdiqlangan administrator";
  s.prepend(t);
  return s;
}
function nameEl(u, opts = {}) {
  const nt = h("span", {class: "nt", text: u.nickname});
  if (opts.colored && !isStaff(u) && !u.deleted) nt.style.color = colorOf(u.id);
  return tint(h("span", {class: "nm" + (isStaff(u) ? " prem " + u.role : "") + (u.deleted ? " deleted" : "")}, nt, badge(u, opts.big)), u);
}
const statusText = u => u.deleted ? "akkaunt o'chirilgan" : isOnline(u.id) ? "onlayn" : "oflayn";

/* ---------------- kirish / chiqish ---------------- */
function setMode(m) {
  S.mode = m;
  $("tabL").classList.toggle("on", m === "login");
  $("tabR").classList.toggle("on", m === "register");
  $("nickWrap").classList.toggle("hidden", m === "login");
  $("regHint").classList.toggle("hidden", m === "login");
  $("submitBtn").textContent = m === "login" ? "Kirish" : "Ro'yxatdan o'tish";
  $("f_pass").autocomplete = m === "login" ? "current-password" : "new-password";
  $("autherr").textContent = "";
  $("unameChk").classList.add("hidden");
  if (m === "register") $("f_user").dispatchEvent(new Event("input"));
}
let unameTimer = null, unameSeq = 0;
$("f_user").addEventListener("input", () => {            // katta-kichik harfga e'tiborsiz: server tekshiradi
  clearTimeout(unameTimer);
  const chk = $("unameChk"), v = $("f_user").value.trim().replace(/^@/, "");
  if (S.mode !== "register" || !v) { chk.classList.add("hidden"); return; }
  unameTimer = setTimeout(async () => {
    const seq = ++unameSeq;
    try {
      const r = await SC.fetch("/api/username/" + encodeURIComponent(v));
      if (!r.ok) return;
      const j = await r.json();
      if (seq !== unameSeq || S.mode !== "register") return;
      chk.className = "uchk " + (j.available ? "ok" : "bad");
      chk.textContent = j.available ? "✓ Username bo'sh" : "✗ " + j.reason;
    } catch (_) {}
  }, 300);
});
if (!SC.supported()) $("autherr").textContent = "Shifrlash uchun HTTPS (xavfsiz ulanish) kerak. Saytni https:// orqali oching.";
$("tabL").onclick = () => setMode("login");
$("tabR").onclick = () => setMode("register");

const JSON_H = {"Content-Type": "application/json"};
$("form").addEventListener("submit", async e => {
  e.preventDefault();
  const btn = $("submitBtn"); btn.disabled = true; $("autherr").textContent = "";
  const username = $("f_user").value.trim().replace(/^@/, ""), password = $("f_pass").value;
  try {
    if (!SC.supported()) throw new Error("Shifrlash uchun HTTPS (xavfsiz ulanish) kerak");
    $("autherr").textContent = "Shifrlash kalitlari tayyorlanmoqda…";
    await new Promise(r => setTimeout(r, 30));                // matn chiqishi uchun (PBKDF2 bir necha yuz ms)
    let r, gen = null;
    if (S.mode === "register") {
      gen = await xGenerate(username, password, E2E.KDF_DEFAULT);
      r = await SC.fetch("/api/register", {method: "POST", headers: JSON_H, body: JSON.stringify({username, nickname: $("f_nick").value.trim() || username, password: gen.kd.auth, e2ee: gen.keys})});
    } else {
      const kr = await SC.fetch("/api/kdf", {method: "POST", headers: JSON_H, body: JSON.stringify({username})});
      const kp = await kr.json().catch(() => ({}));
      const secret = kp.auth_v === 0 ? password : (await E2E.deriveFromPassword(username, password, kp.kdf_iter || E2E.KDF_DEFAULT)).auth;
      r = await SC.fetch("/api/login", {method: "POST", headers: JSON_H, body: JSON.stringify({username, password: secret})});
    }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Xato, qayta urinib ko'ring");
    S.token = j.token; localStorage.setItem(LS_TOKEN, S.token); xReset();
    try {
      if (gen) await xInstall(j.me, j.me.username, gen.ident, gen.keys, E2E.KDF_DEFAULT, true);
      else await xUnlock({upgrade: j.upgrade, e2ee: j.e2ee}, j.me, j.me.username, password);
    } catch (err) { try { await SC.fetch("/api/logout", {method: "POST", headers: {Authorization: "Bearer " + S.token}}); } catch (_) {} S.token = null; localStorage.removeItem(LS_TOKEN); throw err; }
    $("f_pass").value = ""; $("autherr").textContent = "";
    openApp();
  } catch (err) { $("autherr").textContent = err.message; }
  btn.disabled = false;
});

function resetState() {
  S.me = null; S.users = new Map(); S.members = []; S.online = new Set();
  S.group = {msgs: [], unread: 0}; S.dms = new Map(); S.active = null; S.editing = null; S.query = ""; S.tab = "chats";
  S.replying = null; S.pendingImg = null; S.sending = false; S.sel = null; S.imgs = new Map();
  S.played.forEach(u => URL.revokeObjectURL(u)); S.played = new Map(); S.chat = {slowmode: 0, locked: false};
  cancelRecording(); voiceStop();
  ["replybar", "imgbar", "editbar"].forEach(id => $(id).classList.add("hidden"));
  $("search").value = ""; $("msgs").textContent = ""; $("inp").value = "";
}
function showAuth(msg) {
  S.wantClose = true;
  if (S.ws) try { S.ws.close(); } catch (_) {}
  localStorage.removeItem(LS_TOKEN); S.token = null;
  E2E.clearIdentity(); xReset(); blobUrls.forEach(p => p.then(u => URL.revokeObjectURL(u)).catch(() => {})); blobUrls.clear();
  closeModal(); closeCtx(); resetState();
  document.body.classList.remove("in-chat");
  $("app").classList.add("hidden"); $("auth").classList.remove("hidden");
  $("autherr").textContent = msg || "";
  document.title = APP_NAME;
}
async function logout() {
  try { await SC.fetch("/api/logout", {method: "POST", headers: {Authorization: "Bearer " + S.token}}); } catch (_) {}
  showAuth("");
}

/* ---------------- mavzu ---------------- */
function toggleTheme() {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem(LS_THEME, t); } catch (_) {}
}

/* ---------------- WebSocket ---------------- */
function connect() {
  S.wantClose = false;
  const ws = SC.socket(S.token);                     // shifrlangan WebSocket (token birinchi shifrlangan kadrda)
  S.ws = ws;
  ws.onopen = () => { S.retry = 0; $("connbar").classList.add("hidden"); };
  ws.onmessage = ev => {                              // tartib saqlanadi: har bir hodisa shifrdan ochilgach qayta ishlanadi
    S.q = (S.q || Promise.resolve()).then(async () => { const m = JSON.parse(ev.data); await prepare(m); onMessage(m); }).catch(err => console.error(err));
  };
  ws.onclose = ev => {
    if (S.wantClose || ws !== S.ws) return;
    if (ev.code === WS_UNAUTHORIZED) return showAuth("Sessiya tugagan, qayta kiring");
    if (ev.code === WS_FORBIDDEN) return showAuth("Siz ban qilingansiz");
    if (ev.code === WS_IP_BLOCKED) return showAuth("IP manzilingiz bloklangan");
    $("connbar").classList.remove("hidden");
    S.retry++;
    setTimeout(() => { if (S.token && !S.wantClose) connect(); }, Math.min(1000 * S.retry, 8000));
  };
}

async function prepare(m) {
  if (X.ready) await X.ready;
  if (m.type === "init") await hydrateAll(m.history);
  else if (m.type === "message") await hydrate(m);
  else if (m.type === "message_edited" && m.e2e) {
    const {list} = findMsg(m.id, m.to, m.from), x = list.find(i => i.id === m.id);
    if (x) { m._h = Object.assign({}, x, {e2e: m.e2e}); await hydrate(m._h); }
  }
}
function eachMsg(fn) { S.group.msgs.forEach(fn); S.dms.forEach(d => { d.msgs.forEach(fn); d.buffer.forEach(fn); }); }
const snippetOf = t => (t || "").replace(/\s+/g, " ").slice(0, 100);
function partnerOf(m) { return m.user.id === S.me.id ? m.to : m.user.id; }
function findMsg(id, to, from) {
  if (to == null) return {list: S.group.msgs, dm: null};
  const dm = dmOf(from === S.me.id ? to : from);
  return {list: dm.msgs, dm};
}
const atBottom = () => { const b = $("msgs"); return b.scrollHeight - b.scrollTop - b.clientHeight < 80; };
const isActiveGroup = () => S.active && S.active.kind === "group";
const isActiveDm = uid => S.active && S.active.kind === "dm" && S.active.uid === uid;

function onMessage(m) {
  switch (m.type) {
    case "init": {
      S.me = Object.assign({}, S.me, m.me); upsertUser(m.me);
      S.online = new Set(m.online_ids);
      m.history.forEach(x => upsertUser(x.user));
      S.group.msgs = m.history;
      S.chat = m.chat || {slowmode: 0, locked: false};
      loadMembers(); loadDialogs();
      if (S.active && S.active.kind === "dm") reloadActiveDm();
      if (!S.active && !isMobile()) openChat({kind: "group"}); else { renderList(); renderHeader(); renderMessages(true); }
      break; }
    case "message": {
      upsertUser(m.user);
      const mine = m.user.id === S.me.id;
      if (m.to == null) {
        const stick = atBottom();
        S.group.msgs.push(m);
        if (isActiveGroup()) {
          renderMessages(mine || stick);
          if (!mine && !stick) bumpAway();
        } else if (!mine) S.group.unread++;
      } else {
        const pid = partnerOf(m), dm = dmOf(pid);
        if (!S.users.has(pid)) loadMembers();
        dm.last = m;
        if (dm.loaded) dm.msgs.push(m); else dm.buffer.push(m);
        if (isActiveDm(pid)) {
          const stick = atBottom();
          renderMessages(mine || stick);
          if (!mine) {
            if (!document.hidden) { dm.unread = 0; wsSend({type: "read", with: pid}); }
            else dm.unread++;
            if (!stick) bumpAway();
          }
        } else if (!mine) dm.unread++;
      }
      renderList();
      break; }
    case "message_edited": {
      const {list, dm} = findMsg(m.id, m.to, m.from);
      const x = list.find(i => i.id === m.id);
      if (m._h) m.content = m._h.content;
      if (x) {
        if (m._h) Object.assign(x, {content: m._h.content, e2e: m.e2e, verified: m._h.verified, bad: m._h.bad, locked: m._h.locked, _r: m._h._r, reply: m._h.reply});
        else x.content = m.content;
        x.edited = true;
      }
      eachMsg(y => { if (y.reply && y.reply.id === m.id && !y.reply.deleted) y.reply.text = snippetOf(m.content); });
      if (dm && dm.last && dm.last.id === m.id) { dm.last.content = m.content; dm.last.edited = true; if (m._h) Object.assign(dm.last, {e2e: m.e2e, bad: m._h.bad, locked: m._h.locked}); }
      renderMessages(false); renderList();
      break; }
    case "message_deleted": {
      const {list, dm} = findMsg(m.id, m.to, m.from);
      const i = list.findIndex(x => x.id === m.id);
      if (i >= 0) list.splice(i, 1);
      eachMsg(y => { if (y.reply && y.reply.id === m.id) y.reply = {id: m.id, deleted: true}; });
      if (S.editing && S.editing.id === m.id) cancelEdit();
      if (S.replying && S.replying.id === m.id) cancelReply();
      if (VP.id === m.id) voiceStop();
      if (S.sel && S.sel.delete(m.id)) updateSelBar();
      if (dm) {
        dm.buffer = dm.buffer.filter(x => x.id !== m.id);
        if (dm.last && dm.last.id === m.id) { dm.last = dm.msgs.length ? dm.msgs[dm.msgs.length - 1] : null; if (!dm.loaded || !dm.last) loadDialogs(); }
      }
      scheduleRender();
      break; }
    case "chat_settings":
      S.chat = {slowmode: m.slowmode || 0, locked: !!m.locked};
      renderHeader();
      if (isActiveGroup() && !amAdmin()) toast(S.chat.locked ? "Admin umumiy chatni qulfladi" : (S.chat.slowmode ? "Sekin rejim: " + S.chat.slowmode + " soniya" : "Umumiy chat ochildi"), "warn");
      break;
    case "media_removed": {                              // admin faylni o'chirdi (izoh matni qoladi)
      const x = S.group.msgs.find(i => i.id === m.id);
      if (x) { x.image = null; x.thumb = null; x.w = x.h = null; x.file = null; }
      S.imgs.delete(m.id); if (VP.id === m.id) voiceStop();
      const u = S.played.get(m.id); if (u) { URL.revokeObjectURL(u); S.played.delete(m.id); }
      eachMsg(y => { if (y.reply && y.reply.id === m.id) { y.reply.image = false; y.reply.file = false; } });
      renderMessages(false); renderList();
      break; }
    case "e2ee_room": case "e2ee_wrap": loadRoom().catch(() => {}); break;
    case "e2ee_rotate_hint": if (amAdmin()) rotateRoom(m.reason); break;
    case "report_new": toast("Yangi shikoyat keldi (⋮ → Shikoyatlar)", "warn"); break;
    case "chat_cleared": {
      const gone = new Set(S.group.msgs.map(x => x.id));
      eachMsg(y => { if (y.reply && gone.has(y.reply.id)) y.reply = {id: y.reply.id, deleted: true}; });
      S.group.msgs = [];
      if (isActiveGroup()) { cancelEdit(); cancelReply(); exitSelect(); }
      renderMessages(false); renderList();
      toast(m.by === S.me.id ? "Chat tozalandi" : "Admin umumiy chatni tozaladi", "ok");
      break; }
    case "read": {
      const dm = S.dms.get(m.by);
      if (dm) {
        dm.msgs.forEach(x => { if (x.user.id === S.me.id) x.read = true; });
        if (dm.last && dm.last.user.id === S.me.id) dm.last.read = true;
        if (isActiveDm(m.by)) renderMessages(false);
      }
      break; }
    case "presence":
      if (m.online) S.online.add(m.uid); else S.online.delete(m.uid);
      if (!S.users.has(m.uid)) loadMembers();
      renderList(); renderHeader(); refreshModal();
      break;
    case "members_changed": loadMembers(); loadDialogs(); break;
    case "dm_cleared": {
      const other = m.a === S.me.id ? m.b : m.a;
      S.dms.delete(other);
      const wasActive = isActiveDm(other);
      if (wasActive) closeChat();
      renderList();
      toast(m.a === S.me.id ? "Suhbat o'chirildi" : "Suhbat o'chirildi (boshqa tomon o'chirdi)", "ok");
      break; }
    case "user_removed":
      upsertUser(m.user);
      S.members = S.members.filter(x => x.id !== m.user.id); S.online.delete(m.user.id);
      renderList(); renderHeader(); renderMessages(false); refreshModal();
      break;
    case "account_removed": showAuth("Akkauntingiz o'chirildi"); break;
    case "user_update":
      upsertUser(m.user);
      renderList(); renderHeader(); renderMessages(false); refreshModal();
      break;
    case "system":
      toast(m.lines.join("\n"), m.level);
      if (m.level === "warn") { S.group.msgs.push({service: true, text: m.lines.join(" "), ts: Date.now() / 1000}); if (isActiveGroup()) renderMessages(false); }
      break;
    case "banned": showAuth("Siz ban qilindingiz" + (m.reason ? ": " + m.reason : "")); break;
  }
}

async function loadMembers() {
  try {
    const j = await api("/members");
    S.members = j.members; S.online = new Set(j.online_ids);
    j.members.forEach(upsertUser);
    renderList(); renderHeader(); refreshModal();
    serveWraps();
  } catch (_) {}
}
async function loadDialogs() {
  try {
    const j = await api("/dialogs");
    if (X.ready) await X.ready;
    await hydrateAll(j.dialogs.map(d => d.last).filter(Boolean));
    const seen = new Set();
    j.dialogs.forEach(d => {
      upsertUser(d.user); seen.add(d.user.id);
      const dm = dmOf(d.user.id); dm.last = d.last; dm.unread = isActiveDm(d.user.id) ? 0 : d.unread;
    });
    S.dms.forEach((dm, uid) => {                       // serverda yo'q suhbat (masalan, boshqa tomon o'chirgan)
      if (seen.has(uid)) return;
      if (isActiveDm(uid)) { dm.msgs = []; dm.buffer = []; dm.last = null; renderMessages(false); }
      else S.dms.delete(uid);
    });
    renderList();
  } catch (_) {}
}
async function loadDm(uid) {
  const dm = dmOf(uid);
  const j = await api("/dm/" + uid);
  if (X.ready) await X.ready;
  await hydrateAll(j.history);
  const ids = new Set(j.history.map(x => x.id));
  dm.msgs = j.history.concat(dm.buffer.filter(x => !ids.has(x.id))).sort((a, b) => a.id - b.id);
  dm.buffer = []; dm.loaded = true;
  if (dm.msgs.length) dm.last = dm.msgs[dm.msgs.length - 1];
}
async function reloadActiveDm() {
  const uid = S.active.uid;
  try { await loadDm(uid); if (isActiveDm(uid)) { renderMessages(true); wsSend({type: "read", with: uid}); } } catch (_) {}
}

/* ---------------- chap panel: ro'yxat ---------------- */
function itemEl({av, title, sub, subOn, time, unread, active, onclick, onctx}) {
  return h("div", {class: "item" + (active ? " active" : ""), onclick, oncontextmenu: onctx ? e => { e.preventDefault(); e.stopPropagation(); onctx(e.clientX, e.clientY); } : null},
    av,
    h("div", {class: "i-mid"},
      h("div", {class: "i-top"}, h("div", {class: "i-title"}, title), time ? h("span", {class: "i-time", text: time}) : null),
      h("div", {class: "i-bot"}, h("div", {class: "i-sub" + (subOn ? " on" : "")}, sub),
        unread ? h("span", {class: "pill", text: unread > 99 ? "99+" : String(unread)}) : null)));
}
function previewOf(m, withAuthor) {
  if (!m) return "";
  const mine = m.user.id === S.me.id;
  const body = m.locked ? "🔒 Shifrlangan xabar" : m.bad ? "⚠ Shifrni ochib bo'lmadi" : m.content;
  const text = (m.image ? "📷 " : m.file ? (m.file.voice ? "🎤 " : "📎 ") : "") + (body ? body.replace(/\s+/g, " ") : (m.image ? "Rasm" : m.file ? (m.file.voice ? "Ovozli xabar" : m.file.name) : ""));
  if (mine) return [h("b", {text: "Siz: "}), text];
  return withAuthor ? [h("b", {text: m.user.nickname + ": "}), text] : text;
}
function groupItem() {
  const last = [...S.group.msgs].reverse().find(x => !x.service);
  return itemEl({
    av: groupAvatar("m"), title: h("span", {class: "nt", text: "Umumiy chat"}),
    sub: last ? previewOf(last, true) : "Hozircha xabar yo'q", time: last ? listTime(last.ts) : "",
    unread: S.group.unread, active: isActiveGroup(), onclick: () => openChat({kind: "group"}),
  });
}
function dmItem(u, dm) {
  return itemEl({
    av: avatar(u, "m", true), title: nameEl(u), sub: previewOf(dm.last, false), time: listTime(dm.last.ts),
    unread: dm.unread, active: isActiveDm(u.id), onclick: () => openChat({kind: "dm", uid: u.id}),
    onctx: (x, y) => dmMenu(x, y, u.id),
  });
}
function memberItem(u) {
  const sub = (isStaff(u) ? roleLabel(u.role) + " • " : "") + statusText(u);
  return itemEl({
    av: avatar(u, "m", true), title: nameEl(u), sub, subOn: isOnline(u.id),
    active: isActiveDm(u.id), onclick: () => openChat({kind: "dm", uid: u.id}),
  });
}
function renderList() {
  if (!S.me) return;
  $("moreBtn").classList.toggle("hidden", !amAdmin());
  const list = $("list"), top = list.scrollTop;
  list.textContent = "";
  const q = S.query.trim().toLowerCase();
  const match = u => !q || u.nickname.toLowerCase().includes(q) || u.username.toLowerCase().includes(q);
  if (S.tab === "chats") {
    if (!q || "umumiy chat".includes(q)) list.append(groupItem());
    const dms = [...S.dms.entries()].filter(([, d]) => d.last).sort((a, b) => b[1].last.ts - a[1].last.ts);
    dms.forEach(([id, d]) => { const u = U(id); if (match(u)) list.append(dmItem(u, d)); });
    if (q) {
      const shown = new Set(dms.map(([id]) => id));
      const others = S.members.filter(m => m.id !== S.me.id && !shown.has(m.id) && match(m));
      if (others.length) { list.append(h("div", {class: "sect", text: "A'zolar"})); others.forEach(m => list.append(memberItem(U(m.id)))); }
    }
    if (!list.children.length) list.append(h("div", {class: "none", text: "Hech narsa topilmadi"}));
  } else {
    const all = S.members.filter(m => m.id !== S.me.id && match(m)).map(m => U(m.id));
    const on = all.filter(u => isOnline(u.id)), off = all.filter(u => !isOnline(u.id));
    if (on.length) { list.append(h("div", {class: "sect", text: "Onlayn — " + on.length})); on.forEach(u => list.append(memberItem(u))); }
    if (off.length) { list.append(h("div", {class: "sect", text: "Oflayn"})); off.forEach(u => list.append(memberItem(u))); }
    if (!all.length) list.append(h("div", {class: "none", text: S.members.length > 1 ? "Hech narsa topilmadi" : "Hozircha boshqa a'zolar yo'q"}));
  }
  list.scrollTop = top;
  updateBadges();
}
function updateBadges() {
  let total = S.group.unread;
  S.dms.forEach(d => { total += d.unread; });
  const b = $("chatsBadge");
  b.classList.toggle("hidden", !total); b.textContent = total > 99 ? "99+" : String(total);
  document.title = (total ? "(" + total + ") " : "") + APP_NAME;
}
document.querySelectorAll(".tabs button").forEach(btn => btn.addEventListener("click", () => {
  S.tab = btn.dataset.tab;
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x === btn));
  renderList();
}));
$("search").addEventListener("input", e => { S.query = e.target.value; renderList(); });

/* ---------------- menyu ---------------- */
function renderMenu() {
  const menu = $("menu"); menu.textContent = "";
  const dark = document.documentElement.dataset.theme === "dark";
  const add = (ic, text, fn) => menu.append(h("button", {class: "dd-i", type: "button", onclick: () => { menu.classList.add("hidden"); fn(); }}, icon(ic), text));
  add("user", "Mening profilim", () => openProfile(S.me.id));
  add("edit", "Profilni tahrirlash", openSettings);
  add("lock", "Shifrlash: server nimani ko'radi?", () => openInspector("server"));
  add(dark ? "sun" : "moon", dark ? "Kunduzgi mavzu" : "Tungi mavzu", toggleTheme);
  menu.append(h("div", {class: "dd-sep"}));
  add("logout", "Chiqish", logout);
}
$("menuBtn").addEventListener("click", e => { e.stopPropagation(); $("amenu").classList.add("hidden"); renderMenu(); $("menu").classList.toggle("hidden"); });

/* ---------------- admin: 3 nuqta menyusi ---------------- */
function renderAdminMenu() {
  const menu = $("amenu"); menu.textContent = "";
  const add = (ic, text, fn) => menu.append(h("button", {class: "dd-i", type: "button", onclick: () => { menu.classList.add("hidden"); fn(); }}, icon(ic), text));
  add("shield", "IP lar va profillar", () => openAdmin("ips"));
  add("list", "Harakatlar logi", () => openAdmin("log"));
  add("ban", "Bloklangan IP lar", () => openAdmin("blocks"));
  add("attach", "Media boshqaruvi", () => openAdmin("media"));
  add("flag", "Shikoyatlar", () => openAdmin("reports"));
  add("shield", "Moderatsiya sozlamalari", () => openAdmin("mod"));
  menu.append(h("div", {class: "dd-sep"}));
  const clr = h("button", {class: "dd-i", type: "button", onclick: () => { menu.classList.add("hidden"); clearGroupChat(); }}, icon("trash"), "Umumiy chatni tozalash");
  clr.style.color = "var(--err)"; menu.append(clr);
}
$("moreBtn").addEventListener("click", e => {
  e.stopPropagation(); $("menu").classList.add("hidden");
  renderAdminMenu(); $("amenu").classList.toggle("hidden");
});

/* ---------------- chat oynasi ---------------- */
function currentMsgs() {
  if (!S.active) return [];
  return S.active.kind === "group" ? S.group.msgs : dmOf(S.active.uid).msgs;
}
async function openChat(target) {
  if (S.sel) { S.sel = null; $("chat").classList.remove("selecting"); }
  S.active = target;
  cancelRecording(); cancelEdit(); cancelReply(); clearPendingImage(); $("inp").value = ""; autosize(); S.away = 0; bumpAway(true);
  $("empty").classList.add("hidden"); $("chat").classList.remove("hidden");
  document.body.classList.add("in-chat");
  if (target.kind === "group") S.group.unread = 0;
  else {
    const dm = dmOf(target.uid); dm.unread = 0;
    if (!dm.loaded) {
      renderHeader(); $("msgs").textContent = "";
      try { await loadDm(target.uid); } catch (err) { toast(err.message, "error"); }
      if (!isActiveDm(target.uid)) return;
    }
    wsSend({type: "read", with: target.uid});
  }
  renderHeader(); renderMessages(true); renderList();
  if (!isMobile()) $("inp").focus();
}
function closeChat() {
  if (S.sel) { S.sel = null; $("chat").classList.remove("selecting"); }
  S.active = null; cancelEdit(); cancelReply(); clearPendingImage();
  document.body.classList.remove("in-chat");
  if (!isMobile()) { $("chat").classList.add("hidden"); $("empty").classList.remove("hidden"); }
  renderList();
}
function renderHeader() {
  if (!S.active || !S.me) return;
  const av = $("hav"), title = $("htitle"), sub = $("hsub");
  av.textContent = ""; title.textContent = ""; sub.className = "hsub";
  if (S.active.kind === "group") {
    av.append(groupAvatar("m")); title.append(h("span", {class: "nt", text: "Umumiy chat"}));
    sub.textContent = (S.members.length || 1) + " a'zo, " + onlineCount() + " onlayn" + (S.chat.locked ? " • 🔒 qulflangan" : S.chat.slowmode ? " • 🐢 " + S.chat.slowmode + " s" : "") + (X.epoch && !X.rooms.has(X.epoch) ? " • ⏳ kalit kutilmoqda" : "");
  } else {
    const u = U(S.active.uid);
    av.append(avatar(u, "m", true)); title.append(nameEl(u));
    sub.textContent = statusText(u) + (X.changed.has(u.id) ? " • ⚠ kalit o'zgargan" : ""); if (isOnline(u.id)) sub.classList.add("on");
  }
  $("chMore").classList.toggle("hidden", S.active.kind !== "dm");
  const dead = S.active.kind === "dm" && !!U(S.active.uid).deleted;
  $("chat").classList.toggle("dead", dead);
  const locked = S.active.kind === "group" && S.chat.locked && !amAdmin();
  $("chat").classList.toggle("locked", locked);
  if (locked) { cancelEdit(); cancelReply(); clearPendingImage(); }
  if (dead) { cancelEdit(); cancelReply(); clearPendingImage(); }
}
$("hinfo").addEventListener("click", () => {
  if (!S.active) return;
  if (S.active.kind === "group") openGroupInfo(); else openProfile(S.active.uid);
});
$("backBtn").addEventListener("click", closeChat);

function bumpAway(reset) {
  if (reset) S.away = 0; else S.away++;
  const tb = $("tbBadge");
  tb.textContent = String(S.away); tb.classList.toggle("hidden", !S.away);
}
function renderMessages(stick) {
  if (!S.active || !S.me) return;
  const box = $("msgs"), prevTop = box.scrollTop;
  const list = currentMsgs(), isGroup = S.active.kind === "group";
  box.textContent = "";
  let prev = null, lastDay = "";
  if (!list.length) box.append(h("div", {class: "blank", text: isGroup ? "Hozircha xabar yo'q. Birinchi bo'lib yozing 👋" : "Suhbatni boshlang — xabar yozing 👋"}));
  list.forEach((m, i) => {
    if (m.service) { box.append(h("div", {class: "svc", text: m.text})); prev = null; return; }
    const day = dayKey(m.ts);
    if (day !== lastDay) { box.append(h("div", {class: "day", text: dayLabel(m.ts)})); lastDay = day; prev = null; }
    const next = list[i + 1];
    const first = !prev || prev.user.id !== m.user.id || m.ts - prev.ts > 300;
    const last = !next || next.service || next.user.id !== m.user.id || dayKey(next.ts) !== day || next.ts - m.ts > 300;
    box.append(bubbleRow(m, isGroup, first, last));
    prev = m;
  });
  box._stick = !!stick;
  if (stick) { box.scrollTop = box.scrollHeight; bumpAway(true); } else box.scrollTop = prevTop;
  toggleToBottom();
}
function replyQuote(r) {
  const gone = !!r.deleted;
  const q = h("div", {class: "rq" + (gone ? " gone" : ""), role: "button"},
    h("b", {text: gone ? "Xabar" : r.nickname}),
    h("span", {text: gone ? "O'chirilgan xabar" : (r.image ? "📷 " : r.file ? (r.voice ? "🎤 " : "📎 ") : "") + (r.text || (r.image ? "Rasm" : r.file ? (r.file_name || "Fayl") : ""))}));
  q.addEventListener("click", e => { e.stopPropagation(); if (!gone) jumpTo(r.id); });
  return q;
}
function jumpTo(id) {
  const box = $("msgs"), row = box.querySelector('.row[data-id="' + Number(id) + '"]');
  if (!row) { toast("Bu xabar yuklangan tarixda yo'q (eski)", "warn"); return; }
  box._stick = false;
  row.scrollIntoView({block: "center", behavior: "smooth"});
  row.classList.remove("flash"); void row.offsetWidth; row.classList.add("flash");
  setTimeout(() => row.classList.remove("flash"), 1400);
}

/* ---------------- Rasm: avval xira, bosilganda yuklanadi va tiniq ochiladi ---------------- */
function imageBox(m, mine) {
  const ratio = Math.min(2.4, Math.max(0.8, m.w && m.h ? m.w / m.h : 4 / 3));
  // O'zim yuborgan rasm darrov ochiq; boshqalarniki bosilguncha yuklanmaydi.
  if (mine && !S.imgs.has(m.id)) S.imgs.set(m.id, "open");
  const st = S.imgs.get(m.id);
  const box = h("div", {class: "imgbox" + (st === "open" ? " open" : st === "loading" ? " loading" : ""), role: "button", tabindex: "0",
    "aria-label": st === "open" ? "Rasmni kattalashtirish" : "Rasmni yuklash"});
  box.style.aspectRatio = String(ratio);
  if (st !== "open") {
    const th = h("img", {class: "mthumb", alt: "", draggable: "false"});
    th.addEventListener("error", () => { th.remove(); box.classList.add("nothumb"); });
    if (m.thumb) th.src = m.thumb; else box.classList.add("nothumb");
    const dl = h("span", {class: "mdl", "aria-hidden": "true"}, icon("dl"), spinnerEl());
    box.append(th, dl);
  } else {
    box.append(fullImg(m));
  }
  const act = e => {
    e.stopPropagation();
    const cur = S.imgs.get(m.id);
    if (cur === "open") { imgSrcOf(m).then(openLightbox).catch(() => toast("Rasmni ochib bo'lmadi", "error")); return; }
    if (cur === "loading") return;
    startImageLoad(m, box);
  };
  box.addEventListener("click", act);
  box.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(e); } });
  return box;
}
/* ---------------- Fayl xabari: yuklab olish, video/audio ijro etish ---------------- */
const fmtSize = n => n < 1024 ? n + " B" : n < 1048576 ? Math.round(n / 1024) + " KB" : (n / 1048576).toFixed(1) + " MB";
const fileExt = name => { const i = (name || "").lastIndexOf("."); return i > 0 && i < name.length - 1 ? name.slice(i + 1, i + 5).toUpperCase() : "FAYL"; };
const PLAYABLE = /^(video\/(mp4|webm|ogg|quicktime)|audio\/(mpeg|mp3|ogg|wav|x-wav|webm|mp4|aac|flac|x-m4a))$/;
async function fetchFileBlob(m, type) {
  if (m.file.e2e) return new Blob([await e2eFetchBlob(m)], {type});          // shifrlangan fayl: qurilmada ochiladi
  const r = await SC.fetch(m.file.url, {headers: {Authorization: "Bearer " + S.token}});     // shifrlangan kanal orqali, tizim tokeni bilan
  if (!r.ok) throw new Error("fayl");
  return new Blob([r.bytes], {type});
}
async function downloadFile(m, box) {
  if (box.classList.contains("loading")) return;
  box.classList.add("loading");
  try {
    const blob = await fetchFileBlob(m, "application/octet-stream");                           // hech qachon sahifa sifatida ochilmaydi
    const url = URL.createObjectURL(blob), a = h("a", {href: url, download: m.file.name});
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (_) { toast("Faylni yuklab bo'lmadi", "error"); }
  box.classList.remove("loading");
}
async function playFile(m, box) {
  if (box.classList.contains("loading")) return;
  box.classList.add("loading");
  try {
    const blob = await fetchFileBlob(m, m.file.mime);
    S.played.set(m.id, URL.createObjectURL(blob));
    renderMessages(false);
  } catch (_) { toast("Faylni yuklab bo'lmadi", "error"); box.classList.remove("loading"); }
}
function fileBox(m) {
  if (m.file.voice) return voiceBox(m);
  const f = m.file, playable = PLAYABLE.test(f.mime);
  if (playable && S.played.has(m.id)) {
    const el = h(f.mime.startsWith("video/") ? "video" : "audio", {controls: true, preload: "metadata", playsinline: true});
    el.src = S.played.get(m.id);
    return h("div", {class: "mplayer"}, el, h("div", {class: "mpn", text: f.name + " • " + fmtSize(f.size)}));
  }
  const box = h("div", {class: "filebox", role: "button", tabindex: "0", "aria-label": "Faylni yuklab olish: " + f.name});
  const act = h("span", {class: "fdl", "aria-hidden": "true"}, icon("dl"), spinnerEl());
  box.append(h("span", {class: "fico"}, h("b", {text: fileExt(f.name)})),
    h("span", {class: "fmeta"}, h("b", {class: "fname", text: f.name}), h("small", {text: fmtSize(f.size)})));
  if (playable) {
    const pl = h("button", {class: "fplay", type: "button", title: "Ijro etish", "aria-label": "Ijro etish"}, icon("play"));
    pl.addEventListener("click", e => { e.stopPropagation(); playFile(m, box); });
    box.append(pl);
  }
  box.append(act);
  const go = e => { e.stopPropagation(); downloadFile(m, box); };
  box.addEventListener("click", go);
  box.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(e); } });
  return box;
}
function spinnerEl() {
  const NSV = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(NSV, "svg"); s.setAttribute("class", "mspin"); s.setAttribute("viewBox", "0 0 50 50");
  const c = document.createElementNS(NSV, "circle");
  [["cx", 25], ["cy", 25], ["r", 22], ["fill", "none"], ["stroke-width", 3], ["stroke-linecap", "round"]].forEach(([k, v]) => c.setAttribute(k, v));
  s.append(c); return s;
}
/* ---------------- Ovozli xabar: ijro etish (bitta umumiy pleer, qayta chizishda holat saqlanadi) ---------------- */
const VP = {id: null, audio: null, url: null, rate: 1, loading: false};
const fmtDur = s => { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ":" + pad2(s % 60); };
function voiceStop() {
  if (VP.audio) { try { VP.audio.pause(); VP.audio.removeAttribute("src"); VP.audio.load(); } catch (_) {} }
  if (VP.url) URL.revokeObjectURL(VP.url);
  VP.id = VP.audio = VP.url = null; VP.loading = false;
  paintVoices();
}
function paintVoice(box) {
  const id = +box.dataset.vid, cur = VP.id === id, a = cur ? VP.audio : null;
  const dur = a && isFinite(a.duration) && a.duration > 0 ? a.duration : +box.dataset.dur;
  box.classList.toggle("active", !!a);
  box.classList.toggle("playing", !!a && !a.paused);
  box.classList.toggle("loading", cur && VP.loading);
  box.querySelector(".vfill").style.width = (a && dur ? Math.min(100, a.currentTime / dur * 100) : 0) + "%";
  box.querySelector(".vtime").textContent = a && (a.currentTime > 0 || !a.paused) ? fmtDur(a.currentTime) + " / " + fmtDur(dur) : fmtDur(dur);
  box.querySelector(".vspd").textContent = VP.rate + "x";
}
function paintVoices() { document.querySelectorAll(".vbox").forEach(paintVoice); }
async function voiceToggle(m) {
  if (VP.id === m.id && VP.audio) { if (VP.audio.paused) VP.audio.play().catch(() => {}); else VP.audio.pause(); paintVoices(); return; }
  if (VP.loading) return;
  voiceStop();
  VP.id = m.id; VP.loading = true; paintVoices();
  try {
    const blob = await fetchFileBlob(m, "audio/wav");
    if (VP.id !== m.id) return;                                        // yuklanayotganda boshqa narsa bosildi
    const url = URL.createObjectURL(blob), a = new Audio();
    a.preload = "auto"; a.src = url; a.playbackRate = VP.rate;
    ["timeupdate", "play", "pause", "loadedmetadata", "durationchange"].forEach(ev => a.addEventListener(ev, paintVoices));
    a.addEventListener("ended", () => { a.currentTime = 0; paintVoices(); });
    a.addEventListener("error", () => { if (VP.audio === a) { toast("Ovozni ijro etib bo'lmadi", "error"); voiceStop(); } });
    VP.audio = a; VP.url = url; VP.loading = false; paintVoices();
    await a.play().catch(() => {});                                    // iOS: ruxsat bermasa, yana bir bosish ijro etadi
  } catch (_) { if (VP.id === m.id) { toast("Ovozni yuklab bo'lmadi", "error"); voiceStop(); } }
}
function voiceBox(m) {
  const f = m.file, dur = f.dur || Math.max(1, (f.size - 44) / 32000);
  const box = h("div", {class: "vbox"});
  box.dataset.vid = m.id; box.dataset.dur = dur;
  const play = h("button", {class: "vplay", type: "button", "aria-label": "Ovozli xabarni ijro etish"}, icon("play", "ic vi-play"), icon("pause", "ic vi-pause"), spinnerEl());
  play.addEventListener("click", e => { e.stopPropagation(); voiceToggle(m); });
  const fill = h("div", {class: "vfill"}), track = h("div", {class: "vtrack"}, h("div", {class: "vline"}, fill));
  track.addEventListener("click", e => {                               // bosilgan joyga o'tish (faqat yuklangan bo'lsa)
    e.stopPropagation();
    const a = VP.id === m.id ? VP.audio : null; if (!a || !isFinite(a.duration) || a.duration <= 0) return;
    const r = track.getBoundingClientRect(); a.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * a.duration; paintVoices();
  });
  const spd = h("button", {class: "vspd", type: "button", title: "Tezlik", "aria-label": "Ijro tezligi"});
  spd.addEventListener("click", e => { e.stopPropagation(); VP.rate = VP.rate === 1 ? 1.5 : VP.rate === 1.5 ? 2 : 1; if (VP.audio) VP.audio.playbackRate = VP.rate; paintVoices(); });
  box.append(play, h("div", {class: "vmid"}, track, h("div", {class: "vmeta"}, h("span", {class: "vtime"}), spd)));
  paintVoice(box);
  return box;
}
function fullImg(m) {
  const img = h("img", {class: "mimg", alt: "Rasm", draggable: "false"});
  img.addEventListener("load", () => { const b = $("msgs"); if (b._stick) b.scrollTop = b.scrollHeight; });
  imgSrcOf(m).then(u => { img.src = u; }).catch(() => {});
  return img;
}
function startImageLoad(m, box) {
  S.imgs.set(m.id, "loading"); box.classList.add("loading");
  const t0 = performance.now(), pre = new Image();
  const done = ok => {
    const wait = Math.max(0, 550 - (performance.now() - t0));      // animatsiya ko'rinib o'tishi uchun
    setTimeout(() => {
      if (!ok) {                                                    // xato: yana bosib ko'rish mumkin
        S.imgs.delete(m.id); toast("Rasmni yuklab bo'lmadi", "error");
        const b = document.querySelector('#msgs .row[data-id="' + m.id + '"] .imgbox'); if (b) b.classList.remove("loading");
        return;
      }
      S.imgs.set(m.id, "open");
      const cur = document.querySelector('#msgs .row[data-id="' + m.id + '"] .imgbox');   // qayta chizilgan bo'lishi mumkin
      if (!cur) return;
      const img = fullImg(m); img.classList.add("reveal");
      cur.classList.remove("loading"); cur.classList.add("open"); cur.setAttribute("aria-label", "Rasmni kattalashtirish");
      cur.append(img);
      void cur.offsetWidth;
      requestAnimationFrame(() => cur.classList.add("clear"));
      setTimeout(() => cur.querySelectorAll(".mthumb,.mdl").forEach(x => x.remove()), 450);
    }, wait);
  };
  pre.onload = () => done(true); pre.onerror = () => done(false);
  imgSrcOf(m).then(u => { pre.src = u; }).catch(() => done(false));
}
function bubbleRow(m, isGroup, first, last) {
  const mine = m.user.id === S.me.id, u = U(m.user.id);
  const row = h("div", {class: "row" + (mine ? " mine" : "") + (first ? " first" : "") + (last ? " last" : "") + (isGroup ? "" : " dm")});
  row.dataset.id = m.id;
  if (S.sel) {
    const can = canDelete(m);
    row.classList.add(can ? "selectable" : "locked");
    if (can) {
      if (S.sel.has(m.id)) row.classList.add("selected");
      row.append(h("span", {class: "chk", "aria-hidden": "true"}, icon("check")));
    }
    row.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); toggleSel(m, row); }, true);
  }
  const slot = h("div", {class: "slot"});
  // Telegramdagidek: bir odamning ketma-ket xabarlarida avatar faqat eng oxirgisining yonida ko'rinadi,
  // qolganlarida o'sha joy bo'sh qoladi (xabarlar bir tekis turadi).
  if (isGroup && !mine && last) { const a = avatar(u, "s"); a.style.cursor = "pointer"; a.addEventListener("click", () => openProfile(u.id)); slot.append(a); }
  const meta = h("span", {class: "meta"});
  if (m.edited) meta.append("tahrirlangan ");
  if (m.e2e) meta.append(h("span", {class: "lk" + (m.locked ? "" : (m.verified && !m.bad ? " ok" : " bad")),
    title: m.locked ? "Shifrlangan, kalit kutilmoqda" : m.verified && !m.bad ? "Uchdan-uchga shifrlangan, imzosi tasdiqlangan" : "Imzo yoki shifrni tekshirib bo'lmadi!",
    text: m.locked ? "🔒" : m.verified && !m.bad ? "🔒" : "⚠"}), " ");
  else if (m.legacy) meta.append(h("span", {class: "lk bad", title: "Eski xabar: E2EE'dan oldin yozilgan, server o'qiy oladi", text: "🔓"}), " ");
  meta.append(hhmm(m.ts));
  if (mine && m.to != null) meta.append(icon(m.read ? "checks" : "check", m.read ? "ic rd" : "ic"));
  const bubble = tint(h("div", {class: "bubble" + (isStaff(u) ? " prem " + u.role : "") + (m.image ? " has-img" + (m.content ? "" : " img-only") : "") + (m.file ? " has-file" + (m.file.voice ? " has-voice" : "") : "")}), u);
  if (isGroup && !mine && first) {
    const nm = h("div", {class: "bname"}, nameEl(u, {colored: true}));
    nm.addEventListener("click", () => openProfile(u.id));
    bubble.append(nm);
  }
  if (m.reply) bubble.append(replyQuote(m.reply));
  if (m.image) bubble.append(imageBox(m, mine));
  if (m.file) bubble.append(fileBox(m));
  const more = h("button", {class: "more", type: "button", "aria-label": "Amallar"}, icon("down"));
  more.addEventListener("click", e => { e.stopPropagation(); const r = more.getBoundingClientRect(); openCtx(r.left, r.bottom + 4, m); });
  const shown = m.locked ? "🔒 Xabar kaliti kutilmoqda…" : m.bad ? "⚠ Shifrni ochib bo'lmadi" : m.content;
  if (shown || !(m.image || m.file)) bubble.append(h("div", {class: "btext" + (m.locked || m.bad ? " dim" : ""), text: shown}));
  bubble.append(meta, more);
  bubble.addEventListener("contextmenu", e => { e.preventDefault(); if (S.sel) return toggleSel(m, row); openCtx(e.clientX, e.clientY, m); });
  let timer = null;   // sensorli ekranda uzoq bosish
  bubble.addEventListener("touchstart", e => { if (S.sel) return; const t = e.touches[0]; timer = setTimeout(() => openCtx(t.clientX, t.clientY, m), 480); }, {passive: true});
  ["touchend", "touchmove", "touchcancel"].forEach(ev => bubble.addEventListener(ev, () => clearTimeout(timer), {passive: true}));
  row.append(slot, bubble);
  return row;
}
function toggleToBottom() {
  const b = $("msgs");
  $("toBottom").classList.toggle("hidden", b.scrollHeight - b.scrollTop - b.clientHeight < 240);
}
$("msgs").addEventListener("scroll", () => { $("msgs")._stick = atBottom(); toggleToBottom(); if (atBottom()) bumpAway(true); closeCtx(); });
$("toBottom").addEventListener("click", () => { const b = $("msgs"); b.scrollTop = b.scrollHeight; bumpAway(true); });



/* ---------------- Shaxsiy suhbat menyusi / suhbatni o'chirish ---------------- */
function openMenu(x, y, items) {
  S.ctxAt = Date.now();
  const ctx = $("ctx"); ctx.textContent = "";
  items.forEach(it => {
    const b = h("button", {class: "dd-i", type: "button", onclick: () => { closeCtx(); it.fn(); }}, icon(it.ic), it.text);
    if (it.danger) b.style.color = "var(--err)";
    ctx.append(b);
  });
  ctx.classList.remove("hidden");
  const w = ctx.offsetWidth, hgt = ctx.offsetHeight;
  ctx.style.left = Math.max(8, Math.min(x, innerWidth - w - 8)) + "px";
  ctx.style.top = Math.max(8, Math.min(y, innerHeight - hgt - 8)) + "px";
}
function dmMenu(x, y, uid) {
  openMenu(x, y, [
    {ic: "user", text: "Profilni ko'rish", fn: () => openProfile(uid)},
    {ic: "trash", text: "Suhbatni o'chirish", danger: true, fn: () => deleteDmChat(uid)},
  ]);
}
$("chMore").addEventListener("click", e => {
  e.stopPropagation();
  if (!S.active || S.active.kind !== "dm") return;
  const r = $("chMore").getBoundingClientRect();
  dmMenu(r.right - 200, r.bottom + 4, S.active.uid);
});
async function deleteDmChat(uid) {
  const u = U(uid);
  const ok = await confirmDlg("Bu suhbat (" + u.nickname + " bilan) ikkala tomon uchun ham butunlay o'chiriladi: xabarlar va rasmlar ikkalangizdan ham yo'qoladi. Buni qaytarib bo'lmaydi.",
    {title: "Suhbatni o'chirish", okText: "O'chirish", danger: true});
  if (ok) wsSend({type: "delete_dm", with: uid});
}

/* ---------------- Belgilash rejimi: ko'p xabarni birdaniga o'chirish ---------------- */
let renderQueued = false;
function scheduleRender() {                       // ketma-ket o'chirishlarda bir kadrda bir marta chizish
  if (renderQueued) return; renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderMessages(false); renderList(); });
}
function enterSelect(firstId) {
  if (!S.active) return;
  cancelEdit(); cancelReply();
  S.sel = new Set(); if (firstId != null) S.sel.add(firstId);
  $("chat").classList.add("selecting");
  renderMessages(false); updateSelBar();
}
function exitSelect() {
  if (!S.sel) return;
  S.sel = null; $("chat").classList.remove("selecting");
  renderMessages(false);
}
function toggleSel(m, row) {
  if (!S.sel || !canDelete(m)) return;
  if (S.sel.has(m.id)) S.sel.delete(m.id); else S.sel.add(m.id);
  if (row) row.classList.toggle("selected", S.sel.has(m.id));
  updateSelBar();
}
function updateSelBar() {
  if (!S.sel) return;
  $("selCount").textContent = String(S.sel.size);
  $("selDel").disabled = !S.sel.size;
  const all = currentMsgs().filter(x => !x.service && canDelete(x));
  $("selAll").textContent = all.length && all.every(x => S.sel.has(x.id)) ? "Bekor" : "Hammasi";
}
$("selCancel").addEventListener("click", exitSelect);
$("selAll").addEventListener("click", () => {
  if (!S.sel) return;
  const all = currentMsgs().filter(x => !x.service && canDelete(x));
  if (all.length && all.every(x => S.sel.has(x.id))) S.sel.clear(); else all.forEach(x => S.sel.add(x.id));
  document.querySelectorAll("#msgs .row[data-id]").forEach(r => r.classList.toggle("selected", S.sel.has(Number(r.dataset.id))));
  updateSelBar();
});
$("selDel").addEventListener("click", async () => {
  if (!S.sel || !S.sel.size) return;
  const ids = [...S.sel], n = ids.length;
  const ok = await confirmDlg(n + " ta xabar o'chirilsinmi?", {title: "Xabarlarni o'chirish", okText: "O'chirish", danger: true});
  if (!ok || !S.sel) return;
  for (let i = 0; i < ids.length; i += 200) wsSend({type: "delete_many", ids: ids.slice(i, i + 200)});
  exitSelect();
});
async function clearGroupChat() {
  if (!amAdmin()) return;
  const ok = await confirmDlg("Umumiy chatdagi BARCHA xabarlar hamma uchun o'chiriladi. Buni qaytarib bo'lmaydi.",
    {title: "Chatni tozalash", okText: "Tozalash", danger: true});
  if (ok) wsSend({type: "clear_chat"});
}

/* ---------------- kontekst menyu ---------------- */
function canDelete(m) {
  if (m.user.id === S.me.id) return true;
  if (m.to != null || !amAdmin()) return false;
  const t = U(m.user.id);
  return t.role === "user" || (t.role === "admin" && S.me.role === "owner");
}
function openCtx(x, y, m) {
  S.ctxAt = Date.now();
  const ctx = $("ctx"); ctx.textContent = "";
  const add = (ic, text, fn, danger) => {
    const b = h("button", {class: "dd-i", type: "button", onclick: () => { closeCtx(); fn(); }}, icon(ic), text);
    if (danger) b.style.color = "var(--err)";
    ctx.append(b);
  };
  const usable = !m.locked && !m.bad;
  if (usable && !m.legacy) add("reply", "Javob berish", () => startReply(m));
  if (m.content && usable) add("copy", "Nusxalash", () => copyText(m.content));
  if (m.user.id !== S.me.id) add("user", "Profilni ko'rish", () => openProfile(m.user.id));
  if (m.user.id !== S.me.id && m.to == null && !m.service) add("flag", "Shikoyat qilish", () => reportMessage(m));
  if (m.user.id === S.me.id && usable && !m.legacy) add("edit", "Tahrirlash", () => startEdit(m));
  if (canDelete(m)) add("select", "Belgilash", () => enterSelect(m.id));
  if (canDelete(m)) add("trash", "O'chirish", async () => { if (await confirmDlg("Bu xabar o'chirilsinmi?", {title: "Xabarni o'chirish", okText: "O'chirish", danger: true})) wsSend({type: "delete", id: m.id}); }, true);
  ctx.classList.remove("hidden");
  const w = ctx.offsetWidth, hgt = ctx.offsetHeight;
  ctx.style.left = Math.max(8, Math.min(x, innerWidth - w - 8)) + "px";
  ctx.style.top = Math.max(8, Math.min(y, innerHeight - hgt - 8)) + "px";
}
function closeCtx() { $("ctx").classList.add("hidden"); }
async function reportMessage(m) {
  const reason = await promptDlg("Shikoyat qilish", m.e2e
    ? "Xabarlar shifrlangan, adminlar ularni o'qiy olmaydi. Shikoyat yuborsangiz, FAQAT shu bitta xabarning matni adminlarga ochib beriladi. Nima uchun shikoyat qilyapsiz? (ixtiyoriy)"
    : "Nima uchun shikoyat qilyapsiz? (ixtiyoriy)", "", {okText: "Yuborish", placeholder: "Sabab"});
  if (reason === null) return;
  try { await api("/report", {method: "POST", body: {message_id: m.id, reason, evidence: m.e2e ? (m.content || "") : ""}}); toast("Shikoyat adminlarga yuborildi", "ok"); }
  catch (err) { toast(err.message, "error"); }
}
document.addEventListener("click", e => {
  if (Date.now() - (S.ctxAt || 0) > 350) closeCtx();
  if (!e.target.closest("#menu") && !e.target.closest("#menuBtn")) $("menu").classList.add("hidden");
  if (!e.target.closest("#amenu") && !e.target.closest("#moreBtn")) $("amenu").classList.add("hidden");
});
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); toast("Nusxalandi", "ok"); }
  catch (_) {
    const ta = h("textarea", {class: "offscreen"}); ta.value = t; document.body.append(ta); ta.select();
    try { document.execCommand("copy"); toast("Nusxalandi", "ok"); } catch (_e) {}
    ta.remove();
  }
}

/* ---------------- yozish, tahrirlash ---------------- */
const inp = $("inp");
function autosize() { inp.style.height = "auto"; inp.style.height = Math.min(inp.scrollHeight, 140) + "px"; syncSend(); }
function syncSend() {
  $("sendBtn").classList.toggle("on", !!inp.value.trim() || !!S.pendingImg);
  $("composer").classList.toggle("has-text", !!inp.value.trim() || !!S.pendingImg || !!S.editing);   // matn bor: yuborish tugmasi, yo'q: mikrofon
}
inp.addEventListener("input", autosize);
inp.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && !COARSE && !e.isComposing) { e.preventDefault(); submit(); }
  else if (e.key === "Escape") { if (S.editing) cancelEdit(); else if (S.pendingImg) clearPendingImage(); else if (S.replying) cancelReply(); }
  else if (e.key === "ArrowUp" && !inp.value && S.active) {       // oxirgi o'z xabarini tahrirlash
    const mine = [...currentMsgs()].reverse().find(x => !x.service && x.user.id === S.me.id && !x.legacy && !x.bad && !x.locked);
    if (mine) { e.preventDefault(); startEdit(mine); }
  }
});
inp.addEventListener("paste", e => {                              // Ctrl+V bilan rasm qo'yish
  const f = (e.clipboardData && e.clipboardData.files || [])[0];
  if (f) { e.preventDefault(); setPendingImage(f); }
});
$("sendBtn").addEventListener("click", submit);

function startEdit(m) {
  cancelReply(); clearPendingImage();
  S.editing = m; inp.value = m.content; autosize(); inp.focus();
  $("ebText").textContent = m.content ? m.content.replace(/\s+/g, " ") : (m.file ? (m.file.voice ? "🎤 Ovozli xabar izohi" : "📎 Fayl izohi") : "📷 Rasm izohi");
  $("editbar").classList.remove("hidden");
}
function cancelEdit() {
  if (!S.editing) return;
  S.editing = null; inp.value = ""; autosize(); $("editbar").classList.add("hidden");
}
$("ebCancel").addEventListener("click", cancelEdit);

function startReply(m) {
  cancelEdit();
  S.replying = replyInfo(m);
  $("rbName").textContent = m.user.nickname;
  $("rbText").textContent = (m.image ? "📷 " : m.file ? (m.file.voice ? "🎤 " : "📎 ") : "") + (m.content ? m.content.replace(/\s+/g, " ") : (m.file ? (m.file.voice ? "Ovozli xabar" : m.file.name) : "Rasm"));
  $("replybar").classList.remove("hidden");
  inp.focus();
}
function cancelReply() { S.replying = null; $("replybar").classList.add("hidden"); }
$("rbCancel").addEventListener("click", cancelReply);

/* ---- rasm yuborish (izoh bilan) ---- */
const IMG_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"], MAX_MEDIA = 50 * 1024 * 1024;
async function shrinkImage(f) {              // katta fotolarni yuborishdan oldin kichraytiradi (GIF tegilmaydi)
  if (f.type === "image/gif" || f.size <= 1.5 * 1024 * 1024 || !self.createImageBitmap) return f;
  try {
    const bmp = await createImageBitmap(f), k = Math.min(1, 1920 / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas"); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.85));
    return blob && blob.size < f.size ? blob : f;
  } catch (_) { return f; }
}
async function setPendingImage(file) {              // istalgan turdagi fayl (50 MB gacha)
  if (!S.active || !file) return;
  if (S.active.kind === "group" && S.chat.locked && !amAdmin()) { toast("Umumiy chat qulflangan", "error"); return; }
  const isImg = IMG_TYPES.includes(file.type);
  const blob = isImg ? await shrinkImage(file) : file;
  if (blob.size > MAX_MEDIA) { toast("Fayl 50 MB dan oshmasligi kerak", "error"); return; }
  if (!blob.size) { toast("Fayl bo'sh", "error"); return; }
  cancelEdit(); clearPendingImage();
  const ext = blob.type === "image/jpeg" ? "jpg" : (blob.type.split("/")[1] || "png");
  S.pendingImg = {blob, isImg, url: isImg ? URL.createObjectURL(blob) : null, name: isImg ? "rasm." + ext : (file.name || "fayl")};
  $("ibThumb").classList.toggle("hidden", !isImg); $("ibIcon").classList.toggle("hidden", isImg);
  if (isImg) $("ibThumb").src = S.pendingImg.url; else $("ibThumb").removeAttribute("src");
  $("ibTitle").textContent = isImg ? "Rasm" : S.pendingImg.name;
  $("ibInfo").textContent = "Izoh yozib yuboring (ixtiyoriy) • " + fmtSize(blob.size);
  $("imgbar").classList.remove("hidden");
  syncSend(); inp.focus();
}
function clearPendingImage() {
  if (S.pendingImg && S.pendingImg.url) URL.revokeObjectURL(S.pendingImg.url);
  S.pendingImg = null; $("ibThumb").removeAttribute("src"); $("imgbar").classList.add("hidden"); syncSend();
}
$("attachBtn").addEventListener("click", () => $("imgFile").click());
$("imgFile").addEventListener("change", () => { const f = $("imgFile").files[0]; $("imgFile").value = ""; if (f) setPendingImage(f); });
$("ibCancel").addEventListener("click", clearPendingImage);
["dragenter", "dragover"].forEach(ev => $("chat").addEventListener(ev, e => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); $("chat").classList.add("drop"); } }));
["dragleave", "drop"].forEach(ev => $("chat").addEventListener(ev, e => { if (ev === "dragleave" && $("chat").contains(e.relatedTarget)) return; $("chat").classList.remove("drop"); }));
$("chat").addEventListener("drop", e => { const f = e.dataTransfer && e.dataTransfer.files[0]; if (f) { e.preventDefault(); setPendingImage(f); } });

async function sendImage(caption) {
  if (S.sending) return;
  S.sending = true; $("sendBtn").disabled = true;
  const img = S.pendingImg, keep = $("ibInfo").textContent;
  try {
    const ctx = await keyForActive();
    $("ibInfo").textContent = "Shifrlanmoqda…";
    let blob = img.blob, f = {name: img.name, mime: blob.type || "application/octet-stream", size: blob.size, img: false};
    if (img.isImg) { const c = await cleanImage(blob); blob = c.blob; f = Object.assign(f, {mime: blob.type || f.mime, size: blob.size, img: true, w: c.w, h: c.h, th: c.th}); }
    const e = await E2E.encryptFile(new Uint8Array(await blob.arrayBuffer()));
    f.k = e.key;
    $("ibInfo").textContent = "Yuborilmoqda… (" + fmtSize(e.blob.length) + ")";
    const r = await SC.fetch("/api/e2ee/blob", {method: "POST", headers: {Authorization: "Bearer " + S.token, "Content-Type": "application/octet-stream"}, body: e.blob});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Fayl yuklanmadi");
    const payload = {t: caption, f}; if (S.replying) payload.r = S.replying;
    const msg = {type: "send", e2e: await sealFor(ctx, payload), blob: j.blob};
    if (S.active.kind === "dm") msg.to = S.active.uid;
    if (!wsSend(msg)) throw new Error("Ulanish yo'q");
    inp.value = ""; clearPendingImage(); cancelReply(); autosize();
  } catch (err) { toast(err.message, "error"); if (S.pendingImg) $("ibInfo").textContent = keep; }
  S.sending = false; $("sendBtn").disabled = false;
}
async function submit() {
  const text = inp.value.trim();
  if (!S.active || S.sending) return;
  if (S.active.kind === "dm" && U(S.active.uid).deleted) { toast("Bu akkaunt o'chirilgan. Xabar yuborib bo'lmaydi", "error"); return; }
  if (S.pendingImg) { sendImage(text); return; }
  if (!S.editing && !text) return;
  if (S.editing && !text && !S.editing._f) return;
  if (S.editing && text === S.editing.content) { cancelEdit(); return; }
  S.sending = true;
  try {
    const ctx = await keyForActive(), payload = {t: text};
    if (S.editing) {                                                // tahrir: javob va fayl ma'lumoti saqlanadi, matn almashadi
      const m = S.editing;
      if (m._r) payload.r = m._r; if (m._f) payload.f = m._f;
      if (wsSend({type: "edit", id: m.id, e2e: await sealFor(ctx, payload)})) cancelEdit();
    } else {
      if (S.replying) payload.r = S.replying;
      const msg = {type: "send", e2e: await sealFor(ctx, payload)};
      if (S.active.kind === "dm") msg.to = S.active.uid;
      if (wsSend(msg)) { inp.value = ""; cancelReply(); autosize(); inp.focus(); }
    }
  } catch (err) { toast(err.message, "error"); }
  S.sending = false;
}
/* ---------------- Ovozli xabar: yozish -> ovozni o'zgartirish -> shifrlash -> yuborish ----------------
   Mikrofon tugmasi: 1-bosish — yozishni boshlaydi, 2-bosish — to'xtatib yuboradi. 🗑 yoki Esc — bekor qilish.
   Xom ovoz faqat shu qurilma xotirasida, darhol o'zgartiriladi; serverga faqat o'zgargan va E2EE bilan shifrlangan ovoz boradi. */
function setRecUi(mode) {                                           // "off" | "rec" | "busy"
  const c = $("composer");
  c.classList.toggle("recording", mode !== "off"); c.classList.toggle("rec-busy", mode === "busy");
  $("micBtn").classList.toggle("on", mode === "rec"); $("micBtn").disabled = mode === "busy"; $("recCancel").disabled = mode === "busy";
  $("micBtn").setAttribute("aria-label", mode === "rec" ? "Yuborish" : "Ovozli xabar yozish");
  $("recLbl").textContent = mode === "busy" ? "Ovoz tayyorlanmoqda…" : "Ovoz o'zgartirilib shifrlanadi";
  if (mode === "off") $("recTime").textContent = "0:00";
}
function cancelRecording() {
  if (!S.rec || S.recBusy) return;
  const r = S.rec; S.rec = null; clearInterval(S.recTimer);
  r.cancel().catch(() => {}); setRecUi("off");
}
async function startRecording() {
  if (S.rec || S.recBusy || S.sending || !S.active) return;
  if (S.editing || S.pendingImg || inp.value.trim()) return;
  if (S.active.kind === "group" && S.chat.locked && !amAdmin()) { toast("Umumiy chat qulflangan", "error"); return; }
  if (S.active.kind === "dm" && U(S.active.uid).deleted) { toast("Bu akkaunt o'chirilgan. Xabar yuborib bo'lmaydi", "error"); return; }
  const at = S.active; let rec = null;
  $("micBtn").disabled = true;                                        // ruxsat so'ralayotganda qayta bosilmasin
  try {
    rec = await Voice.record({
      onLimit: () => { toast("Yozuv " + Math.round(Voice.MAX_SEC / 60) + " daqiqaga yetdi, yuborilmoqda", "warn"); finishRecording(); },
      onLost: () => { if (rec && S.rec === rec) { cancelRecording(); toast("Mikrofon uzildi, yozuv bekor qilindi", "error"); } },
    });
    if (S.active !== at) { rec.cancel().catch(() => {}); rec = null; return; }   // ruxsat so'ralayotganda chat almashtirildi
    S.rec = rec; setRecUi("rec");
    S.recTimer = setInterval(() => { if (S.rec) $("recTime").textContent = fmtDur(S.rec.elapsed()); }, 250);
  } catch (err) { toast(err.message || "Mikrofonni ochib bo'lmadi", "error"); }
  finally { $("micBtn").disabled = false; }
}
async function sendVoice(wav, dur) {
  const ctx = await keyForActive(), target = S.active;
  const e = await E2E.encryptFile(new Uint8Array(await wav.arrayBuffer()));
  const f = {name: "ovozli-xabar.wav", mime: "audio/wav", size: wav.size, img: false, k: e.key, vo: 1, d: Math.round(dur * 10) / 10};
  const r = await SC.fetch("/api/e2ee/blob", {method: "POST", headers: {Authorization: "Bearer " + S.token, "Content-Type": "application/octet-stream"}, body: e.blob});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Ovoz yuklanmadi");
  const payload = {t: "", f}; if (S.replying) payload.r = S.replying;
  const msg = {type: "send", e2e: await sealFor(ctx, payload), blob: j.blob};
  if (target.kind === "dm") msg.to = target.uid;
  if (!wsSend(msg)) throw new Error("Ulanish yo'q");
  cancelReply();
}
async function finishRecording() {
  const rec = S.rec; if (!rec || S.recBusy) return;
  S.recBusy = true; S.sending = true; clearInterval(S.recTimer); setRecUi("busy");
  const at = S.active;
  try {
    const raw = await rec.stop();
    if (!raw) throw new Error("Yozuv olinmadi");
    const out = await Voice.disguise(raw);                          // asl ovoz shu yerda o'zgaradi
    if (!out) { toast("Ovoz juda qisqa — yuborilmadi", "warn"); return; }
    if (S.active !== at) { toast("Chat almashtirildi — ovozli xabar yuborilmadi", "warn"); return; }
    await sendVoice(out.wav, out.duration);
  } catch (err) { toast(err.message || "Ovozli xabar yuborilmadi", "error"); }
  finally { S.rec = null; S.recBusy = false; S.sending = false; setRecUi("off"); syncSend(); }
}
$("micBtn").addEventListener("click", () => { if (S.rec) finishRecording(); else startRecording(); });
$("recCancel").addEventListener("click", cancelRecording);
document.addEventListener("keydown", e => { if (e.key === "Escape" && S.rec && !S.recBusy) { e.preventDefault(); e.stopPropagation(); cancelRecording(); } }, true);
document.addEventListener("visibilitychange", () => { if (document.hidden && S.rec && !S.recBusy) { cancelRecording(); toast("Ilovadan chiqilgani uchun yozuv bekor qilindi", "warn"); } });
addEventListener("pagehide", cancelRecording);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.active && S.active.kind === "dm") {
    const dm = dmOf(S.active.uid);
    if (dm.unread) { dm.unread = 0; wsSend({type: "read", with: S.active.uid}); renderList(); }
  }
});


/* ---------------- Telegram uslubidagi dialoglar ---------------- */
function askDialog({title, text, okText = "OK", cancelText = "Bekor qilish", danger = false, input = null, alertOnly = false}) {
  return new Promise(resolve => {
    const root = $("dlg"), prevFocus = document.activeElement;
    let field = null;
    const done = v => {
      root.classList.add("hidden"); root.setAttribute("aria-hidden", "true"); root.textContent = "";
      document.removeEventListener("keydown", onKey, true);
      if (prevFocus && prevFocus.focus) try { prevFocus.focus(); } catch (_) {}
      resolve(v);
    };
    const ok = () => done(input ? field.value : true);
    const cancel = () => done(input ? null : false);
    const onKey = e => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
      else if (e.key === "Enter" && !(e.target && e.target.tagName === "BUTTON")) { e.preventDefault(); e.stopPropagation(); ok(); }
    };
    const card = h("div", {class: "dlg-card", role: alertOnly ? "alertdialog" : "dialog", "aria-modal": "true"});
    if (title) card.append(h("h3", {class: "dlg-t", text: title}));
    if (text) card.append(h("p", {class: "dlg-m", text}));
    if (input) { field = h("input", {class: "dlg-in", type: input.type || "text", autocomplete: "off", spellcheck: "false", placeholder: input.placeholder || ""}); field.value = input.value || ""; card.append(field); }
    const btns = h("div", {class: "dlg-b"});
    if (!alertOnly) btns.append(h("button", {class: "dlg-btn", type: "button", text: cancelText, onclick: cancel}));
    const okBtn = h("button", {class: "dlg-btn" + (danger ? " danger" : ""), type: "button", text: okText, onclick: ok});
    btns.append(okBtn); card.append(btns);
    root.textContent = ""; root.append(card);
    root.onmousedown = e => { if (e.target === root) cancel(); };
    root.classList.remove("hidden"); root.setAttribute("aria-hidden", "false");
    document.addEventListener("keydown", onKey, true);
    setTimeout(() => { (field || okBtn).focus(); if (field) field.select(); }, 30);
  });
}
const confirmDlg = (text, o = {}) => askDialog({title: o.title, text, okText: o.okText || "OK", danger: !!o.danger});
const promptDlg = (title, text, value = "", o = {}) => askDialog({title, text, input: {value, placeholder: o.placeholder, type: o.type}, okText: o.okText || "OK", danger: !!o.danger});

/* Brauzerning o'z o'ng-tugma menyusini yopish (matn kiritish maydonlaridan tashqari) */
document.addEventListener("contextmenu", e => {
  if (e.target.closest && e.target.closest("input, textarea")) return;   // nusxalash/qo'yish uchun qoladi
  e.preventDefault();
  if (!e.target.closest(".bubble")) closeCtx();
});

/* ---------------- modal ---------------- */
function showModal(node) {
  const sheet = $("sheet"), top = sheet.scrollTop;
  sheet.textContent = ""; sheet.append(node);
  $("modal").classList.remove("hidden");
  sheet.scrollTop = top;
}
function openModal(build, live, wide, fit) { S.modal = {build, live: !!live}; $("sheet").classList.toggle("wide", !!wide); $("sheet").classList.toggle("fit", !!fit); showModal(build()); }
function closeModal() { S.modal = null; $("modal").classList.add("hidden"); $("sheet").classList.remove("wide", "fit"); $("sheet").textContent = ""; }
function refreshModal() { if (S.modal && S.modal.live) showModal(S.modal.build()); }
$("modal").addEventListener("mousedown", e => { if (e.target === $("modal")) closeModal(); });
function openLightbox(url) { $("lbImg").src = url; $("lightbox").classList.remove("hidden"); }
function closeLightbox() { $("lightbox").classList.add("hidden"); $("lbImg").removeAttribute("src"); }
$("lightbox").addEventListener("click", closeLightbox);
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (!$("lightbox").classList.contains("hidden")) closeLightbox();
  else if (S.sel && !S.modal && $("ctx").classList.contains("hidden")) exitSelect();
  else if (!$("ctx").classList.contains("hidden")) closeCtx();
  else if (S.modal) closeModal();
});

function sheetHead(title, onBack) {
  return h("div", {class: "sh-head"},
    onBack ? h("button", {class: "icon-btn", type: "button", onclick: onBack, "aria-label": "Orqaga"}, icon("back")) : null,
    h("span", {text: title}),
    h("button", {class: "icon-btn", type: "button", onclick: closeModal, "aria-label": "Yopish"}, icon("close")));
}

/* ---------- guruh ma'lumoti ---------- */
function openGroupInfo() {
  let filter = "";
  const build = () => {
    const wrap = h("div", {});
    const total = S.members.length || 1;
    wrap.append(
      h("div", {class: "sh-head"}, h("span", {text: "Guruh ma'lumoti"}),
        h("button", {class: "icon-btn", type: "button", onclick: closeModal, "aria-label": "Yopish"}, icon("close"))),
      h("div", {class: "ginfo"}, groupAvatar("l"), h("h3", {text: "Umumiy chat"}),
        h("p", {text: total + " a'zo, " + onlineCount() + " onlayn"})));
    const search = h("input", {type: "text", class: "gsearch", placeholder: "A'zolarni qidirish", autocomplete: "off"});
    search.value = filter;
    const list = h("div", {class: "mlist"});
    const fill = () => {
      list.textContent = "";
      const q = filter.trim().toLowerCase();
      S.members.map(m => U(m.id)).filter(u => !q || u.nickname.toLowerCase().includes(q) || u.username.toLowerCase().includes(q))
        .sort((a, b) => (isOnline(b.id) - isOnline(a.id)) || 0)
        .sort((a, b) => (isStaff(b) - isStaff(a)))
        .forEach(u => list.append(itemEl({
          av: avatar(u, "m", true), title: [nameEl(u), u.id === S.me.id ? h("span", {class: "i-time", text: "(siz)"}) : null],
          sub: (isStaff(u) ? roleLabel(u.role) + " • " : "") + statusText(u), subOn: isOnline(u.id),
          onclick: () => openProfile(u.id, openGroupInfo),
        })));
      if (!list.children.length) list.append(h("div", {class: "none", text: "Hech narsa topilmadi"}));
    };
    search.addEventListener("input", () => { filter = search.value; fill(); });
    fill();
    wrap.append(search, list);
    if (amAdmin()) wrap.append(h("div", {class: "g-clear"}, h("button", {class: "btn danger sm", type: "button", onclick: () => { closeModal(); clearGroupChat(); }}, "Chatni tozalash")));
    return wrap;
  };
  openModal(build, false, false, true);
}

/* ---------- profil ---------- */
function openProfile(uid, onBack) {
  if (!S.users.has(uid)) { loadMembers(); }
  openModal(() => profileView(uid, onBack), true, false, true);
}
function infoRow(label, value, wide) { return h("div", {class: "info-r" + (wide ? " wide" : "")}, h("small", {text: label}), h("div", {text: value})); }
function profileView(uid, onBack) {
  const u = U(uid), me = u.id === S.me.id;
  const wrap = h("div", {});
  if (u.deleted) {
    const bn = h("div", {class: "pbanner gone"});
    if (onBack) bn.append(h("button", {class: "pbtn l", type: "button", onclick: onBack, "aria-label": "Orqaga"}, icon("back")));
    bn.append(h("button", {class: "pbtn r", type: "button", onclick: closeModal, "aria-label": "Yopish"}, icon("close")));
    wrap.append(bn, h("div", {class: "pbody"}, avatar(u, "l"),
      h("div", {class: "pname"}, nameEl(u, {big: true})),
      h("div", {class: "pstat", text: "Bu akkaunt o'chirilgan"}),
      h("div", {class: "gone-note", text: "Yozgan xabarlari chatda qoladi. Unga xabar yuborib bo'lmaydi."})));
    return wrap;
  }
  const banner = tint(h("div", {class: "pbanner" + (isStaff(u) ? " prem " + u.role : "")}), u);
  if (onBack) banner.append(h("button", {class: "pbtn l", type: "button", onclick: onBack, "aria-label": "Orqaga"}, icon("back")));
  banner.append(h("button", {class: "pbtn r", type: "button", onclick: closeModal, "aria-label": "Yopish"}, icon("close")));
  const body = h("div", {class: "pbody"});
  body.append(avatar(u, "l"),
    h("div", {class: "pname"}, nameEl(u, {big: true})),
    h("div", {class: "pstat" + (isOnline(u.id) ? " on" : ""), text: statusText(u)}));
  if (isStaff(u)) body.append(tint(h("div", {class: "chip prem " + u.role}, hasEmoji(u) ? badge(u) : (u.badge === "none" ? null : icon(u.role === "owner" ? "shield" : "check", "ic vb")), roleLabel(u.role)), u));
  else if (hasEmoji(u)) body.append(h("div", {class: "chip"}, badge(u), "Maxsus nishon"));
  const info = h("div", {class: "info"});
  if (u.bio) info.append(infoRow("Bio", u.bio, true));
  info.append(infoRow("Username", "@" + u.username));
  if (u.joined) info.append(infoRow("Qo'shilgan", new Date(u.joined * 1000).getDate() + "-" + MONTHS[new Date(u.joined * 1000).getMonth()] + " " + new Date(u.joined * 1000).getFullYear()));
  body.append(info);
  const acts = h("div", {class: "acts"});
  if (me) acts.append(h("button", {class: "btn", type: "button", onclick: openSettings}, "Profilni tahrirlash"));
  else acts.append(h("button", {class: "btn", type: "button", onclick: () => { closeModal(); openChat({kind: "dm", uid: u.id}); }}, "Xabar yozish"));
  body.append(acts);
  if (!me && amAdmin() && u.role !== "owner" && (u.role !== "admin" || S.me.role === "owner")) body.append(modPanel(u));
  wrap.append(banner, body);
  return wrap;
}
function modPanel(u) {
  const cmd = text => wsSend({type: "cmd", text});
  const panel = h("div", {class: "mod"}, h("h4", {}, icon("shield"), "Moderatsiya"));
  const flags = h("div", {class: "mod-r"});
  if (u.banned) flags.append(h("span", {class: "flag", text: "Ban qilingan"}));
  if (u.muted) flags.append(h("span", {class: "flag w", text: "Mute qilingan"}));
  if (u.warns) flags.append(h("span", {class: "warnflag", text: "Ogohlantirish: " + u.warns + "/3"}));
  if (flags.children.length) panel.append(flags);
  const dur = h("select", {}, h("option", {value: "10", text: "10 daqiqa"}), h("option", {value: "60", text: "1 soat"}),
    h("option", {value: "1440", text: "1 kun"}), h("option", {value: "perm", text: "Doimiy"}));
  panel.append(h("div", {class: "mod-r"}, dur,
    h("button", {class: "btn ghost sm", type: "button", onclick: () => cmd("/mute " + u.username + " " + dur.value)}, "Mute"),
    u.muted ? h("button", {class: "btn ghost sm", type: "button", onclick: () => cmd("/unmute " + u.username)}, "Unmute") : null));
  panel.append(h("div", {class: "mod-r"},
    h("button", {class: "btn ghost sm", type: "button", onclick: async () => {
      const why = await promptDlg("Ogohlantirish", "@" + u.username + " ga ogohlantirish (3 tadan keyin 1 soat mute). Sabab:", "", {okText: "Ogohlantirish"});
      if (why !== null) cmd("/warn " + u.username + " " + why);
    }}, "Ogohlantirish"),
    u.warns ? h("button", {class: "btn ghost sm", type: "button", onclick: () => cmd("/unwarn " + u.username)}, "Olib tashlash") : null,
    h("button", {class: "btn ghost sm", type: "button", onclick: async () => {
      if (await confirmDlg("@" + u.username + " ning umumiy chatdagi oxirgi xabarlari (va fayllari) o'chiriladi.", {title: "Xabarlarini tozalash", okText: "Tozalash", danger: true})) cmd("/purge " + u.username);
    }}, "Xabarlarini tozalash"),
    h("button", {class: "btn ghost sm", type: "button", onclick: () => openBadgePicker(u)}, "Emoji nishon")));
  panel.append(h("div", {class: "mod-r"},
    u.banned
      ? h("button", {class: "btn ghost sm", type: "button", onclick: () => cmd("/unban " + u.username)}, "Bandan chiqarish")
      : h("button", {class: "btn danger sm", type: "button", onclick: async () => { if (await confirmDlg("@" + u.username + " ni ban qilasizmi?", {title: "Ban qilish", okText: "Ban qilish", danger: true})) cmd("/ban " + u.username); }}, "Ban qilish")));
  if (S.me.role === "owner") {
    panel.append(h("div", {class: "mod-r"}, u.role === "admin"
      ? h("button", {class: "btn ghost sm", type: "button", onclick: async () => { if (await confirmDlg("@" + u.username + " adminlikdan olinsinmi?", {title: "Adminlikdan olish", okText: "Olish", danger: true})) cmd("/rmadmin " + u.username); }}, "Adminlikdan olish")
      : h("button", {class: "btn ghost sm", type: "button", onclick: async () => { if (await confirmDlg("@" + u.username + " admin qilinsinmi?", {title: "Admin qilish", okText: "Admin qilish"})) cmd("/addadmin " + u.username); }}, "Admin qilish")));
  }
  const rows = panel.querySelectorAll(".mod-r");
  if (S.me.role === "owner" && rows.length >= 2) { const last = rows[rows.length - 1], prev = rows[rows.length - 2]; [...last.children].forEach(c => prev.append(c)); last.remove(); }
  panel.append(h("div", {class: "mod-r"}, h("button", {class: "btn danger sm", type: "button", onclick: async () => {
    if (await confirmDlg("@" + u.username + " akkaunti o'chiriladi va chatdan chiqarib tashlanadi. Yozgan xabarlari \"Deleted account\" nomi bilan qoladi. Buni qaytarib bo'lmaydi.",
      {title: "Akkauntni o'chirish", okText: "O'chirish", danger: true})) { cmd("/remove " + u.username); closeModal(); }
  }}, "Akkauntni o'chirish")));
  return panel;
}


/* ---------- admin paneli: IP lar, harakatlar logi, bloklar ---------- */
const fmtDT = ts => { const d = new Date(ts * 1000); return pad2(d.getDate()) + "." + pad2(d.getMonth() + 1) + "." + String(d.getFullYear()).slice(2) + " " + hhmm(ts) + ":" + pad2(d.getSeconds()); };
function admErr(box, err) { box.textContent = ""; box.append(h("div", {class: "adm-empty", text: err.message})); }

function openAdmin(initial, preset) {
  preset = preset || {};
  openModal(() => {
    const st = {tab: initial, q: preset.q || "", ip: preset.ip || "", user: preset.user || "", action: ""};
    const tabs = h("div", {class: "adm-tabs"}), body = h("div", {class: "adm-body"});
    const defs = [["ips", "IP lar"], ["log", "Harakatlar"], ["msgs", "Xabarlar"], ["blocks", "Bloklanganlar"], ["media", "Media"], ["reports", "Shikoyatlar"], ["mod", "Moderatsiya"]];
    const loaders = {ips: loadIps, log: loadLog, msgs: loadMsgs, blocks: loadBlocks, media: loadMedia, reports: loadReports, mod: loadMod};
    const paintTabs = () => {
      tabs.textContent = "";
      defs.forEach(([k, t]) => tabs.append(h("button", {type: "button", class: st.tab === k ? "on" : "", text: t, onclick: () => { st.tab = k; paintTabs(); load(); }})));
    };
    const load = () => { body.textContent = ""; loaders[st.tab](); };

    /* --- IP lar: har bir IP dan qaysi profil necha marta kirgan --- */
    function loadIps() {
      const filter = h("input", {type: "text", class: "fld", placeholder: "IP yoki @username bo'yicha qidirish", autocomplete: "off"});
      filter.value = st.q;
      const list = h("div", {});
      let timer = null;
      const fill = async () => {
        list.textContent = ""; list.append(h("div", {class: "adm-empty", text: "Yuklanmoqda…"}));
        try {
          const j = await api("/admin/ips?q=" + encodeURIComponent(st.q));
          list.textContent = "";
          if (!j.ips.length) list.append(h("div", {class: "adm-empty", text: "Hech narsa topilmadi"}));
          j.ips.forEach(e => list.append(ipCard(e, fill)));
        } catch (err) { admErr(list, err); }
      };
      filter.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { st.q = filter.value.trim(); fill(); }, 300); });
      body.append(h("div", {class: "adm-filters"}, filter), list);
      fill();
    }
    function ipCard(e, refresh) {
      const head = h("div", {class: "ipc-h"}, h("span", {class: "ip", text: e.ip}), e.blocked ? h("span", {class: "flag b", text: "Bloklangan"}) : null);
      const sum = h("div", {class: "ipc-s", text: e.profiles.length + " ta profil • " + e.logins + " kirish • " + e.sessions + " sessiya • " + e.msgs + " xabar" +
        (e.failed ? " • " + e.failed + " xato urinish" : "") + " • oxirgi: " + fmtDT(e.last_seen)});
      const card = h("div", {class: "ipc" + (e.blocked ? " blk" : "")}, head, sum);
      e.profiles.forEach(p => card.append(h("div", {class: "ipc-p"},
        h("div", {class: "who"}, h("b", {text: "@" + p.username}), p.nickname ? " (" + p.nickname + ")" : "", p.known ? "" : " — ro'yxatdan o'tmagan nom"),
        h("div", {class: "num", text: p.logins + " kirish • " + p.sessions + " sessiya • " + p.msgs + " xabar" + (p.failed ? " • " + p.failed + " xato" : "")}))));
      const acts = h("div", {class: "ipc-a"}, h("button", {class: "btn ghost sm", type: "button", text: "Loglari", onclick: () => openAdmin("log", {ip: e.ip})}));
      if (e.blocked) acts.append(h("button", {class: "btn ghost sm", type: "button", text: "Blokdan ochish", onclick: async () => {
        if (!await confirmDlg(e.ip + " blokdan ochilsinmi?", {title: "Blokdan ochish", okText: "Ochish"})) return;
        try { await api("/admin/unblock", {method: "POST", body: {ip: e.ip}}); toast("Blokdan ochildi", "ok"); refresh(); } catch (err) { toast(err.message, "error"); }
      }}));
      else acts.append(h("button", {class: "btn danger sm", type: "button", text: "Bloklash", onclick: async () => {
        const reason = await promptDlg("IP bloklash", e.ip + " bloklanadi. Sabab (ixtiyoriy):", "spam", {okText: "Bloklash"});
        if (reason === null) return;
        try { const j = await api("/admin/blocks", {method: "POST", body: {ip: e.ip, reason}}); toast("Bloklandi" + (j.kicked ? " (" + j.kicked + " ta ulanish uzildi)" : ""), "ok"); refresh(); }
        catch (err) { toast(err.message, "error"); }
      }}));
      card.append(acts);
      return card;
    }

    /* --- Harakatlar logi: filtrlar bilan --- */
    function loadLog() {
      const ipI = h("input", {type: "text", class: "fld", placeholder: "IP", autocomplete: "off"}); ipI.value = st.ip;
      const userI = h("input", {type: "text", class: "fld", placeholder: "@username", autocomplete: "off"}); userI.value = st.user;
      const sel = h("select", {}, h("option", {value: "", text: "Barcha amallar"}));
      const list = h("div", {}), more = h("button", {class: "btn ghost sm adm-more hidden", type: "button", text: "Yana yuklash"});
      let before = 0, filled = false, timer = null;
      const picked = new Set();
      const delSel = h("button", {class: "btn danger sm", type: "button", text: "Tanlanganlarni o'chirish"});
      const delAll = h("button", {class: "btn ghost sm dangerline", type: "button", text: "Filtrdagi hammasini o'chirish"});
      const updDel = () => { delSel.disabled = !picked.size; delSel.textContent = picked.size ? "Tanlanganlarni o'chirish (" + picked.size + ")" : "Tanlanganlarni o'chirish"; };
      delSel.addEventListener("click", async () => {
        if (!await confirmDlg(picked.size + " ta log yozuvi butunlay o'chiriladi.", {title: "Loglarni o'chirish", okText: "O'chirish", danger: true})) return;
        try { const j = await api("/admin/activity/delete", {method: "POST", body: {ids: [...picked]}}); toast(j.deleted + " ta yozuv o'chirildi", "ok"); picked.clear(); updDel(); page(true); }
        catch (err) { toast(err.message, "error"); }
      });
      delAll.addEventListener("click", async () => {
        const f = ipI.value.trim() || userI.value.trim() || sel.value;
        if (!await confirmDlg(f ? "Joriy filtrga mos BARCHA yozuvlar o'chiriladi." : "Harakatlar logining BUTUN tarixi o'chiriladi.", {title: "Loglarni o'chirish", okText: "Hammasini o'chirish", danger: true})) return;
        try { const j = await api("/admin/activity/delete", {method: "POST", body: {all: true, ip: ipI.value.trim(), user: userI.value.trim(), action: sel.value}}); toast(j.deleted + " ta yozuv o'chirildi", "ok"); picked.clear(); updDel(); page(true); }
        catch (err) { toast(err.message, "error"); }
      });
      const row = it => {
        const bad = ["login_failed", "blocked", "ip_block"].includes(it.action);
        const ipl = it.ip ? h("span", {class: "ipl", text: it.ip, onclick: () => { ipI.value = it.ip; page(true); }}) : null;
        const ck = h("input", {type: "checkbox", class: "ck", "aria-label": "Tanlash"});
        ck.addEventListener("change", () => { if (ck.checked) picked.add(it.id); else picked.delete(it.id); updDel(); });
        return h("div", {class: "lg sel"}, ck, h("div", {class: "t", text: fmtDT(it.ts)},),
          h("div", {class: "w"}, h("span", {class: "a" + (bad ? " bad" : ""), text: it.label}), it.username ? "@" + it.username + " " : "", ipl),
          it.detail ? h("div", {class: "d", text: it.detail}) : null);
      };
      const page = async reset => {
        if (reset) { before = 0; list.textContent = ""; picked.clear(); updDel(); }
        const qs = new URLSearchParams({ip: ipI.value.trim(), user: userI.value.trim(), action: sel.value, limit: "100"});
        if (before) qs.set("before", before);
        try {
          const j = await api("/admin/activity?" + qs.toString());
          if (!filled) { j.actions.forEach(a => sel.append(h("option", {value: a.key, text: a.label}))); filled = true; }
          j.items.forEach(it => list.append(row(it)));
          if (j.items.length) before = j.items[j.items.length - 1].id;
          more.classList.toggle("hidden", j.items.length < 100);
          if (reset && !j.items.length) list.append(h("div", {class: "adm-empty", text: "Yozuv topilmadi"}));
        } catch (err) { admErr(list, err); }
      };
      const again = () => { clearTimeout(timer); timer = setTimeout(() => page(true), 300); };
      ipI.addEventListener("input", again); userI.addEventListener("input", again); sel.addEventListener("change", () => page(true));
      more.addEventListener("click", () => page(false));
      body.append(h("div", {class: "adm-filters"}, ipI, userI, sel), h("div", {class: "adm-bar"}, delSel, delAll), list, more);
      updDel(); page(true);
    }

    /* --- Bloklangan IP lar --- */
    function loadBlocks() {
      const ipI = h("input", {type: "text", class: "fld", placeholder: "Bloklash uchun IP (masalan 203.0.113.5)", autocomplete: "off"});
      const reasonI = h("input", {type: "text", class: "fld", placeholder: "Sabab (ixtiyoriy)", autocomplete: "off"});
      const list = h("div", {});
      const fill = async () => {
        list.textContent = "";
        try {
          const j = await api("/admin/blocks");
          if (!j.blocks.length) list.append(h("div", {class: "adm-empty", text: "Bloklangan IP yo'q"}));
          j.blocks.forEach(b => list.append(h("div", {class: "ipc blk"},
            h("div", {class: "ipc-h"}, h("span", {class: "ip", text: b.ip})),
            h("div", {class: "ipc-s", text: (b.reason ? b.reason + " • " : "") + "@" + b.by + " • " + fmtDT(b.ts)}),
            h("div", {class: "ipc-a"}, h("button", {class: "btn ghost sm", type: "button", text: "Blokdan ochish", onclick: async () => {
              try { await api("/admin/unblock", {method: "POST", body: {ip: b.ip}}); toast("Blokdan ochildi", "ok"); fill(); } catch (err) { toast(err.message, "error"); }
            }}),
            h("button", {class: "btn ghost sm", type: "button", text: "Loglari", onclick: () => openAdmin("log", {ip: b.ip})})))));
        } catch (err) { admErr(list, err); }
      };
      const add = h("button", {class: "btn danger sm", type: "button", text: "Bloklash", onclick: async () => {
        if (!ipI.value.trim()) return;
        try { await api("/admin/blocks", {method: "POST", body: {ip: ipI.value.trim(), reason: reasonI.value}}); ipI.value = ""; reasonI.value = ""; toast("Bloklandi", "ok"); fill(); }
        catch (err) { toast(err.message, "error"); }
      }});
      body.append(h("div", {class: "adm-filters"}, ipI, reasonI, add), list);
      fill();
    }

    /* --- Xabarlar logi: bazada shifrlangan, serverda ochilgan (o'chirilgan/tahrirlanganlar ham) --- */
    function loadMsgs() {
      const qI = h("input", {type: "text", class: "fld", placeholder: "@username bo'yicha qidirish", autocomplete: "off"});
      const sel = h("select", {}, h("option", {value: "", text: "Barcha xabarlar"}), h("option", {value: "deleted", text: "Faqat o'chirilganlar"}), h("option", {value: "edited", text: "Faqat tahrirlanganlar"}));
      const list = h("div", {}), more = h("button", {class: "btn ghost sm adm-more hidden", type: "button", text: "Yana yuklash"});
      let next = 0, timer = null;
      const row = it => {
        const cipher = h("div", {class: "mcipher", text: it.cipher || "(shifr yo'q)"});
        const metaTxt = it.meta ? (it.meta.kind + " • epoch " + it.meta.epoch + " • shifr " + it.meta.cipher_bytes + " bayt • imzo " + it.meta.sig_bytes + " bayt")
          : (it.legacy ? "eski xabar (E2EE'dan oldin)" : "");
        const lock = h("div", {class: "mmeta", text: "🔒 " + metaTxt});
        const flags = h("span", {class: "mflags"},
          it.deleted ? h("span", {class: "flag b", text: "O'chirilgan"}) : null,
          it.edited ? h("span", {class: "flag w", text: "Tahrirlangan"}) : null,
          it.file ? h("span", {class: "flag", text: "Fayl " + fmtSize(it.file_bytes) + " (shifrlangan)"}) : null,
          it.legacy ? h("span", {class: "flag w", text: "Eski"}) : null);
        const card = h("div", {class: "lg mlg" + (it.deleted ? " gone" : "")},
          h("div", {class: "t", text: fmtDT(it.ts) + " • #" + it.id}),
          h("div", {class: "w"}, h("span", {class: "a", text: "@" + it.username}), it.nickname ? " (" + it.nickname + ") " : " ", flags),
          cipher, lock);
        it.history.forEach(hh => card.append(h("div", {class: "mhist"},
          h("b", {text: (hh.type === "edit" ? "Tahrir" : hh.type === "delete" ? "O'chirish" : hh.type) + " • " + fmtDT(hh.ts) + (hh.by ? " • @" + hh.by : "")}),
          hh.type === "edit" ? h("div", {class: "mcipher", text: hh.old + "\n→\n" + hh.new}) : h("div", {class: "mcipher", text: hh.old}))));
        return card;
      };
      const page = async reset => {
        if (reset) { next = 0; list.textContent = ""; }
        const qs = new URLSearchParams({q: qI.value.trim(), state: sel.value, limit: "50"});
        if (next) qs.set("before", next);
        try {
          const j = await api("/admin/messages?" + qs.toString());
          j.items.forEach(it => list.append(row(it)));
          next = j.next; more.classList.toggle("hidden", !next);
          if (reset && !j.items.length) list.append(h("div", {class: "adm-empty", text: "Xabar topilmadi"}));
        } catch (err) { admErr(list, err); }
      };
      qI.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => page(true), 300); });
      sel.addEventListener("change", () => page(true)); more.addEventListener("click", () => page(false));
      body.append(h("div", {class: "adm-note", text: "Uchdan-uchga shifrlash (E2EE): server ham, admin ham xabar matnini o'qiy olmaydi — bu yerda faqat shifrlangan konvertlar ko'rinadi. Matnni faqat chat a'zolarining qurilmalari ochadi. Lichka xabarlar bu yerda ko'rinmaydi."}),
        h("div", {class: "adm-filters"}, qI, sel),
        h("div", {class: "adm-bar"}, h("button", {class: "btn ghost sm dangerline", type: "button", text: "Tarixni tozalash", onclick: async () => {
          if (!await confirmDlg("O'chirilgan umumiy chat xabarlari bazadan butunlay o'chadi va tahrir/moderatsiya tarixi tozalanadi.", {title: "Xabarlar tarixini tozalash", okText: "Tozalash", danger: true})) return;
          try { const j = await api("/admin/messages/clean", {method: "POST"}); toast(j.messages + " ta xabar, " + j.history + " ta tarix tozalandi", "ok"); page(true); }
          catch (err) { toast(err.message, "error"); }
        }})), list, more);
      page(true);
    }


    /* --- Media boshqaruvi: fayl nomi/mazmuni ko'rinmaydi, faqat tur/hajm/vaqt/yuboruvchi --- */
    function loadMedia() {
      const KL = {image: "Rasm", video: "Video", audio: "Audio", other: "Fayl"};
      const kind = h("select", {}, ...[["", "Barcha turlar"], ["image", "Rasmlar"], ["video", "Videolar"], ["audio", "Audio"], ["other", "Boshqa fayllar"]].map(([v, t]) => h("option", {value: v, text: t})));
      const size = h("select", {}, ...[["0", "Har qanday hajm"], ["1", "1 MB dan katta"], ["5", "5 MB dan katta"], ["20", "20 MB dan katta"]].map(([v, t]) => h("option", {value: v, text: t})));
      const who = h("input", {type: "text", class: "fld", placeholder: "@username", autocomplete: "off"});
      const info = h("div", {class: "mm-total"}), list = h("div", {}), more = h("button", {class: "btn ghost sm adm-more hidden", type: "button", text: "Yana yuklash"});
      const del = h("button", {class: "btn danger sm", type: "button", text: "Tanlanganlarni o'chirish", disabled: true});
      const all = h("button", {class: "btn ghost sm", type: "button", text: "Ko'ringanlarni belgilash"});
      const picked = new Set(), boxes = [];
      let next = 0, timer = null;
      const upd = () => { del.disabled = !picked.size; del.textContent = picked.size ? "O'chirish (" + picked.size + ")" : "Tanlanganlarni o'chirish"; };
      const row = it => {
        const ck = h("input", {type: "checkbox", class: "ck", "aria-label": "Tanlash"});
        const r = h("div", {class: "mrow"}, ck, h("div", {}, h("span", {class: "mk", text: it.kind === "e2e" ? "🔒 Shifrlangan" : (KL[it.kind] || "Fayl")}), "@" + it.username, h("div", {class: "ms", text: fmtDT(it.ts)})), h("span", {class: "sz", text: fmtSize(it.size)}));
        ck.addEventListener("change", () => { if (ck.checked) picked.add(it.id); else picked.delete(it.id); r.classList.toggle("on", ck.checked); upd(); });
        boxes.push([ck, it.id, r]); return r;
      };
      const page = async reset => {
        if (reset) { next = 0; list.textContent = ""; picked.clear(); boxes.length = 0; upd(); }
        const qs = new URLSearchParams({kind: kind.value, sender: who.value.trim(), min_mb: size.value, limit: "50"});
        if (next) qs.set("before", next);
        try {
          const j = await api("/admin/media?" + qs.toString());
          info.textContent = "Umumiy chatdagi media: " + j.totals.count + " ta, jami " + fmtSize(j.totals.size);
          j.items.forEach(it => list.append(row(it)));
          next = j.next; more.classList.toggle("hidden", !next);
          if (reset && !j.items.length) list.append(h("div", {class: "adm-empty", text: "Media topilmadi"}));
        } catch (err) { admErr(list, err); }
      };
      all.addEventListener("click", () => { boxes.forEach(([ck, id, r]) => { ck.checked = true; picked.add(id); r.classList.add("on"); }); upd(); });
      del.addEventListener("click", async () => {
        if (!picked.size) return;
        if (!await confirmDlg(picked.size + " ta media chatdan va serverdan butunlay o'chiriladi. Izohi bor xabarlarning matni qoladi.", {title: "Media o'chirish", okText: "O'chirish", danger: true})) return;
        try { const j = await api("/admin/media/delete", {method: "POST", body: {ids: [...picked]}}); toast(j.deleted + " ta media o'chirildi", "ok"); page(true); }
        catch (err) { toast(err.message, "error"); }
      });
      const again = () => { clearTimeout(timer); timer = setTimeout(() => page(true), 300); };
      kind.addEventListener("change", () => page(true)); size.addEventListener("change", () => page(true)); who.addEventListener("input", again);
      more.addEventListener("click", () => page(false));
      body.append(h("p", {class: "mm-note", text: "Fayllar diskda shifrlangan. Bu yerda fayl nomi va mazmuni ko'rsatilmaydi (adminga ham), lichka fayllari kirmaydi. Loglarga faqat o'chirilgan SON yoziladi."}),
        info, h("div", {class: "adm-filters"}, kind, size, who), h("div", {class: "adm-bar"}, all, del), list, more);
      page(true);
    }

    /* --- Shikoyatlar --- */
    function loadReports() {
      const status = h("select", {}, h("option", {value: "open", text: "Ochiq shikoyatlar"}), h("option", {value: "closed", text: "Ko'rib chiqilganlar"}));
      const list = h("div", {}), more = h("button", {class: "btn ghost sm adm-more hidden", type: "button", text: "Yana yuklash"});
      let next = 0;
      const close = async (it, action) => {
        try { await api("/admin/reports/close", {method: "POST", body: {id: it.id, action}}); page(true); }
        catch (err) { toast(err.message, "error"); }
      };
      const card = it => {
        const c = h("div", {class: "rcard" + (it.status === "closed" ? " closed" : "")},
          h("div", {class: "rh"}, h("span", {text: fmtDT(it.ts) + " • #" + it.message_id}), h("span", {text: "@" + it.reporter + " → @" + it.target}),
            it.status === "closed" ? h("span", {class: "flag w", text: (it.action || "Yopilgan") + (it.by ? " (@" + it.by + ")" : "")}) : null),
          h("div", {class: "rt", text: it.text || (it.disclosed ? "(shikoyatchi matnni ochib bermadi)" : "(matnsiz)")}),
          it.reason ? h("div", {class: "rr", text: "Sabab: " + it.reason}) : null);
        if (it.disclosed) {                                   // E2EE: shikoyatchi bergan matn asl shifrlangan xabarga mosligini O'Z qurilmamizda tekshiramiz
          const v = h("div", {class: "rv", text: "🔒 Xabar shifrlangan; matn — shikoyatchi ixtiyoriy ochib bergani. Tekshirilmoqda…"});
          c.append(v);
          (async () => {
            try {
              const env = E2E.parseEnvelope(it.cipher), key = env.k === "g" ? X.rooms.get(env.ep) : null;
              if (!key) { v.textContent = "🔒 Tekshirib bo'lmadi: bu xabar kaliti sizda yo'q (matn tasdiqlanmagan)."; return; }
              const senderPeer = await peer(it.target_id);
              const r = await E2E.openMessage(it.cipher, {sender: it.target_id, peer: null, key, signKey: senderPeer.sign});
              const ok = r.verified && typeof r.payload.t === "string" && r.payload.t === it.text;
              v.textContent = ok ? "✅ Matn asl shifrlangan xabarga mos (imzo tasdiqlandi)." : "⚠ Ochib berilgan matn asl xabarga MOS EMAS — soxta shikoyat bo'lishi mumkin!";
              v.classList.add(ok ? "ok" : "bad");
            } catch (_) { v.textContent = "⚠ Tekshirib bo'lmadi (shifrni ochishda xato)."; v.classList.add("bad"); }
          })();
        }
        if (it.status === "open") {
          const a = h("div", {class: "ra"});
          if (it.alive) a.append(h("button", {class: "btn danger sm", type: "button", text: "Xabarni o'chirish", onclick: () => close(it, "delete")}));
          a.append(h("button", {class: "btn ghost sm", type: "button", text: "Mute 10 daq", onclick: () => { if (wsSend({type: "cmd", text: "/mute " + it.target + " 10 shikoyat"})) close(it, "done"); }}),
            h("button", {class: "btn ghost sm", type: "button", text: "Ogohlantirish", onclick: () => { if (wsSend({type: "cmd", text: "/warn " + it.target + " shikoyat"})) close(it, "done"); }}),
            h("button", {class: "btn ghost sm", type: "button", text: "Rad etish", onclick: () => close(it, "dismiss")}));
          c.append(a);
        }
        return c;
      };
      const page = async reset => {
        if (reset) { next = 0; list.textContent = ""; }
        const qs = new URLSearchParams({status: status.value, limit: "30"}); if (next) qs.set("before", next);
        try {
          const j = await api("/admin/reports?" + qs.toString());
          j.items.forEach(it => list.append(card(it)));
          next = j.next; more.classList.toggle("hidden", !next);
          if (reset && !j.items.length) list.append(h("div", {class: "adm-empty", text: status.value === "open" ? "Ochiq shikoyat yo'q 🎉" : "Hech narsa yo'q"}));
        } catch (err) { admErr(list, err); }
      };
      status.addEventListener("change", () => page(true)); more.addEventListener("click", () => page(false));
      body.append(h("div", {class: "adm-filters"}, status), list, more); page(true);
    }

    /* --- Moderatsiya sozlamalari: sekin rejim, qulf, taqiqlangan so'zlar --- */
    async function loadMod() {
      let cfg;
      try { cfg = await api("/admin/modsettings"); } catch (err) { admErr(body, err); return; }
      const save = async patch => {
        try { cfg = await api("/admin/modsettings", {method: "POST", body: patch}); toast("Saqlandi", "ok"); paintWords(); }
        catch (err) { toast(err.message, "error"); }
      };
      const slow = h("select", {}, ...[[0, "O'chiq"], [5, "5 soniya"], [10, "10 soniya"], [30, "30 soniya"], [60, "1 daqiqa"], [300, "5 daqiqa"]].map(([v, t]) => h("option", {value: String(v), text: t})));
      if (![0, 5, 10, 30, 60, 300].includes(cfg.slowmode)) slow.append(h("option", {value: String(cfg.slowmode), text: cfg.slowmode + " soniya"}));
      slow.value = String(cfg.slowmode);
      const lock = h("input", {type: "checkbox"}); lock.checked = cfg.locked;
      lock.addEventListener("change", () => save({locked: lock.checked}));
      const wIn = h("input", {type: "text", class: "fld", placeholder: "So'z qo'shish (so'z* — prefiks bo'yicha)", maxlength: "32", autocomplete: "off"});
      const wl = h("div", {class: "wl"});
      const e2eSection = () => {
        const box = h("div", {class: "msec"}, h("h4", {text: "🔐 Uchdan-uchga shifrlash (E2EE)"}));
        const info = h("p", {text: "Yuklanmoqda…"}); box.append(info);
        api("/admin/e2ee").then(st => {
          info.textContent = "Guruh kaliti avlodi: " + st.epoch + " • kalitli foydalanuvchilar: " + st.keyed_users + " • server o'qiy oladigan eski xabarlar: " + st.legacy_messages +
            ". Ban qilinganda kalit avtomatik yangilanadi, qo'lda ham yangilash mumkin.";
          box.append(h("div", {class: "ep-row"}, h("button", {class: "btn sm", type: "button", text: "Guruh kalitini yangilash", onclick: async () => {
            if (!X.rooms.has(X.epoch)) { toast("Sizda joriy guruh kaliti yo'q", "error"); return; }
            await rotateRoom("manual"); load();
          }})));
          if (S.me.role === "owner" && st.legacy_messages) box.append(h("div", {class: "ep-row"}, h("button", {class: "btn danger sm", type: "button", text: "Eski xabarlarni o'chirish (" + st.legacy_messages + ")", onclick: async () => {
            if (!await confirmDlg("Server o'qiy oladigan barcha eski xabarlar va ularning fayllari butunlay o'chadi. Qaytarib bo'lmaydi. Yangi (E2EE) xabarlarga tegilmaydi.", {title: "Eski xabarlarni o'chirish", okText: "O'chirish", danger: true})) return;
            try { const j = await api("/admin/e2ee/purge-legacy", {method: "POST"}); toast(j.deleted + " ta eski xabar o'chirildi", "ok"); load(); } catch (err) { toast(err.message, "error"); }
          }})));
        }).catch(err => { info.textContent = err.message; });
        return box;
      };
      const paintWords = () => {
        wl.textContent = "";
        if (!cfg.words.length) wl.append(h("div", {class: "adm-empty", text: "Taqiqlangan so'z yo'q"}));
        cfg.words.forEach(w => wl.append(h("span", {}, w, h("button", {type: "button", "aria-label": "Olib tashlash", text: "×", onclick: () => save({words: cfg.words.filter(x => x !== w)})}))));
      };
      const addWord = () => { const v = wIn.value.trim(); if (!v) return; wIn.value = ""; save({words: [...cfg.words, v]}); };
      wIn.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); addWord(); } });
      body.append(
        h("div", {class: "msec"}, h("h4", {text: "🐢 Sekin rejim"}), h("p", {text: "Oddiy foydalanuvchilar umumiy chatga shuncha vaqtda bir marta yoza oladi. Adminlarga va lichkaga qo'llanmaydi."}),
          h("div", {class: "ep-row"}, slow, h("button", {class: "btn sm", type: "button", text: "Saqlash", onclick: () => save({slowmode: Number(slow.value)})}))),
        h("div", {class: "msec"}, h("h4", {text: "🔒 Chatni qulflash"}), h("p", {text: "Qulflanganda umumiy chatga faqat adminlar yoza oladi (lichka ishlayveradi)."}),
          h("label", {class: "tgl"}, h("span", {text: "Umumiy chat qulflangan"}), lock)),
        h("div", {class: "msec"}, h("h4", {text: "🚫 Taqiqlangan so'zlar"}), h("p", {text: "E2EE yoqilgan: server xabar matnini ko'ra olmaydi, shuning uchun taqiqlangan so'zlar filtri faqat eski (E2EE'dan oldingi) rejimda ishlaydi. Yangi xabarlar filtrlanmaydi — moderatsiya shikoyatlar, mute/ban va tezlik cheklovlari orqali."}),
          h("div", {class: "ep-row"}, wIn, h("button", {class: "btn sm", type: "button", text: "Qo'shish", onclick: addWord})), wl),
        e2eSection(),
        h("div", {class: "msec"}, h("h4", {text: "🛡️ Avtomatik himoya"}), h("p", {text: "3 ta ogohlantirishdan keyin foydalanuvchi 1 soatga mute qilinadi. Spam (1 daqiqada 3 marta tezlik limitiga urilish) — 5 daqiqa avtomatik mute. Foydalanuvchi profilidagi Moderatsiya panelidan: ogohlantirish, xabarlarini tozalash, mute/ban."})));
      paintWords();
    }

    paintTabs(); load();
    return h("div", {}, sheetHead("Admin: loglar, media va moderatsiya"), tabs, body);
  }, false, true);
}

/* ---------- emoji nishon: tanlash (o'zimga yoki foydalanuvchiga) ---------- */
const BADGE_EMOJIS = "👑 ✅ ⭐ 🌟 💎 🔥 ⚡ 🚀 🛡️ 🏆 🎖️ 💜 ❤️ 💙 💚 🧡 😎 🤩 😈 👻 🦄 🐉 🦁 🐺 🦅 🌈 🌙 ☀️ ❄️ 🍀 🎯 🎨 🎧 🎮 💫 ✨ 🔱 ⚜️ 🧿 🪐 🍒 🍉 👾 🤖 🥇 📢 🎉 🌹 🦋 🐱 🐼 🍕".split(" ");
const BADGE_ANIMS = [["", "Yo'q"], ["pulse", "Puls"], ["bounce", "Sakrash"], ["spin", "Aylanish"], ["shake", "Silkinish"], ["float", "Suzish"], ["glow", "Nur"], ["flip", "Aylanma"], ["wave", "Silkitish"], ["rainbow", "Kamalak"]];
function badgeEditor(t, onSaved) {
  const cur = {badge: t.badge || "", anim: t.badge_anim || ""};
  const prev = h("div", {class: "ep-prev"}), grid = h("div", {class: "ep-grid"}), anims = h("div", {class: "ep-anims"});
  const custom = h("input", {type: "text", class: "fld", maxlength: "16", placeholder: "Yoki o'z emojingizni kiriting", autocomplete: "off"});
  const paint = () => {
    prev.textContent = "";
    const b = badge(Object.assign({}, t, {badge: cur.badge, badge_anim: cur.anim}), true);
    prev.append(nameEl(Object.assign({}, t, {badge: cur.badge, badge_anim: cur.anim}), {big: true}));
    if (!b) prev.append(h("small", {text: "  (nishon yo'q)"}));
    grid.querySelectorAll("button").forEach(x => x.classList.toggle("on", x.textContent === cur.badge));
    anims.querySelectorAll("button").forEach(x => x.classList.toggle("on", x.dataset.a === cur.anim));
  };
  BADGE_EMOJIS.forEach(e => grid.append(h("button", {type: "button", text: e, "aria-label": e, onclick: () => { cur.badge = e; custom.value = ""; paint(); }})));
  BADGE_ANIMS.forEach(([k, n]) => { const b = h("button", {type: "button", text: n}); b.dataset.a = k; b.addEventListener("click", () => { cur.anim = k; paint(); }); anims.append(b); });
  custom.addEventListener("input", () => { const v = custom.value.trim(); if (v) { cur.badge = v; paint(); } });
  const save = async () => {
    try {
      let u;
      if (t.id === S.me.id) u = (await api("/profile", {method: "PATCH", body: {badge: cur.badge, badge_anim: cur.anim}})).me;
      else u = (await api("/admin/badge", {method: "POST", body: {user_id: t.id, badge: cur.badge, anim: cur.anim}})).user;
      upsertUser(u); renderList(); renderHeader(); renderMessages(false);
      toast("Nishon saqlandi", "ok"); if (onSaved) onSaved(u);
    } catch (err) { toast(err.message, "error"); }
  };
  const row = h("div", {class: "ep-row"},
    h("button", {class: "btn", type: "button", text: "Saqlash", onclick: save}),
    h("button", {class: "btn ghost", type: "button", text: isStaff(t) ? "Galochka (standart)" : "Olib tashlash", onclick: () => { cur.badge = ""; cur.anim = ""; custom.value = ""; paint(); }}),
    isStaff(t) ? h("button", {class: "btn ghost", type: "button", text: "Yashirish", onclick: () => { cur.badge = "none"; cur.anim = ""; custom.value = ""; paint(); }}) : null);
  paint();
  return h("div", {}, prev, grid, h("div", {class: "ep-row"}, custom), anims, row);
}
function badgeSection() { return h("div", {class: "setsec"}, h("h4", {text: "Profil nishoni (emoji va animatsiya)"}), badgeEditor(S.me)); }
function openBadgePicker(u) {
  openModal(() => h("div", {}, sheetHead("Emoji nishon: @" + u.username, () => openProfile(u.id)), h("div", {class: "sh-body"}, badgeEditor(U(u.id), () => openProfile(u.id)))), false);
}

/* ---------- sozlamalar (o'z profilim) ---------- */
/* ---------------- Shifrlash inspektori: xabar qanday shifrlanadi va server nimani ko'radi ---------------- */
function openInspector(tab) {
  openModal(() => {
    const st = {tab: tab || "flow"};
    const tabs = h("div", {class: "adm-tabs"}), body = h("div", {class: "adm-body enc"});
    const defs = [["flow", "Xabar yo'li"], ["server", "Server ko'radi"], ["keys", "Kalitlar"], ["limits", "Halol chegaralar"]];
    const paint = () => { tabs.textContent = ""; defs.forEach(([k, t]) => tabs.append(h("button", {type: "button", class: st.tab === k ? "on" : "", text: t, onclick: () => { st.tab = k; paint(); load(); }}))); };
    const load = () => { body.textContent = ""; ({flow: encFlow, server: encServer, keys: encKeys, limits: encLimits})[st.tab](body); };
    paint(); load();
    return h("div", {}, sheetHead("🔒 Shifrlash: nima sodir bo'layapti?"), tabs, body);
  }, false, true);
}
const mono = (t, cls) => h("div", {class: "enc-mono" + (cls ? " " + cls : ""), text: t});
const step = (n, title, ...kids) => h("div", {class: "enc-step"}, h("div", {class: "enc-n", text: String(n)}), h("div", {class: "enc-b"}, h("b", {text: title}), ...kids));
const shortId = s => s && s.length > 28 ? s.slice(0, 22) + "…" + s.slice(-6) : (s || "");

function encFlow(body) {
  const out = h("div", {});
  const inp2 = h("textarea", {class: "fld", rows: "2", maxlength: "200"}); inp2.value = "Salom! Bu sinov matni 🙂";
  const go = h("button", {class: "btn", type: "button", text: "Shifrlab ko'rish (yuborilmaydi)"});
  go.onclick = async () => {
    out.textContent = "";
    try {
      if (!S.active) throw new Error("Avval biror suhbatni oching (guruh yoki lichka) — kalit shu suhbatniki");
      const ctx = await keyForActive(), text = inp2.value.slice(0, 200);
      const env = await sealFor(ctx, {t: text}), t = E2E.trace[E2E.trace.length - 1];
      const dm = S.active.kind === "dm", p = dm ? await peer(S.active.uid) : null;
      const pkt = JSON.stringify(Object.assign({type: "send", e2e: env}, dm ? {to: S.active.uid} : {}));
      out.append(
        step(1, "Sizning matningiz (faqat qurilmangizda)", mono(t.plain), h("small", {text: "Uzunlik yashirilishi uchun " + t.plainBytes + " baytgacha to'ldiriladi."})),
        step(2, dm ? "Kalit: ikkingiz orasidagi ECDH kaliti" : "Kalit: guruh kaliti (avlod " + ctx.ep + ")",
          mono(dm ? "Sizning xavfsizlik raqamingiz: " + X.fp + "\n" + U(S.active.uid).nickname + ": " + p.fp : "Kalit ID: " + (X.keyIds.get(ctx.ep) || "?") + "  (kalitning o'zi emas, faqat belgisi)"),
          h("small", {text: dm ? "Bu kalit faqat sizning va suhbatdoshingizning maxfiy kalitlaridan hosil bo'ladi; server ikkalasini ham bilmaydi." : "Guruh kaliti serverda yo'q: har bir a'zo uchun uning ommaviy kaliti bilan o'ralgan nusxasi bor."})),
        step(3, "AES-256-GCM bilan shifrlash", mono("IV (tasodifiy): " + t.iv + "\nShifr: " + t.ctBytes + " bayt (shu jumladan 16 baytlik tekshiruv tegi)")),
        step(4, "ECDSA imzosi (yuboruvchi — siz)", mono(t.sigBytes + " bayt. Hech kim sizning nomingizdan soxta xabar yarata olmaydi.")),
        step(5, "Serverga ketadigan paket (ilova darajasida)", mono(shortId(pkt) === pkt ? pkt : pkt.slice(0, 90) + " … " + pkt.slice(-40), "net"),
          h("small", {text: "Mana shu — serverga boradigan hamma narsa: matn yo'q, faqat shifr. To'liq konvert:"}), mono(env, "net long")));
    } catch (err) { out.append(h("div", {class: "adm-empty", text: err.message})); }
  };
  const wire = h("div", {});
  const paintWire = () => {
    wire.textContent = "";
    const fr = SC.wire.slice(-4).reverse();
    if (!fr.length) wire.append(h("div", {class: "adm-empty", text: "Hozircha kadr yo'q"}));
    fr.forEach(f => wire.append(h("div", {class: "enc-frame"},
      h("b", {text: (f.dir === "→" ? "Siz → server" : "server → siz") + " • " + new Date(f.ts).toLocaleTimeString() + " • " + f.bytes + " belgi"}),
      h("small", {text: "Server (kanal ochilgach) ko'radigan ilova JSON'i:"}), mono(f.app, "net"),
      h("small", {text: "Tarmoqda (Chrome Network, Wireshark) ko'rinadigani:"}), mono(f.net + "…", "net"))));
  };
  paintWire();
  body.append(
    h("p", {class: "adm-note", text: "Xabaringiz brauzeringizda shifrlanadi va faqat shifr serverga boradi. Sinab ko'ring: matn kiriting — pastda shifrlash qadamlari haqiqiy kalitingiz bilan ko'rsatiladi (xabar yuborilmaydi)."}),
    inp2, go, out,
    h("h4", {class: "enc-h", text: "Tarmoqdagi oxirgi haqiqiy kadrlar"}),
    h("p", {class: "adm-note", text: "Ikki qatlam: tashqi — brauzer↔server kanali (Wireshark shuni ko'radi); ichki — xabar konverti, uni faqat suhbat a'zolari ocha oladi. Server kanalni ochadi, lekin konvertni ocha olmaydi."}),
    h("button", {class: "btn ghost sm", type: "button", text: "Yangilash", onclick: paintWire}), wire);
}

async function encServer(body) {
  body.append(h("div", {class: "adm-empty", text: "Serverdan so'ralmoqda…"}));
  let j;
  try { j = await api("/e2ee/server-view" + (S.active && S.active.kind === "dm" ? "?to=" + S.active.uid : "")); }
  catch (err) { body.textContent = ""; admErr(body, err); return; }
  body.textContent = "";
  const scope = j.scope === "group" ? "Umumiy chat" : "Lichka: " + (S.active ? U(S.active.uid).nickname : "");
  body.append(h("p", {class: "adm-note", text: scope + " — serverning o'z bazasidagi so'nggi qatorlar (server aynan shuni qaytardi). Chap tomonda — qurilmangizda ochilgan matn, o'ngda — server va admin ko'radigani."}));
  const mine = new Map(currentMsgs().map(m => [m.id, m]));
  if (!j.rows.length) body.append(h("div", {class: "adm-empty", text: "Bu suhbatda hali xabar yo'q"}));
  j.rows.forEach(r => {
    const local = mine.get(r.id);
    const you = local ? (local.locked ? "🔒 (kalit kutilmoqda)" : local.bad ? "⚠ (ochib bo'lmadi)" : (local.content || (local.image ? "📷 rasm" : local.file ? (local.file.voice ? "🎤 ovozli xabar" : "📎 " + local.file.name) : ""))) : "(bu xabar yuklanmagan)";
    body.append(h("div", {class: "enc-row"},
      h("div", {class: "enc-rh"}, h("b", {text: "#" + r.id + " • @" + r.from}), h("span", {text: " • " + fmtDT(r.ts) + " • " + r.stored_bytes + " bayt" + (r.blob_bytes ? " • fayl " + fmtSize(r.blob_bytes) + " (shifrlangan)" : "") + (r.deleted ? " • o'chirilgan" : "") + (r.edited ? " • tahrirlangan" : "")}),
        r.e2e ? null : h("span", {class: "flag b", text: "ESKI: server o'qiy oladi"})),
      h("div", {class: "enc-cols"},
        h("div", {}, h("small", {text: "SIZ KO'RASIZ (qurilmada ochilgan)"}), h("div", {class: "enc-you", text: you})),
        h("div", {}, h("small", {text: "SERVER BAZASIDA"}), mono(r.stored, "net")),
        h("div", {}, h("small", {text: "ADMIN LOGIDA"}), mono(r.admin_sees, "net")))));
  });
  const li = arr => h("ul", {class: "enc-ul"}, ...arr.map(t => h("li", {text: t})));
  body.append(
    h("h4", {class: "enc-h", text: "Server biladi"}), li(j.knows.biladi),
    h("h4", {class: "enc-h", text: "Server bilmaydi"}), li(j.knows.bilmaydi),
    h("h4", {class: "enc-h", text: "Sizning yozuvingiz serverda"}),
    mono("Ommaviy kalit (ECDH): " + shortId(j.me.ecdh_pub) + "\nOmmaviy kalit (imzo): " + shortId(j.me.sign_pub) + "\nMaxfiy kalitlar zaxirasi: " + j.me.key_blob_bytes + " bayt, parolingiz kalitida shifrlangan — serverda ochib bo'lmaydi" +
      "\nGuruh kaliti (sizga o'ralgan nusxa): " + (j.room.my_wrap ? "avlod " + j.room.my_wrap.epoch + ", o'ragan: @" + (U(j.room.my_wrap.by).username || j.room.my_wrap.by) : "hali yo'q"), "net"),
    h("h4", {class: "enc-h", text: "Harakatlaringiz logi (adminga ko'rinadigan)"}),
    ...(j.activity.length ? j.activity.map(a => h("div", {class: "enc-act", text: fmtDT(a.ts) + " • " + a.ip + " • " + a.action + (a.detail ? " • " + a.detail : "")})) : [h("div", {class: "adm-empty", text: "Yozuv yo'q"})]),
    j.legacy_messages ? h("p", {class: "adm-note warn", text: "⚠ Bazada hali " + j.legacy_messages + " ta ESKI (E2EE'dan oldingi) xabar bor — ularni server o'qiy oladi. Ega ularni Moderatsiya bo'limidan o'chira oladi."}) : h("p", {class: "adm-note ok", text: "✅ Bazada server o'qiy oladigan xabar yo'q."}));
}

async function encKeys(body) {
  const cur = X.epoch;
  body.append(
    h("p", {class: "adm-note", text: "Barmoq izi — kalitingizning qisqa belgisi. Suhbatdoshingiz bilan uni boshqa kanalda (yuzma-yuz, telefon) solishtiring: mos kelsa, o'rtada hech kim yo'q."}),
    h("h4", {class: "enc-h", text: "Sizning barmoq izingiz"}), mono(X.fp || "—", "fp"),
    h("button", {class: "btn ghost sm", type: "button", text: "Nusxalash", onclick: () => copyText(X.fp)}),
    h("h4", {class: "enc-h", text: "Guruh kaliti"}),
    mono("Joriy avlod: " + (cur || "yo'q") + (X.rooms.has(cur) ? " • sizda bor • kalit ID: " + X.keyIds.get(cur) : " • sizda hali yo'q") + "\nSizda bor avlodlar: " + ([...X.rooms.keys()].join(", ") || "—")));
  const changed = [...X.changed.entries()];
  if (changed.length) {
    body.append(h("p", {class: "adm-note warn", text: "⚠ Quyidagi foydalanuvchilarning kaliti ilgari ko'rganingizdan FARQ QILADI. Bu server almashtirgan kalit bo'lishi mumkin. Barmoq izini tekshirmaguncha ularga yozmang."}));
    changed.forEach(([uid, c]) => body.append(h("div", {class: "enc-row"}, h("b", {text: "@" + U(uid).username}), mono("Avval: " + c.old + "\nHozir: " + c.now),
      h("button", {class: "btn danger sm", type: "button", text: "Yangi kalitni qabul qilish", onclick: () => { acceptKeyChange(uid); toast("Qabul qilindi", "ok"); renderHeader(); body.textContent = ""; encKeys(body); }}))));
  }
  body.append(h("h4", {class: "enc-h", text: "A'zolar barmoq izlari"}));
  const list = h("div", {}); body.append(list);
  const members = S.members.filter(m => m.ek && m.id !== S.me.id).slice(0, 80);
  for (const m of members) {
    try {
      const p = await peer(m.id);
      list.append(h("div", {class: "enc-mem"}, h("b", {text: m.nickname + " @" + m.username}), mono(p.fp + (p.changed ? "   ⚠ O'ZGARGAN" : ""), p.changed ? "bad" : "fp")));
    } catch (_) {}
  }
  if (!members.length) list.append(h("div", {class: "adm-empty", text: "Boshqa a'zo yo'q"}));
}

function encLimits(body) {
  const li = arr => h("ul", {class: "enc-ul"}, ...arr.map(t => h("li", {text: t})));
  body.append(
    h("p", {class: "adm-note", text: "Haqiqiy E2EE nimani kafolatlaydi va nimani kafolatlamaydi — halol ro'yxat:"}),
    h("h4", {class: "enc-h", text: "✅ Kafolat"}),
    li(["Server, hosting egasi va admin xabar matnini, fayl mazmunini va nomini o'qiy olmaydi: ular faqat shifrni ko'radi.",
        "Parolingiz serverga umuman bormaydi — faqat undan olingan qaytarib bo'lmaydigan kirish kaliti boradi. Maxfiy kalitlaringiz parol kalitida shifrlangan.",
        "Har bir xabar imzolangan: server yoki boshqa a'zo sizning nomingizdan soxta xabar yarata olmaydi.",
        "Ban qilingan a'zodan keyin guruh kaliti yangilanadi: u yangi xabarlarni o'qiy olmaydi."]),
    h("h4", {class: "enc-h", text: "⚠ Cheklovlar"}),
    li(["Guruhga qo'shilgan har kim (admin ham, agar a'zo bo'lsa) o'z qurilmasida xabarlarni ko'radi — bu ochiq guruh: ro'yxatdan o'tgan har kim kalit oladi.",
        "Server yashirincha SOXTA a'zo qo'shib, unga kalit o'ratishi mumkin. Himoya: «Kalitlar» bo'limida barmoq izlarini tekshiring; ilgari ko'rilgan kalit o'zgarsa, ogohlantirish chiqadi.",
        "Bu sahifaning kodini ham server beradi. Zararli server kodni almashtirishi mumkin: SRI faqat tashqi o'zgarishdan himoya qiladi. To'liq ishonch uchun kodni tekshiring yoki serverni o'zingiz yuriting.",
        "Metama'lumotlar ko'rinadi: kim, qachon, kimga (lichkada), xabar hajmi, IP. Profil (nickname, bio, rasm) ochiq.",
        "Parolni yo'qotsangiz, eski xabarlarni tiklab bo'lmaydi (kalit zaxirasi faqat parol bilan ochiladi).",
        "Lichkada «oldinga maxfiylik» yo'q (kalit doimiy). Shikoyat yuborganingizda faqat o'sha bitta xabar ixtiyoriy ochib beriladi.",
        "Taqiqlangan so'zlar filtri ishlamaydi: server matnni ko'rmaydi."]));
}
$("encBtn").addEventListener("click", () => openInspector("flow"));

function openSettings() {
  openModal(() => {
    const me = S.me;
    const gal = h("div", {class: "gal"});
    const nick = h("input", {type: "text", class: "fld", maxlength: "24"}); nick.value = me.nickname;
    const bio = h("textarea", {class: "fld", rows: "3", maxlength: "140", placeholder: "O'zingiz haqingizda…"}); bio.value = me.bio || "";
    const old = h("input", {type: "password", class: "fld", autocomplete: "current-password", maxlength: "128"});
    const nw = h("input", {type: "password", class: "fld", autocomplete: "new-password", maxlength: "128"});

    const loadGallery = async () => {
      try {
        const j = await api("/avatars");
        gal.textContent = "";
        j.avatars.forEach(a => {
          const del = h("button", {type: "button", title: "O'chirish", "aria-label": "O'chirish"}, icon("close"));
          del.addEventListener("click", async e => { e.stopPropagation(); try { await api("/avatars/" + a.id, {method: "DELETE"}); loadGallery(); } catch (err) { toast(err.message, "error"); } });
          const g = h("div", {class: "gi" + (a.active ? " act" : ""), title: a.active ? "Faol rasm" : "Faollashtirish"}, h("img", {src: a.url, alt: ""}), del);
          g.addEventListener("click", async () => { if (a.active) return; try { await api("/avatars/" + a.id + "/use", {method: "POST"}); loadGallery(); } catch (err) { toast(err.message, "error"); } });
          gal.append(g);
        });
        if (j.avatars.length < j.max) gal.append(h("button", {class: "btn ghost sm", type: "button", onclick: () => $("file").click()}, icon("camera", "ic vb"), " Rasm qo'shish"));
        if (j.avatars.some(a => a.active)) gal.append(h("button", {class: "btn ghost sm", type: "button", onclick: async () => { try { await api("/avatar/clear", {method: "POST"}); loadGallery(); } catch (err) { toast(err.message, "error"); } }}, "Rasmni olib tashlash"));
      } catch (_) {}
    };
    S.reloadGallery = loadGallery;
    loadGallery();

    const saveProfile = async () => {
      try { await api("/profile", {method: "PATCH", body: {nickname: nick.value, bio: bio.value}}); toast("Profil saqlandi", "ok"); }
      catch (err) { toast(err.message, "error"); }
    };
    const savePass = async () => {
      try {                                                    // maxfiy kalitlar yangi parol bilan brauzerda QAYTA O'RALADI
        if (!old.value) throw new Error("Eski parolni kiriting");
        if (nw.value.length < 6) throw new Error("Yangi parol kamida 6 belgi bo'lishi kerak");
        const info = await api("/me"), e = info.e2ee, un = S.me.username;
        const ko = await E2E.deriveFromPassword(un, old.value, e.kdf_iter || E2E.KDF_DEFAULT);
        let ident; try { ident = await E2E.unwrapIdentity(e.key_blob, ko.kek, un); } catch (_) { throw new Error("Eski parol noto'g'ri"); }
        const kn = await E2E.deriveFromPassword(un, nw.value, E2E.KDF_DEFAULT);
        await api("/password", {method: "POST", body: {old: ko.auth, new: kn.auth, key_blob: await E2E.wrapIdentity(ident, kn.kek, un), kdf_iter: E2E.KDF_DEFAULT}});
        old.value = ""; nw.value = ""; toast("Parol almashtirildi, kalitlar qayta o'raldi (boshqa qurilmalardan chiqarildingiz)", "ok");
      } catch (err) { toast(err.message, "error"); }
    };
    const dark = document.documentElement.dataset.theme === "dark";
    return h("div", {},
      sheetHead("Profilni tahrirlash"),
      h("div", {class: "sh-body"},
        gal,
        isStaff(me) ? colorSection() : null,
        isStaff(me) ? badgeSection() : null,
        h("div", {class: "setsec"},
          h("label", {class: "fl"}, "Nickname", nick),
          h("label", {class: "fl"}, "Bio", bio),
          h("button", {class: "btn", type: "button", onclick: saveProfile}, "Saqlash")),
        h("div", {class: "setsec"}, h("h4", {text: "Parolni almashtirish"}),
          h("label", {class: "fl"}, "Eski parol", old),
          h("label", {class: "fl"}, "Yangi parol (kamida 6 belgi)", nw),
          h("button", {class: "btn ghost", type: "button", onclick: savePass}, "Parolni almashtirish")),
        h("div", {class: "setsec row-b"},
          h("button", {class: "btn ghost", type: "button", onclick: () => { toggleTheme(); closeModal(); }}, dark ? "Kunduzgi mavzu" : "Tungi mavzu"),
          h("button", {class: "btn danger", type: "button", onclick: () => { closeModal(); logout(); }}, "Chiqish")),
        me.role === "owner" ? null : h("div", {class: "setsec"}, h("h4", {text: "Xavfli hudud"}),
          h("button", {class: "btn ghost dangerline", type: "button", onclick: deleteMyAccount}, "Akkauntni o'chirish"))));
  }, false);
}
async function deleteMyAccount() {
  const ok = await confirmDlg("Akkauntingiz butunlay o'chiriladi: profil, rasmlar va parol yo'qoladi. Yozgan xabarlaringiz chatda \"Deleted account\" nomi bilan qoladi. Buni qaytarib bo'lmaydi.",
    {title: "Akkauntni o'chirish", okText: "Davom etish", danger: true});
  if (!ok) return;
  const pw = await promptDlg("Parolni tasdiqlang", "Akkauntni o'chirish uchun parolingizni kiriting:", "", {type: "password", okText: "O'chirish", danger: true});
  if (pw === null) return;
  try {
    const e = (await api("/me")).e2ee, kd = await E2E.deriveFromPassword(S.me.username, pw, e.kdf_iter || E2E.KDF_DEFAULT);
    await api("/account/delete", {method: "POST", body: {password: kd.auth}}); showAuth("Akkauntingiz o'chirildi");
  }
  catch (err) { toast(err.message, "error"); }
}
const PRESETS = ["#f7b733", "#7b61ff", "#ef4444", "#f97316", "#22c55e", "#14b8a6", "#3b82f6", "#ec4899"];
function colorSection() {
  const sec = h("div", {class: "setsec"}, h("h4", {text: "Profil rangi"}));
  const preview = h("div", {class: "pname", style: null}), sw = h("div", {class: "swatches"});
  preview.style.fontSize = "17px"; preview.style.margin = "0 0 10px";
  const save = async c => {
    try {
      const j = await api("/profile", {method: "PATCH", body: {color: c}});
      upsertUser(j.me); paint(); renderList(); renderHeader(); renderMessages(false);
      toast(c ? "Rang saqlandi" : "Standart rang tiklandi", "ok");
    } catch (err) { toast(err.message, "error"); }
  };
  const paint = () => {
    preview.textContent = ""; preview.append(nameEl(S.me, {big: true}));
    sw.textContent = "";
    const cur = (S.me.color || "").toLowerCase();
    PRESETS.forEach(c => {
      const b = h("button", {type: "button", class: "sw" + (cur === c ? " on" : ""), title: c, "aria-label": c});
      b.style.background = c; b.addEventListener("click", () => save(c)); sw.append(b);
    });
    const pick = h("input", {type: "color"}); pick.value = HEX.test(cur) ? cur : TONES[S.me.role];
    pick.addEventListener("change", () => save(pick.value));
    sw.append(h("label", {class: "sw-custom", title: "Boshqa rang tanlash"}, pick),
      h("button", {type: "button", class: "btn ghost sm", text: "Standart", onclick: () => save("")}));
  };
  paint(); sec.append(preview, sw);
  return sec;
}
$("file").addEventListener("change", async () => {
  const f = $("file").files[0]; $("file").value = ""; if (!f) return;
  if (f.size > 2 * 1024 * 1024) { toast("Rasm 2 MB dan oshmasligi kerak", "error"); return; }
  const fd = new FormData(); fd.append("file", f);
  try { await api("/avatar", {method: "POST", body: fd}); toast("Profil rasmi yangilandi", "ok"); if (S.reloadGallery) S.reloadGallery(); }
  catch (err) { toast(err.message, "error"); }
});

/* ---------------- ishga tushirish ---------------- */
function openApp() {
  resetState();
  $("auth").classList.add("hidden"); $("app").classList.remove("hidden");
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x.dataset.tab === "chats"));
  $("chat").classList.add("hidden"); $("empty").classList.remove("hidden");
  S.wantClose = false;
  X.ready = (async () => { await loadMembers(); try { await loadRoom(); } catch (_) {} })();
  connect();
}
(async () => {
  const t = localStorage.getItem(LS_TOKEN); if (!t) return;
  try {
    const r = await SC.fetch("/api/me", {headers: {Authorization: "Bearer " + t}});
    if (!r.ok) throw 0;
    const j = await r.json();
    S.token = t; xReset();
    if (!(await xRestore({upgrade: j.upgrade, e2ee: j.e2ee}, j.me))) { showAuth(""); return; }
    openApp(); S.me = j.me; upsertUser(j.me);
  } catch (_) { localStorage.removeItem(LS_TOKEN); }
})();
})();


/* ---------------- Uzun nickname: "…" bilan qisqaradi, ustiga borilganda sekin siljiydi ---------------- */
(function () {
  let cur = null, raf = 0, timer = 0;
  const HOST = ".item, .pname, .hinfo, .bname, .rq";
  function stop() {
    cancelAnimationFrame(raf); clearTimeout(timer);
    if (cur) { cur.scrollLeft = 0; cur.style.textOverflow = ""; cur.classList.remove("scrolling"); }
    cur = null;
  }
  function start(nt) {
    const max = nt.scrollWidth - nt.clientWidth;
    if (max <= 2) return;
    cur = nt; nt.style.textOverflow = "clip"; nt.classList.add("scrolling");
    const SPEED = 45;                       // px/soniya
    const run = (dir, from) => {
      const t0 = performance.now();
      const step = now => {
        if (cur !== nt) return;
        const d = Math.min(1, (now - t0) / ((max / SPEED) * 1000));
        nt.scrollLeft = dir > 0 ? max * d : max * (1 - d);
        if (d < 1) raf = requestAnimationFrame(step);
        else timer = setTimeout(() => { if (cur === nt) run(-dir); }, 700);
      };
      raf = requestAnimationFrame(step);
    };
    timer = setTimeout(() => { if (cur === nt) run(1); }, 350);
  }
  document.addEventListener("mouseover", e => {
    const host = e.target.closest && e.target.closest(HOST);
    const nt = host && host.querySelector(".nm .nt");
    if (nt === cur) return;
    stop();
    if (nt) start(nt);
  });
  document.addEventListener("mouseleave", stop);
  document.addEventListener("scroll", stop, true);
})();
