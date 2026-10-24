// Preload for the browser test: wraps WebCodecs' VideoDecoder before the page runs, to record what the page
// feeds the decoder and the SHA-256 of every decoded frame the test asks for (all three planes, uncropped,
// and the luma plane alone, for decoders that hand frames back in limited range).
const Real = window.VideoDecoder;
const RT = +(new URLSearchParams(location.search).get("rt") || 360);
const cap = window.__cap = { want: (i) => i < RT, hashes: {}, lumaHashes: {}, lumas: {}, dumpLuma: () => false, pending: 0, fed: 0, keys: 0, order: true, lastTs: -1,
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
          const range = frame.colorSpace && frame.colorSpace.fullRange === false ? "limited" : "full";
          cap.formats.add(`${frame.format} ${frame.codedWidth}x${frame.codedHeight} ${range}`);
          if (cap.want(i)) {
            const c = frame.clone(), buf = new Uint8Array(c.allocationSize());
            cap.pending++;
            c.copyTo(buf).then((layout) => {
              const luma = buf.subarray(0, layout[0].stride * c.codedHeight);
              if (cap.dumpLuma(i)) {
                let s = "";
                for (let k = 0; k < luma.length; k += 32768) s += String.fromCharCode.apply(null, luma.subarray(k, k + 32768));
                cap.lumas[i] = btoa(s);
              }
              c.close();
              return Promise.all([crypto.subtle.digest("SHA-256", buf), crypto.subtle.digest("SHA-256", luma)]);
            }).then(([h, hy]) => { cap.hashes[i] = hex(h); cap.lumaHashes[i] = hex(hy); cap.pending--; },
                    (e) => { cap.errors.push("copy " + e); cap.pending--; });
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
