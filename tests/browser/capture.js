// Preload for the browser test: wraps WebCodecs' VideoDecoder before the page runs, to record what the page
// feeds the decoder and the SHA-256 of every decoded frame the test asks for (all three planes, uncropped).
const Real = window.VideoDecoder;
const RT = +(new URLSearchParams(location.search).get("rt") || 360);
const cap = window.__cap = { want: (i) => i < RT, hashes: {}, pending: 0, fed: 0, keys: 0, order: true, lastTs: -1,
  maxIndex: -1, formats: new Set(), errors: [], decoders: 0 };
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
if (Real) {
  window.VideoDecoder = class extends Real {
    constructor(init) {
      cap.decoders++;
      super({
        error: (e) => { cap.errors.push(String(e)); init.error(e); },
        output: (frame) => {
          const i = Math.round(frame.timestamp * 60 / 1e6);
          cap.maxIndex = Math.max(cap.maxIndex, i);
          cap.formats.add(`${frame.format} ${frame.codedWidth}x${frame.codedHeight}`);
          if (cap.want(i)) {
            const c = frame.clone(), buf = new Uint8Array(c.allocationSize());
            cap.pending++;
            c.copyTo(buf).then(() => { c.close(); return crypto.subtle.digest("SHA-256", buf); })
              .then((h) => { cap.hashes[i] = hex(h); cap.pending--; }, (e) => { cap.errors.push("copy " + e); cap.pending--; });
          }
          init.output(frame);
        },
      });
    }
    configure(cfg) { cap.lastTs = -1; return super.configure(cfg); }
    decode(chunk) {
      cap.fed++;
      if (chunk.type === "key") cap.keys++;
      if (chunk.timestamp <= cap.lastTs) cap.order = false;
      cap.lastTs = chunk.timestamp;
      return super.decode(chunk);
    }
  };
}
