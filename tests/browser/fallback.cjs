// Browser tests for the page's other modes. Usage: electron fallback.cjs <page url> <out.json> [reduced]
// With ?fallback the page acts as if WebCodecs could not decode H.264, writes a finite MP4 and plays it in a
// <video>. With "reduced", the window asks for reduced motion: the page must write the stream and wait.
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
const args = process.argv.slice(2).filter((a) => !a.startsWith("--") && !a.endsWith(".cjs"));
const [url, outPath, reduced] = args;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  const result = {};
  const w = new BrowserWindow({ width: 1280, height: 1000, show: true,
    webPreferences: { preload: require("path").join(__dirname, "capture.js"), contextIsolation: false, sandbox: false, backgroundThrottling: false } });
  w.focus();
  const js = (code) => w.webContents.executeJavaScript(code);
  try {
    if (reduced) {
      // emulate the preference on the loaded page, then reload it so the page starts with it
      await w.loadURL(url);
      w.webContents.debugger.attach("1.3");
      await w.webContents.debugger.sendCommand("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
      await js("window.__cap.fed = 0; location.reload(); true").catch(() => {});
      await new Promise((r) => w.webContents.once("did-finish-load", r));
      await sleep(4000);
      const before = await js("window.__cap.fed");
      await sleep(1500);
      Object.assign(result, await js(`({ fed: window.__cap.fed, decoders: window.__cap.decoders, pause: document.getElementById("pause").textContent,
        status: document.getElementById("status").hidden ? "" : document.getElementById("status").textContent })`), { fedBefore: before });
      await js(`document.getElementById("pause").click(); true`);
      await sleep(1500);
      result.afterResume = await js("window.__cap.fed");
      throw null;
    }
    await w.loadURL(url);
    const t0 = Date.now();
    // Chromium pauses a muted autoplaying video while it is off screen, so bring it into view, as a visitor would
    while (Date.now() - t0 < 120000 && !(await js(`(() => { const v = document.getElementById("fallback"); v.scrollIntoView({ block: "center" });
      return v.currentTime > 1.5; })()`))) await sleep(200);
    Object.assign(result, await js(`(() => { const v = document.getElementById("fallback");
      return { playing: v.currentTime > 1.5, duration: v.duration, width: v.videoWidth, height: v.videoHeight, visible: !v.hidden,
        canvasHidden: document.getElementById("out").hidden, mode: document.getElementById("mode").dataset.kind,
        modeText: document.getElementById("mode").textContent, decoders: window.__cap.decoders,
        pauseHidden: document.getElementById("pause").hidden, error: v.error && v.error.message }; })()`));
  } catch (e) {
    if (e !== null) result.error = String(e && e.stack || e);
  }
  fs.writeFileSync(outPath, JSON.stringify(result));
  app.quit();
});
