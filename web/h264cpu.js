// h264cpu: write an H.264 file whose decoder computes a program. Browser and Node (ES module).
//
// The program (fields, ops, layout) and its 16 program frames are compiled in Python and loaded as
// JSON; this file writes everything that depends on the starting state: the grey IDR frame with the
// display as raw samples, the P frames carrying the starting state, the warm-up copies, and the MP4
// container. Its output is byte-identical to the Python writer's.

// ------------------------------------------------------------------ bits
class Bytes {
  constructor(n = 1 << 16) { this.a = new Uint8Array(n); this.len = 0; }
  push(b) { if (this.len === this.a.length) this.grow(1); this.a[this.len++] = b; }
  append(arr) { this.grow(arr.length); this.a.set(arr, this.len); this.len += arr.length; }
  grow(k) {
    if (this.len + k <= this.a.length) return;
    let n = this.a.length * 2;
    while (n < this.len + k) n *= 2;
    const b = new Uint8Array(n); b.set(this.a.subarray(0, this.len)); this.a = b;
  }
  bytes() { return this.a.slice(0, this.len); }
}

class Bits {
  constructor() { this.out = new Bytes(); this.cur = 0; this.n = 0; }
  u(nbits, v) {
    for (let i = nbits - 1; i >= 0; i--) {
      this.cur = (this.cur << 1) | (Math.floor(v / 2 ** i) & 1);
      if (++this.n === 8) { this.out.push(this.cur); this.cur = 0; this.n = 0; }
    }
  }
  ue(v) { const v1 = v + 1, L = Math.floor(Math.log2(v1)); this.u(L, 0); this.u(L + 1, v1); }
  se(v) { this.ue(v > 0 ? 2 * v - 1 : -2 * v); }
  align() { while (this.n) this.u(1, 0); }
  trailing() { this.u(1, 1); this.align(); }
  raw(arr) { if (this.n) throw new Error("raw bytes need byte alignment"); this.out.append(arr); }
  bytes() { if (this.n) throw new Error("unaligned"); return this.out.bytes(); }
}

export function nal(refIdc, type, rbsp) {
  // Annex B: start code, header byte, payload with emulation prevention bytes (00 00 0x -> 00 00 03 0x)
  const out = new Bytes(rbsp.length + rbsp.length / 64 + 16);
  out.append([0, 0, 0, 1, (refIdc << 5) | type]);
  let zeros = 0;
  for (const b of rbsp) {
    if (zeros >= 2 && b <= 3) { out.push(3); zeros = 0; }
    out.push(b);
    zeros = b === 0 ? zeros + 1 : 0;
  }
  return out.bytes();
}

const LOG2_MAX_FRAME_NUM = 4, MAX_FRAME_NUM = 16;

export function sps(widthMbs, heightMbs, crop, numRefFrames, level = 51, fps = 60) {
  const b = new Bits();
  b.u(8, 77); b.u(8, 0); b.u(8, level); b.ue(0); b.ue(LOG2_MAX_FRAME_NUM - 4); b.ue(2);
  b.ue(numRefFrames); b.u(1, 0); b.ue(widthMbs - 1); b.ue(heightMbs - 1); b.u(1, 1); b.u(1, 1);
  if (crop.some((c) => c)) { b.u(1, 1); for (const c of crop) b.ue(c / 2); } else b.u(1, 0);
  b.u(1, 1);                                   // VUI
  b.u(1, 0); b.u(1, 0); b.u(1, 1); b.u(3, 5); b.u(1, 1); b.u(1, 1); b.u(8, 1); b.u(8, 1); b.u(8, 6);
  b.u(1, 0); b.u(1, 1); b.u(32, 1); b.u(32, 2 * fps); b.u(1, 1); b.u(1, 0); b.u(1, 0); b.u(1, 0);
  b.u(1, 1); b.u(1, 1); b.ue(0); b.ue(0); b.ue(15); b.ue(15); b.ue(0); b.ue(numRefFrames);
  b.trailing();
  return nal(3, 7, b.bytes());
}

export function pps() {
  const b = new Bits();
  b.ue(0); b.ue(0); b.u(1, 0); b.u(1, 0); b.ue(0); b.ue(0); b.ue(0); b.u(1, 0); b.u(2, 1);
  b.se(0); b.se(0); b.se(0); b.u(1, 1); b.u(1, 0); b.u(1, 0);
  b.trailing();
  return nal(3, 8, b.bytes());
}

function pcmMb(b, blocks) { b.align(); for (const blk of blocks) b.raw(blk); }

export function idrMixed(pcm, widthMbs, heightMbs) {
  // I_PCM where pcm (Map addr -> [y16x16, cb8x8, cr8x8]) has samples, flat grey (Intra 16x16 DC, no
  // residual) elsewhere; a new slice wherever grey follows PCM, so grey only ever predicts from grey
  const n = widthMbs * heightMbs, starts = [0];
  for (let a = 1; a < n; a++) if (!pcm.has(a) && pcm.has(a - 1)) starts.push(a);
  const out = new Bytes();
  starts.forEach((s, i) => {
    const e = i + 1 < starts.length ? starts[i + 1] : n;
    const b = new Bits();
    b.ue(s); b.ue(7); b.ue(0); b.u(LOG2_MAX_FRAME_NUM, 0); b.ue(0); b.u(1, 0); b.u(1, 0); b.se(0); b.ue(1);
    for (let a = s; a < e; a++) {
      if (pcm.has(a)) { b.ue(25); pcmMb(b, pcm.get(a)); }
      else { b.ue(3); b.ue(0); b.se(0); b.u(1, 1); }
    }
    b.trailing();
    out.append(nal(3, 5, b.bytes()));
  });
  return out.bytes();
}

export function pPcm(frameNum, pcm, nMbs) {
  const b = new Bits();
  b.ue(0); b.ue(5); b.ue(0); b.u(LOG2_MAX_FRAME_NUM, frameNum % MAX_FRAME_NUM);
  b.u(1, 1); b.ue(0); b.u(1, 0); b.u(1, 0); b.se(0); b.ue(1);
  let run = 0;
  for (let a = 0; a < nMbs; a++) {
    if (pcm.has(a)) { b.ue(run); run = 0; b.ue(30); pcmMb(b, pcm.get(a)); } else run++;
  }
  if (run) b.ue(run);
  b.trailing();
  return nal(2, 1, b.bytes());
}

export function pCopy(frameNum, nMbs) {
  const b = new Bits();
  b.ue(0); b.ue(5); b.ue(0); b.u(LOG2_MAX_FRAME_NUM, frameNum % MAX_FRAME_NUM);
  b.u(1, 1); b.ue(0); b.u(1, 0); b.u(1, 0); b.se(0); b.ue(1); b.ue(nMbs);
  b.trailing();
  return nal(2, 1, b.bytes());
}

// ------------------------------------------------------------------ the program's arithmetic
const clip = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);

function evalOp(op, fetch, N) {
  const out = [], [L, Lc] = op.L;
  for (let p = 0; p < 3; p++) {
    const Lp = p === 0 ? L : Lc, prm = op.params[p], r = new Int32Array(N * N);
    const a = fetch(op.inputs[0], p);
    if (op.kind === "bi") {
      const b = fetch(op.inputs[1], p), [w0, w1, o] = prm, add = 1 << Lp, sh = Lp + 1;
      for (let i = 0; i < r.length; i++) r[i] = clip(((w0 * a[i] + w1 * b[i] + add) >> sh) + o);
    } else {
      const [w, o] = prm;
      if (Lp >= 1) { const add = 1 << (Lp - 1); for (let i = 0; i < r.length; i++) r[i] = clip(((w * a[i] + add) >> Lp) + o); }
      else for (let i = 0; i < r.length; i++) r[i] = clip(w * a[i] + o);
    }
    out.push(r);
  }
  return out;
}

function shifted(x, N, dy, dx) {
  // out[y][x] = in[(y + dy) mod N][(x + dx) mod N]: what a motion vector fetches on the torus
  if (!dy && !dx) return x;
  const r = new Int32Array(N * N);
  for (let y = 0; y < N; y++) {
    const sy = ((y + dy) % N + N) % N;
    for (let xx = 0; xx < N; xx++) r[y * N + xx] = x[sy * N + (((xx + dx) % N) + N) % N];
  }
  return r;
}

export function initial(prog, given) {
  // every field not given, computed once from the given ones (the pipeline full of the same wave)
  const N = prog.N, vals = { ...given };
  let pending = prog.ops.filter((o) => !(o.out in vals));
  while (pending.length) {
    const ready = pending.filter((o) => o.inputs.every((i) => i[0] in vals));
    if (!ready.length) throw new Error("cannot order the ops");
    for (const o of ready) vals[o.out] = evalOp(o, ([src, , dy, dx], p) => shifted(vals[src][p], N, dy, dx), N);
    pending = pending.filter((o) => !(o.out in vals));
  }
  return vals;
}

export function render(prog, vals) {
  // the decoded frame for field values at cell resolution; missing fields show the grey background
  const W = prog.widthMbs * 16, H = prog.heightMbs * 16, N = prog.N;
  const y = new Uint8Array(W * H).fill(128), cb = new Uint8Array(W * H / 4).fill(128), cr = cb.slice();
  for (const f of prog.fields) {
    if (!(f.name in vals) || f.image) continue;
    const v = vals[f.name], side = N + 2 * f.halo;
    for (let j = 0; j < side; j++) {
      const sj = (((j - f.halo) % N) + N) % N;
      for (let i = 0; i < side; i++) {
        const s = sj * N + ((((i - f.halo) % N) + N) % N);
        const X = f.x0 + 2 * i, Y = f.y0 + 2 * j;
        y[Y * W + X] = y[Y * W + X + 1] = y[(Y + 1) * W + X] = y[(Y + 1) * W + X + 1] = v[0][s];
        const c = (Y / 2) * (W / 2) + X / 2;
        cb[c] = v[1][s]; cr[c] = v[2][s];
      }
    }
  }
  return { y, cb, cr, W, H };
}

function pcmBlocks(prog, frame, names) {
  const out = new Map(), { y, cb, cr, W } = frame, N = prog.N;
  for (const f of prog.fields) {
    if (!names.has(f.name)) continue;
    const side = (N + 2 * f.halo) * 2;
    for (let my = f.y0 / 16; my < (f.y0 + side) / 16; my++) {
      for (let mx = f.x0 / 16; mx < (f.x0 + side) / 16; mx++) {
        const by = new Uint8Array(256), bcb = new Uint8Array(64), bcr = new Uint8Array(64);
        for (let r = 0; r < 16; r++) by.set(y.subarray((my * 16 + r) * W + mx * 16, (my * 16 + r) * W + mx * 16 + 16), r * 16);
        for (let r = 0; r < 8; r++) {
          const o = (my * 8 + r) * (W / 2) + mx * 8;
          bcb.set(cb.subarray(o, o + 8), r * 8); bcr.set(cr.subarray(o, o + 8), r * 8);
        }
        out.set(my * prog.widthMbs + mx, [by, bcb, bcr]);
      }
    }
  }
  return out;
}

const b64 = (s) => (typeof atob === "function" ? Uint8Array.from(atob(s), (c) => c.charCodeAt(0))
  : new Uint8Array(Buffer.from(s, "base64")));

export function source(prog, given, { crop = true } = {}) {
  // The endless stream for a starting state. head: frame 0 IDR (grey + the display), P frames with the
  // stored starting state, copies; then the 16 program frames (they differ only in frame_num), forever.
  const W = prog.widthMbs * 16, H = prog.heightMbs * 16, nMbs = prog.widthMbs * prog.heightMbs;
  const d = prog.fields.find((f) => f.name === prog.crop), [cw, ch] = d.shown || [2 * prog.N, 2 * prog.N];
  const box = crop ? [d.x0, W - d.x0 - cw, d.y0, H - d.y0 - ch] : [0, 0, 0, 0];
  const init = initial(prog, given), full = render(prog, init);
  const ps = [sps(prog.widthMbs, prog.heightMbs, box, prog.warm, prog.level, prog.fps), pps()];
  const first = new Set(prog.first || [prog.crop]);
  const head = [concat([...ps, idrMixed(pcmBlocks(prog, full, first), prog.widthMbs, prog.heightMbs)])];
  for (const ch of prog.chunks) head.push(pPcm(head.length, pcmBlocks(prog, full, new Set(ch)), nMbs));
  while (head.length < prog.firstProgramFrame) head.push(pCopy(head.length, nMbs));
  const variants = prog.programFrames.map(b64);
  return {
    head, variants, width: crop ? cw : W, height: crop ? ch : H, codedWidth: W, codedHeight: H,
    frame: (f) => (f < head.length ? head[f] : variants[f % MAX_FRAME_NUM]),
  };
}

export function stream(prog, given, nFrames, opts = {}) {
  // [access units] of a finite file: the head, then program frames up to nFrames
  const s = source(prog, given, opts), frames = [];
  for (let f = 0; f < nFrames || f < s.head.length; f++) frames.push(s.frame(f));
  return { frames, width: s.width, height: s.height };
}

export function concat(parts) {
  let n = 0; for (const p of parts) n += p.length;
  const out = new Uint8Array(n); let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

// ------------------------------------------------------------------ MP4 (like ffmpeg -c copy writes it)
function nalUnits(au) {
  // split an Annex B access unit at its 4-byte start codes (this writer never emits 3-byte ones)
  const out = [];
  let s = -1;
  for (let i = 0; i + 3 < au.length; i++) {
    if (au[i] === 0 && au[i + 1] === 0 && au[i + 2] === 0 && au[i + 3] === 1) {
      if (s >= 0) out.push(au.subarray(s, i));
      s = i + 4; i += 3;
    }
  }
  if (s >= 0) out.push(au.subarray(s));
  return out;
}

const u32 = (v) => [(v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255];
const u16 = (v) => [(v >>> 8) & 255, v & 255];
const str = (s) => [...s].map((c) => c.charCodeAt(0));
function box(type, ...parts) {
  const body = concat(parts.map((p) => (p instanceof Uint8Array ? p : new Uint8Array(p))));
  return concat([new Uint8Array([...u32(body.length + 8), ...str(type)]), body]);
}
const full = (type, version, flags, ...parts) => box(type, [version, ...u32(flags).slice(1)], ...parts);

export function avcConfig(au0) {
  // AVCDecoderConfigurationRecord (the body of an avcC box) for the first access unit's SPS and PPS
  const units = nalUnits(au0);
  const s = units.find((u) => (u[0] & 31) === 7), p = units.find((u) => (u[0] & 31) === 8);
  return concat([new Uint8Array([1, s[1], s[2], s[3], 0xff, 0xe1, ...u16(s.length)]), s,
    new Uint8Array([1, ...u16(p.length)]), p]);
}

// an access unit as an MP4 sample: each NAL unit prefixed with its length instead of a start code
export const sample = (au) => concat(nalUnits(au).flatMap((u) => [new Uint8Array(u32(u.length)), u]));

export function mp4(frames, width, height, fps = 60) {
  const timescale = 600, delta = timescale / fps, n = frames.length, dur = n * delta, movieDur = Math.round(n * 1000 / fps);
  const samples = frames.map(sample);
  const matrix = [0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000].flatMap(u32);
  const avcC = box("avcC", avcConfig(frames[0]));
  const colr = box("colr", [...str("nclx"), ...u16(1), ...u16(1), ...u16(6), 0x80]);   // BT.709/709/601, full range
  const avc1 = box("avc1", [0, 0, 0, 0, 0, 0, ...u16(1), ...new Array(16).fill(0), ...u16(width), ...u16(height),
    ...u32(0x00480000), ...u32(0x00480000), ...u32(0), ...u16(1), ...new Array(32).fill(0), ...u16(0x18), ...u16(0xffff)],
    avcC, colr);
  const stbl = (chunkOffset) => box("stbl",
    full("stsd", 0, 0, u32(1), avc1),
    full("stts", 0, 0, [...u32(1), ...u32(n), ...u32(delta)]),
    full("stss", 0, 0, [...u32(1), ...u32(1)]),
    full("stsc", 0, 0, [...u32(1), ...u32(1), ...u32(n), ...u32(1)]),
    full("stsz", 0, 0, [...u32(0), ...u32(n), ...samples.flatMap((s) => u32(s.length))]),
    full("stco", 0, 0, [...u32(1), ...u32(chunkOffset)]));
  const moov = (chunkOffset) => box("moov",
    full("mvhd", 0, 0, [...u32(0), ...u32(0), ...u32(1000), ...u32(movieDur), ...u32(0x00010000), ...u16(0x0100),
      ...new Array(10).fill(0), ...matrix, ...new Array(24).fill(0), ...u32(2)]),
    box("trak",
      full("tkhd", 0, 3, [...u32(0), ...u32(0), ...u32(1), ...u32(0), ...u32(movieDur), ...new Array(8).fill(0),
        ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...matrix, ...u32(width * 65536), ...u32(height * 65536)]),
      box("edts", full("elst", 0, 0, [...u32(1), ...u32(movieDur), ...u32(0), ...u16(1), ...u16(0)])),
      box("mdia",
        full("mdhd", 0, 0, [...u32(0), ...u32(0), ...u32(timescale), ...u32(dur), ...u16(0x55c4), ...u16(0)]),
        full("hdlr", 0, 0, [...u32(0), ...str("vide"), ...new Array(12).fill(0), ...str("VideoHandler"), 0]),
        box("minf",
          full("vmhd", 0, 1, new Array(8).fill(0)),
          box("dinf", full("dref", 0, 0, u32(1), full("url ", 0, 1))),
          stbl(chunkOffset)))));
  const ftyp = box("ftyp", [...str("isom"), ...u32(512), ...str("isomiso2avc1mp41")]);
  const mdatBody = concat(samples);
  const head = ftyp.length + moov(0).length + 8;            // moov first (fast start), then mdat
  return concat([ftyp, moov(head), new Uint8Array([...u32(mdatBody.length + 8), ...str("mdat")]), mdatBody]);
}

// ------------------------------------------------------------------ playing forever (WebCodecs)
export const CODEC = "avc1.4D0033";                          // Main profile, level 5.1

export function decoderConfig(src) {
  return {
    codec: CODEC, codedWidth: src.codedWidth, codedHeight: src.codedHeight,
    description: avcConfig(src.head[0]),                     // samples as in an MP4, the input every WebCodecs takes
    optimizeForLatency: true,
    colorSpace: { primaries: "bt709", transfer: "bt709", matrix: "smpte170m", fullRange: true },   // as the VUI says
  };
}

export async function canDecode(src) {
  if (typeof VideoDecoder === "undefined" || typeof EncodedVideoChunk === "undefined") return false;
  try { return (await VideoDecoder.isConfigSupported(decoderConfig(src))).supported === true; } catch { return false; }
}

export class Player {
  // Hands the browser's H.264 decoder the head, then the 16 program frames, forever. The program's state
  // lives in the decoder's reference frames, so every frame is decoded, in order; only showing is optional.
  // mode "realtime" shows frames at fps; "fast" decodes as fast as the decoder goes and shows the newest
  // frame at each screen refresh. onFrame(frame, index) must close() the frame.
  constructor(src, { fps = 60, mode = "realtime", onFrame, onError } = {}) {
    Object.assign(this, { src, fps, mode, onFrame, onError });
    this.next = 0; this.decoded = 0; this.shown = -1; this.fedBytes = 0;
    this.queue = []; this.latest = null; this.anchor = null; this.running = false; this.closed = false;
    this.variantSamples = new Map(); this.rates = [];
    this.dec = new VideoDecoder({ output: (f) => this.output(f), error: (e) => this.fail(e) });
    this.dec.addEventListener("dequeue", () => this.feed());
    this.dec.configure(decoderConfig(src));
    this.onVisible = () => this.feed();
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", this.onVisible);
    const loop = (now) => { if (this.closed) return; this.tick(now); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }
  play() { this.running = true; this.anchor = null; this.feed(); }
  pause() { this.running = false; }
  setMode(mode) {
    if (mode === this.mode) return;
    if (mode === "fast") {
      if (this.latest) this.latest.close();
      this.latest = this.queue.pop() || null;
      for (const f of this.queue) f.close();
      this.queue = [];
    } else {
      if (this.latest) this.queue.push(this.latest);
      this.latest = null; this.anchor = null;
    }
    this.mode = mode; this.feed();
  }
  index(frame) { return Math.round(frame.timestamp * this.fps / 1e6); }
  sampleFor(f) {
    if (f < this.src.head.length) return sample(this.src.head[f]);
    const k = f % MAX_FRAME_NUM;
    if (!this.variantSamples.has(k)) this.variantSamples.set(k, sample(this.src.variants[k]));
    return this.variantSamples.get(k);
  }
  feed() {
    if (!this.running || this.closed) return;
    if (this.mode === "fast" && typeof document !== "undefined" && document.hidden) return;
    while (this.dec.decodeQueueSize < 3 && (this.mode === "fast" || this.next <= this.shown + 12)) {
      const f = this.next++, data = this.sampleFor(f);
      this.fedBytes += data.length;
      this.dec.decode(new EncodedVideoChunk({ type: f ? "delta" : "key", timestamp: Math.round(f * 1e6 / this.fps), data }));
    }
  }
  output(frame) {
    this.decoded++;
    if (this.closed) { frame.close(); return; }
    if (this.mode === "fast") { if (this.latest) this.latest.close(); this.latest = frame; } else this.queue.push(frame);
    this.feed();
  }
  tick(now) {
    const last = this.rates[this.rates.length - 1];
    if (!last || now - last[0] >= 500) { this.rates.push([now, this.decoded]); if (this.rates.length > 5) this.rates.shift(); }
    if (!this.running) return;
    if (this.mode === "fast") {
      if (this.latest) { const f = this.latest; this.latest = null; this.show(f); }
    } else {
      if (!this.anchor) this.anchor = [now, this.shown + 1];
      let due = this.anchor[1] + Math.floor((now - this.anchor[0]) * this.fps / 1000 + 0.5);
      if (due > this.shown + 30) { this.anchor = [now, this.shown + 1]; due = this.shown + 1; }   // back from a hidden tab
      let pick = null;
      while (this.queue.length && this.index(this.queue[0]) <= due) { if (pick) pick.close(); pick = this.queue.shift(); }
      if (pick) this.show(pick);
      else if (due > this.shown + 1) this.anchor = [now, this.shown + 1];          // the decoder is behind: slow down
    }
    this.feed();
  }
  show(frame) { this.shown = this.index(frame); this.onFrame(frame, this.shown); }
  rate() {
    // frames decoded per second, over the last two seconds or so
    if (this.rates.length < 2) return 0;
    const [t0, d0] = this.rates[0], [t1, d1] = this.rates[this.rates.length - 1];
    return (d1 - d0) * 1000 / (t1 - t0);
  }
  fail(e) { if (this.closed) return; const n = this.decoded; this.close(); if (this.onError) this.onError(e, n); }
  close() {
    if (this.closed) return;
    this.closed = true; this.running = false;
    for (const f of this.queue) f.close();
    this.queue = [];
    if (this.latest) this.latest.close();
    this.latest = null;
    if (this.dec.state !== "closed") this.dec.close();
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", this.onVisible);
  }
}
