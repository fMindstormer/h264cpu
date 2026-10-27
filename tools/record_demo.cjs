// Records the page for the README: tests/browser/node_modules/.bin/electron tools/record_demo.cjs <url> <outdir>
// (serve docs/ first, e.g. python -m http.server -d docs). Writes frame-NNNN.jpg, times.txt and steps.json;
// then python tools/compose_demo.py <outdir> docs/images/demo.webp adds the captions.
const { app, BrowserWindow } = require("electron");
const fs = require("fs"), path = require("path");
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
app.commandLine.appendSwitch("force-device-scale-factor", "1");
const [url, outDir] = process.argv.slice(2).filter((a) => !a.startsWith("--") && !a.endsWith(".cjs"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
app.whenReady().then(async () => {
  const w = new BrowserWindow({ width: 1280, height: 800, useContentSize: true, show: true, webPreferences: { backgroundThrottling: false } });
  const js = (c) => w.webContents.executeJavaScript(c);
  await w.loadURL(url);
  await sleep(2500);
  const top = await js(`document.querySelector(".bench").getBoundingClientRect().top + scrollY - 12`);
  await js(`scrollTo(0, ${top}); true`);
  await sleep(300);
  const t0 = Date.now(), steps = [];
  let n = 0, recording = true;
  (async () => {
    while (recording) {
      const t = Date.now();
      const img = await w.webContents.capturePage();
      fs.writeFileSync(path.join(outDir, `frame-${String(n).padStart(4, "0")}.jpg`), img.toJPEG(92));
      fs.appendFileSync(path.join(outDir, "times.txt"), `${n} ${t - t0} ${await js("scrollY")}\n`);
      n++;
      await sleep(Math.max(0, 100 - (Date.now() - t)));
    }
  })();
  const step = (k) => steps.push([k, Date.now() - t0]);
  const rect = async (sel) => js(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()`);
  const mouse = (type, x, y) => w.webContents.sendInputEvent({ type, x: Math.round(x), y: Math.round(y), button: "left", clickCount: 1 });
  // 1. choose a pattern, then draw on it
  step("choose");
  await sleep(1200);
  await js(`document.querySelector('[data-preset="gun"]').click(); true`);
  await sleep(2200);
  step("draw");
  // with the keyboard: focus the pattern, walk the cursor, Space toggles cells along a line
  await js(`document.getElementById("editor").focus({ preventScroll: true }); true`);
  const NAMES = { Down: "ArrowDown", Left: "ArrowLeft", Right: "ArrowRight", Space: " " };
  const key = (k) => js(`document.getElementById("editor").dispatchEvent(new KeyboardEvent("keydown", { key: ${JSON.stringify(NAMES[k])}, bubbles: true, cancelable: true })); true`);
  for (let i = 0; i < 4; i++) { await key("Down"); await key("Down"); await key("Down"); await key("Down"); await key("Down"); await key("Down"); await key("Down"); await key("Down"); await key("Down"); await key("Down"); }
  for (let i = 0; i < 6; i++) await key("Left");
  for (let i = 0; i < 6; i++) { for (let j = 0; j < 10; j++) await key("Left"); }
  for (let i = 0; i < 70; i++) { await key("Space"); await key("Right"); await sleep(22); }
  await sleep(700);
  const [rx, ry, rw, rh] = await rect("#run");
  mouse("mouseMove", rx + rw / 2, ry + rh / 2); await sleep(300);
  mouse("mouseDown", rx + rw / 2, ry + rh / 2); mouse("mouseUp", rx + rw / 2, ry + rh / 2);
  // 2. the decoder runs; the cycle turns while the board changes
  step("run");
  await sleep(8500);
  // 3. the whole frame
  step("machine");
  await js(`document.getElementById("machine-toggle").click(); document.getElementById("machine").scrollIntoView({ block: "start" }); true`);
  await sleep(7500);
  // 4. download
  step("download");
  await js(`scrollTo(0, ${top}); true`);
  await sleep(400);
  const [sx, sy, sw, sh] = await rect("#save");
  mouse("mouseMove", sx + sw / 2, sy + sh / 2);
  await js(`document.getElementById("save").focus(); true`);
  await sleep(3500);
  step("end");
  recording = false;
  await sleep(300);
  fs.writeFileSync(path.join(outDir, "steps.json"), JSON.stringify({ steps, save: [sx, sy, sw, sh], top }));
  app.quit();
});
