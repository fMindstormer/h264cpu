"""The page in a real browser engine: Electron's Chromium (which decodes H.264) runs docs/index.html, and
every frame its decoder hands the page must be the frame the simulation predicts, sample for sample.

Needs Electron (npm install --prefix tests/browser) and xvfb-run; skipped otherwise."""
import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
import pytest

from h264cpu import mp4, web
from h264cpu.programs import life, tunnel

HERE = Path(__file__).resolve().parent / "browser"
ELECTRON = HERE / "node_modules" / ".bin" / "electron"
pytestmark = pytest.mark.skipif(not ELECTRON.exists() or shutil.which("xvfb-run") is None,
                                reason="needs Electron (npm install --prefix tests/browser) and xvfb-run")


def frame_hash(planes):
    return hashlib.sha256(b"".join(np.ascontiguousarray(p, dtype=np.uint8).tobytes() for p in planes)).hexdigest()


def expected_hashes(m, init, frames):
    want, out = set(frames), {}
    history = [init] * (m.max_delay() + 1)
    for f in range(max(frames) + 1):
        if f >= m.first_program_frame:
            history.append(m.step(history))
            del history[0]
        if f in want:
            out[f] = frame_hash(m.render(history[-1]) if f >= m.first_program_frame else m.warmup_frame(init, None, f))
    return out


PLANS = {"life": (360, 6000), "tunnel": (240, 970)}          # frames hashed in real time; flat out up to


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    docs = tmp_path_factory.mktemp("site") / "docs"
    web.main(docs)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(docs))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()


@pytest.mark.parametrize("name", sorted(PLANS))
def test_page_in_chromium(name, site, tmp_path):
    rt, fast = PLANS[name]
    env = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x1600x24", str(ELECTRON), "--no-sandbox",
                    str(HERE / "harness.cjs"), f"{site}?rt={rt}#{name}", str(tmp_path / "result.json"),
                    str(tmp_path / "shot"), str(fast)], env=env, check=True, timeout=1500)
    r = json.loads((tmp_path / "result.json").read_text())
    assert "error" not in r, r.get("error")
    assert not r["errors"], r["errors"]

    # what the page fed: one key frame per run, then delta frames in order
    assert r["keys"] == 1 and r["order"] and r["decoders"] == 1
    assert r["fed"] >= fast

    # every frame of the first seconds, and every 97th flat out, equal the simulation
    prog = {"life": life, "tunnel": tunnel}[name]
    m = prog.build()
    board = np.array([c == "1" for c in r["board"]]).reshape(prog.N, prog.N)
    if name == "life":
        init, stored, crop, first = m.initial(life.given(board)), None, "D", None
    else:
        init, stored, crop, first = m.initial(tunnel.start_given(board)), tunnel.start(m)[1], tunnel.CROP, tunnel.FIRST
    frames = m.stream(init, 600, crop, stored=stored, first=first)   # also sets the first program frame
    got = {int(k): v for k, v in r["hashes"].items()}
    assert set(range(rt)) <= set(got) and fast in got
    want = expected_hashes(m, init, sorted(got))
    bad = [f for f in sorted(got) if got[f] != want[f]]
    assert not bad, f"{len(bad)} of {len(got)} frames differ, first {bad[:5]}"

    # pause stops the decoder, resume continues it
    assert r["pause"]["during"] == 0 and r["pause"]["after"] > 30

    # the download is this run as a 10 s file, byte for byte what Python writes
    assert r["downloads"] and r["downloads"][0]["state"] == "completed"
    assert Path(r["downloads"][0]["path"]).read_bytes() == mp4.mux(frames, *m.fields[crop].shown_px, 60)

    # a preset starts a new run: a new decoder, a new key frame, no errors
    assert r["secondRun"]["decoders"] == 2 and r["secondRun"]["keys"] == 2 and not r["secondRun"]["errors"]
    print(name, r["realtime"], r["fast"], r["stats2"])
