// Ovozli xabar DSP'sini Node'da tekshiradi: ovoz balandligi pasayadi, davomiylik saqlanadi, WAV to'g'ri, har xabarda nisbat tasodifiy.
// Ishlatish: node tests/voice_dsp_test.mjs
import fs from "node:fs"; import vm from "node:vm"; import assert from "node:assert/strict";
const src = fs.readFileSync(new URL("../app/static/js/voice.js", import.meta.url).pathname, "utf8");
vm.runInThisContext(src);
const {highpass, encodeWav, disguiseSamples} = globalThis.Voice._dsp, RATE = globalThis.Voice.RATE;

function synth(sec, f0) {                                   // unli tovushga o'xshash: garmonikalar + sekin tebranish + amplituda bosqichlari
  const n = Math.floor(sec * RATE), x = new Float32Array(n);
  let ph = 0;
  for (let i = 0; i < n; i++) {
    const t = i / RATE, f = f0 * (1 + 0.02 * Math.sin(2 * Math.PI * 4.5 * t));
    ph += 2 * Math.PI * f / RATE;
    let s = 0; for (let h = 1; h <= 8; h++) s += Math.sin(h * ph) / h;
    x[i] = 0.25 * s * (0.6 + 0.4 * Math.sin(2 * Math.PI * 1.3 * t));
  }
  return x;
}
function f0Of(x, from, len) {                               // avtokorrelyatsiya bilan asosiy chastota
  let best = 0, bl = 0;
  for (let lag = Math.floor(RATE / 400); lag <= Math.floor(RATE / 70); lag++) {
    let c = 0, e1 = 1e-9, e2 = 1e-9;
    for (let i = from; i < from + len; i++) { c += x[i] * x[i + lag]; e1 += x[i] ** 2; e2 += x[i + lag] ** 2; }
    c /= Math.sqrt(e1 * e2); if (c > best) { best = c; bl = lag; }
  }
  return RATE / bl;
}

const src0 = synth(6, 180);
const before = f0Of(src0, 20000, 4000);
assert.ok(Math.abs(before - 180) < 6, "asl f0 " + before);

const t0 = Date.now();
const {samples, ratio} = await disguiseSamples(Float32Array.from(src0), null, 0.78);
const ms = Date.now() - t0;
const ratioLen = samples.length / src0.length;
assert.ok(Math.abs(ratioLen - 1) < 0.02, "davomiylik o'zgardi: " + ratioLen);
const after = f0Of(samples, 20000, 4000);
assert.ok(Math.abs(after / before - 0.78) < 0.04, `ovoz balandligi kutilgandek emas: ${before} -> ${after}`);
let peak = 0; for (const v of samples) { assert.ok(Number.isFinite(v)); peak = Math.max(peak, Math.abs(v)); }
assert.ok(peak <= 1 && peak > 0.5, "peak " + peak);
console.log(`ok: f0 ${before.toFixed(1)} -> ${after.toFixed(1)} Hz (r=${ratio}), davomiylik x${ratioLen.toFixed(3)}, ${ms} ms (6 s ovoz)`);

// tasodifiy nisbat: har chaqiruvda boshqacha va belgilangan oraliqda
const rs = [];
for (let i = 0; i < 12; i++) rs.push((await disguiseSamples(synth(1, 150))).ratio);
assert.ok(rs.every(r => r >= 0.74 && r <= 0.82), "nisbat oraliqdan tashqarida");
assert.ok(new Set(rs.map(r => r.toFixed(4))).size >= 8, "nisbat tasodifiy emas");
console.log("ok: nisbat har xabarda tasodifiy:", rs.slice(0, 4).map(r => r.toFixed(3)).join(", "), "…");

// WAV sarlavhasi
const wav = new DataView(encodeWav(samples));
const tag = (o, n) => String.fromCharCode(...Array.from({length: n}, (_, i) => wav.getUint8(o + i)));
assert.equal(tag(0, 4), "RIFF"); assert.equal(tag(8, 4), "WAVE"); assert.equal(tag(36, 4), "data");
assert.equal(wav.getUint32(24, true), RATE); assert.equal(wav.getUint16(22, true), 1); assert.equal(wav.getUint16(34, true), 16);
assert.equal(wav.getUint32(40, true), samples.length * 2); assert.equal(wav.byteLength, 44 + samples.length * 2);
console.log("ok: WAV sarlavhasi to'g'ri, hajm", (wav.byteLength / 1024).toFixed(0), "KB / 6 s");

// juda qisqa/jim kirish buzilmasligi kerak
const quiet = await disguiseSamples(new Float32Array(RATE));
assert.ok(quiet.samples.every(Number.isFinite));
console.log("ok: jim kirish buzilmaydi");
