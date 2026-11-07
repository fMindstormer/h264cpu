// Browser test for the decoder check. Usage: electron survey.cjs <page url?decoder=…#life> <out.json> [tamper]
// Runs Life flat out until the page has checked 200 shown frames against its own JavaScript Life, or until
// it says no decoder of the asked kind exists, then records the check and the result text the page reports.
// With "tamper", every canvas readback has one cell's pixel inverted, as a decoder that got one cell wrong.
const { app, BrowserWindow } = require("electron");
const fs = require("fs");
app.commandLine.appendSwitch("no-sandbox");
const args = process.argv.slice(2).filter((a) => !a.startsWith("--") && !a.endsWith(".cjs"));
const [url, outPath, tamper] = args;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  const result = {};
  const w = new BrowserWindow({ width: 1280, height: 1000, show: true,
    webPreferences: { preload: require("path").join(__dirname, "capture.js"), contextIsolation: false, sandbox: false, backgroundThrottling: false } });
  w.focus();
  const js = (code) => w.webContents.executeJavaScript(code);
  const state = () => js(`({ state: document.getElementById("check").dataset.state || "", text: document.getElementById("check").textContent })`);
  try {
    await w.loadURL(url);
    if (tamper) await js(`(() => { const get = CanvasRenderingContext2D.prototype.getImageData;
      CanvasRenderingContext2D.prototype.getImageData = function (...a) {
        const img = get.apply(this, a);
        for (let k = 0; k < 3; k++) img.data[k] = 255 - img.data[k];
        return img;
      }; return true; })()`);
    await js(`document.querySelector('[data-speed="fast"]').click(); true`);
    const t0 = Date.now();
    let s;
    while (Date.now() - t0 < 240000) {
      s = await state();
      if (s.state === "bad" || s.state === "none" || (s.state === "ok" && +s.text.replace(/,/g, "").match(/^\d+/)[0] >= 200)) break;
      await sleep(250);
    }
    Object.assign(result, s, await js(`({ pressed: document.querySelector('[data-accel][aria-pressed="true"]').dataset.accel,
      decoders: window.__cap.decoders, errors: window.__cap.errors, formats: [...window.__cap.formats],
      status: document.getElementById("status").hidden ? "" : document.getElementById("status").textContent })`));
    await js(`document.getElementById("copy-result").click(); true`);   // the button must not throw, clipboard or not
    // the page sets the link's address when it is clicked; the test keeps the click from opening it
    result.report = await js(`(() => { const a = document.getElementById("report"); a.addEventListener("click", (e) => e.preventDefault());
      a.dispatchEvent(new MouseEvent("click", { cancelable: true })); return a.href; })()`);
  } catch (e) {
    result.error = String(e && e.stack || e);
  }
  fs.writeFileSync(outPath, JSON.stringify(result));
  app.quit();
});
