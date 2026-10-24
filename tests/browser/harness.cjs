// Browser test for the page: Electron (Chromium with H.264) loads the built page, lets it run, and records
// what the decoder produced. Usage: electron harness.cjs <page url?rt=R#program> <out.json> <shot prefix> <F>
// R: frames hashed in real time from frame 0; F: flat out, every 97th frame up to frame F is hashed.
// Run under xvfb-run. tests/test_browser.py checks the result against the simulation.
const { app, BrowserWindow, session } = require("electron");
const path = require("path");
const fs = require("fs");
app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
const [url, outPath, shotPrefix, fastTo] = process.argv.slice(-4);
const RT = +(new URL(url).searchParams.get("rt") || 360), F = +fastTo;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  const result = { log: [] };
  const log = (m) => { result.log.push(m); console.log(m); };
  const downloads = [];
  session.defaultSession.on("will-download", (e, item) => {
    const p = path.join(path.dirname(outPath), `download-${downloads.length}.mp4`);
    item.setSavePath(p);
    item.once("done", (ev, state) => downloads.push({ path: p, state }));
  });
  const w = new BrowserWindow({ width: 1280, height: 1600, show: true,
    webPreferences: { preload: path.join(__dirname, "capture.js"), contextIsolation: false, sandbox: false, backgroundThrottling: false } });
  w.webContents.on("console-message", (e, level, message) => { if (level >= 2) log("console: " + message); });
  const js = (code) => w.webContents.executeJavaScript(code);
  const waitFor = async (code, ms, what) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { if (await js(code)) return Date.now() - t0; await sleep(100); }
    throw new Error("timed out waiting for " + what);
  };
  try {
    await w.loadURL(url);
    // 1. real time: every frame of the first 6 seconds (capture.js hashes those from the start)
    const t1 = await waitFor(`window.__cap.maxIndex >= ${RT} && window.__cap.pending === 0`, 180000, "real-time frames");
    result.board = await js(`(() => { const e = document.getElementById("editor"), n = e.width;
      const d = e.getContext("2d").getImageData(0, 0, n, n).data;
      let s = ""; for (let i = 0; i < n * n; i++) s += d[4 * i] === 246 ? "1" : "0"; return s; })()`);
    result.realtime = { frames: await js("window.__cap.maxIndex"), ms: t1 };
    result.stats1 = await js(`document.getElementById("stats").textContent`);
    await w.webContents.capturePage().then((img) => fs.writeFileSync(shotPrefix + "-realtime.png", img.toPNG()));
    // 2. pause: the decoder gets nothing more, resume: it carries on
    await js(`document.getElementById("pause").click(); true`);
    await sleep(600);
    const p0 = await js("window.__cap.maxIndex");
    await sleep(1500);
    const p1 = await js("window.__cap.maxIndex");
    await js(`document.getElementById("pause").click(); true`);
    await sleep(1500);
    const p2 = await js("window.__cap.maxIndex");
    result.pause = { during: p1 - p0, after: p2 - p1 };
    // 3. flat out, with the whole machine shown: every 97th frame up to F
    await js(`window.__cap.want = (i) => i % 97 === 0 || i === ${F};
      document.querySelector('[data-speed="fast"]').click();
      const b = document.getElementById("whole-box"); b.checked = true; b.dispatchEvent(new Event("change")); true`);
    const t3 = await waitFor(`window.__cap.maxIndex >= ${F} && window.__cap.pending === 0`, 900000, "fast frames");
    result.fast = { frames: await js("window.__cap.maxIndex"), ms: t3 };
    result.stats2 = await js(`document.getElementById("stats").textContent`);
    await w.webContents.capturePage().then((img) => fs.writeFileSync(shotPrefix + "-fast.png", img.toPNG()));
    // 4. download this run as a 10 s file
    await js(`window.__cap.want = () => false; const d = document.getElementById("dur"); d.value = "10";
      document.getElementById("save").click(); true`);
    const t4 = Date.now();
    while (!downloads.length && Date.now() - t4 < 60000) await sleep(100);
    result.downloads = downloads;
    const cap = await js(`(() => { const c = window.__cap; return { hashes: c.hashes, fed: c.fed, keys: c.keys, order: c.order,
      formats: [...c.formats], errors: c.errors, decoders: c.decoders }; })()`);
    Object.assign(result, cap);
    // 5. a new run (a preset) starts a new decoder from frame 0
    await js(`window.__cap.maxIndex = -1; document.querySelector('[data-preset="gun"]').click(); true`);
    await waitFor("window.__cap.decoders >= 2 && window.__cap.maxIndex >= 0", 60000, "second run");
    await sleep(2000);
    result.secondRun = await js(`({ decoders: window.__cap.decoders, keys: window.__cap.keys, errors: window.__cap.errors,
      status: document.getElementById("status").hidden ? "" : document.getElementById("status").textContent })`);
  } catch (e) {
    result.error = String(e && e.stack || e);
  }
  fs.writeFileSync(outPath, JSON.stringify(result));
  app.quit();
});
