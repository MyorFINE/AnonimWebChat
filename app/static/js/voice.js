/* Anonim Chat by Hevorix — ovozli xabar: yozish + ovozni o'zgartirish (qalinlashtirish). HAMMASI QURILMADA.

   Xom (asl) ovoz qurilmadan HECH QACHON chiqmaydi: yozilgan ovoz darhol o'zgartiriladi, so'ng E2EE bilan shifrlanib yuboriladi.
   "Asl ovozni yuborish" degan kod yo'li umuman yo'q.

   Ovoz o'zgartirish (pitch + formanta pasaytirish, tezlik o'zgarmaydi):
     1. mono 16 kHz ga o'tkaziladi, past chastotali shovqin/DC olib tashlanadi
     2. ovoz r marta (0.74..0.82, HAR XABARDA tasodifiy) sekinlashtirib-pasaytiriladi (resampling): ovoz balandligi VA tembri pasayadi
     3. WSOLA bilan tezligi qaytariladi (davomiylik asl holiga keladi)
     r har xabarda boshqacha: bir xil nisbatni bilgan hujumchi ham ovozni aniq "qaytara" olmaydi.
   Chiqish: 16-bit mono WAV (metama'lumotsiz). */
"use strict";
(root => {
const RATE = 16000, MAX_SEC = 300, MIN_SEC = 0.8;
const SHIFT_MIN = 0.74, SHIFT_MAX = 0.82;            // qancha past bo'lishini shu yerdan sozlang (kichikroq = qalinroq ovoz)

const rnd = () => { const b = new Uint32Array(1); root.crypto.getRandomValues(b); return b[0] / 4294967296; };
const tick = () => new Promise(r => setTimeout(r, 0));

/* ---------------- DSP (sof funksiyalar: Node'da ham testlanadi) ---------------- */
function highpass(x, fc = 70) {                       // DC va past chastotali shovqin
  const rc = 1 / (2 * Math.PI * fc), dt = 1 / RATE, a = rc / (rc + dt);
  let py = 0, px = 0;
  for (let i = 0; i < x.length; i++) { const v = x[i]; py = a * (py + v - px); px = v; x[i] = py; }
  return x;
}

function resampleBy(x, step) {                        // Catmull-Rom; step < 1 => uzunroq (pastroq ovoz)
  const n = x.length, m = Math.max(1, Math.floor((n - 1) / step)), y = new Float32Array(m);
  for (let i = 0; i < m; i++) {
    const t = i * step, k = t | 0, f = t - k;
    const p0 = x[k > 0 ? k - 1 : 0], p1 = x[k], p2 = x[k + 1 < n ? k + 1 : n - 1], p3 = x[k + 2 < n ? k + 2 : n - 1];
    y[i] = p1 + 0.5 * f * (p2 - p0 + f * (2 * p0 - 5 * p1 + 4 * p2 - p3 + f * (3 * (p1 - p2) + p3 - p0)));
  }
  return y;
}

async function wsolaCompress(x, alpha, onProgress) { // davomiylikni alpha (<1) marta qisqartiradi, ovoz balandligini saqlaydi
  const N = 800, Hs = 400, TOL = 240, STEP = 2, Ha = Hs / alpha;
  const outLen = Math.floor(x.length * alpha);
  if (x.length < N * 3 || outLen < N) return x.slice(0, Math.max(1, outLen));
  const out = new Float32Array(outLen + N), win = new Float32Array(N), win0 = new Float32Array(N);
  for (let i = 0; i < N; i++) { win[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / N); win0[i] = i < N / 2 ? 1 : win[i]; }
  const frames = Math.ceil(outLen / Hs);
  let prev = 0;
  for (let k = 0; k < frames; k++) {
    let pos = Math.min(Math.round(k * Ha), x.length - N);
    if (k > 0) {
      const tgt = prev + Hs;                          // oldingi bo'lakning "tabiiy davomi"
      if (tgt + Hs <= x.length) {
        let best = -Infinity, bp = pos;
        for (let d = -TOL; d <= TOL; d += STEP) {
          const c = pos + d;
          if (c < 0 || c + N > x.length) continue;
          let dot = 0, e = 1e-9;
          for (let j = 0; j < Hs; j += STEP) { const v = x[c + j]; dot += v * x[tgt + j]; e += v * v; }
          const s = dot / Math.sqrt(e);
          if (s > best) { best = s; bp = c; }
        }
        pos = bp;
      }
    }
    const w = k === 0 ? win0 : win, o = k * Hs;
    for (let j = 0; j < N; j++) { const idx = o + j; if (idx < out.length) out[idx] += x[pos + j] * w[j]; }
    prev = pos;
    if ((k & 127) === 127) { if (onProgress) onProgress(k / frames); await tick(); }
  }
  return out.subarray(0, outLen);
}

function finish(y) {                                  // ovoz balandligini tekislash + chetlarini yumshatish
  let peak = 1e-6;
  for (let i = 0; i < y.length; i++) { const a = Math.abs(y[i]); if (a > peak) peak = a; }
  const g = Math.min(6, 0.9 / peak), fade = Math.min(160, y.length >> 1);
  for (let i = 0; i < y.length; i++) y[i] *= g;
  for (let i = 0; i < fade; i++) { const f = i / fade; y[i] *= f; y[y.length - 1 - i] *= f; }
  return y;
}

function encodeWav(f32, rate = RATE) {                // 16-bit PCM mono
  const n = f32.length, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) { const s = Math.max(-1, Math.min(1, f32[i])); v.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true); }
  return buf;
}

/* x: mono Float32 (RATE Hz). O'zi tozalanadi (nollanadi). Natija: {samples, ratio} */
async function disguiseSamples(x, onProgress, ratio) {
  const r = ratio || SHIFT_MIN + rnd() * (SHIFT_MAX - SHIFT_MIN);
  highpass(x);
  const low = resampleBy(x, r); x.fill(0);
  const y = await wsolaCompress(low, r, onProgress); low.fill(0);
  return {samples: finish(y), ratio: r};
}

/* ---------------- brauzer qismi ---------------- */
async function decodeToMono16k(blob) {
  const AC = root.AudioContext || root.webkitAudioContext, OAC = root.OfflineAudioContext || root.webkitOfflineAudioContext;
  if (!AC || !OAC) throw new Error("Brauzeringiz ovozni qayta ishlashni qo'llamaydi");
  const ac = new AC();
  try {
    const raw = await blob.arrayBuffer();
    const buf = await new Promise((res, rej) => { const p = ac.decodeAudioData(raw, res, rej); if (p && p.catch) p.catch(rej); });
    const off = new OAC(1, Math.max(1, Math.ceil(buf.duration * RATE)), RATE);
    const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start();
    const r = await off.startRendering();
    return r.getChannelData(0).slice();
  } finally { try { ac.close(); } catch (_) {} }
}

async function disguise(blob, onProgress) {          // yozilgan xom ovoz -> o'zgartirilgan WAV
  const x = await decodeToMono16k(blob);
  if (x.length / RATE < MIN_SEC) { x.fill(0); return null; }
  const {samples} = await disguiseSamples(x, onProgress);
  const dur = samples.length / RATE, wav = new Blob([encodeWav(samples)], {type: "audio/wav"});
  samples.fill(0);
  return {wav, duration: dur};
}

const MIMES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
async function record({onLimit, onLost} = {}) {
  if (!root.isSecureContext) throw new Error("Mikrofon faqat HTTPS (xavfsiz ulanish) orqali ishlaydi");
  const md = root.navigator && root.navigator.mediaDevices;
  if (!md || !md.getUserMedia || !root.MediaRecorder) throw new Error("Brauzeringiz ovoz yozishni qo'llamaydi");
  let stream;
  try { stream = await md.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}}); }
  catch (e) {
    const n = e && e.name;
    throw new Error(n === "NotAllowedError" || n === "SecurityError" ? "Mikrofonga ruxsat berilmagan. Brauzer sozlamalaridan ruxsat bering"
      : n === "NotFoundError" || n === "OverconstrainedError" ? "Mikrofon topilmadi" : "Mikrofonni ochib bo'lmadi");
  }
  const mime = MIMES.find(t => root.MediaRecorder.isTypeSupported && root.MediaRecorder.isTypeSupported(t)) || "";
  let rec;
  try { rec = new root.MediaRecorder(stream, mime ? {mimeType: mime} : undefined); }
  catch (_) { stream.getTracks().forEach(t => t.stop()); throw new Error("Ovoz yozishni boshlab bo'lmadi"); }
  const chunks = []; let discard = false, timer = 0, failed = false;
  const release = () => { clearTimeout(timer); stream.getTracks().forEach(t => { t.onended = null; t.stop(); }); };   // mikrofon indikatori darhol o'chadi
  const finished = new Promise(res => {
    rec.onstop = () => { release(); const b = discard || failed ? null : new Blob(chunks, {type: rec.mimeType || mime || "audio/webm"}); chunks.length = 0; res(b); };
  });
  rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
  rec.onerror = () => { failed = true; try { if (rec.state !== "inactive") rec.stop(); else release(); } catch (_) { release(); } if (onLost) onLost(); };
  stream.getAudioTracks().forEach(t => { t.onended = () => { if (!discard && onLost) onLost(); }; });
  const t0 = root.performance.now();
  rec.start(500);
  timer = setTimeout(() => { if (onLimit) onLimit(); }, MAX_SEC * 1000);
  return {
    elapsed: () => (root.performance.now() - t0) / 1000,
    stop: () => { try { if (rec.state !== "inactive") rec.stop(); else release(); } catch (_) { release(); } return finished; },
    cancel: () => { discard = true; try { if (rec.state !== "inactive") rec.stop(); else release(); } catch (_) { release(); } return finished; },
  };
}

root.Voice = {record, disguise, MAX_SEC, MIN_SEC, RATE, _dsp: {highpass, resampleBy, wsolaCompress, finish, encodeWav, disguiseSamples}};
})(typeof globalThis !== "undefined" ? globalThis : window);
