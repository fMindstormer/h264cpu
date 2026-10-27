"""The browser writer (web/h264cpu.js) must write exactly the bytes the Python writer and muxer write."""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from h264cpu import mp4
from h264cpu.programs import life, primes, tunnel
from h264cpu.web import export, primes_given

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_browser_writer_matches_python(tmp_path):
    m = life.build()
    board = life.soup(seed=7, density=0.25)
    export(m, life.given(board), tmp_path / "life.json")
    frames = m.stream(m.initial(life.given(board)), 300, "D")
    board.astype(np.uint8).tofile(tmp_path / "board.bin")
    subprocess.run(["node", str(ROOT / "web" / "test_parity.mjs"), str(tmp_path / "life.json"),
                    str(tmp_path / "board.bin"), "300", str(tmp_path / "js")], check=True)
    assert (tmp_path / "js.264").read_bytes() == b"".join(frames)
    assert (tmp_path / "js.mp4").read_bytes() == mp4.mux(frames, 2 * life.N, 2 * life.N, 60)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_browser_writer_matches_python_tunnel(tmp_path):
    """The same for the tunnel: a picture field that starts grey, the board inside it, a 1920x1080 crop."""
    m = tunnel.build()
    board = tunnel.soup(seed=7, density=0.25)
    _, stored, _ = tunnel.start(m)
    export(m, tunnel.start_given(board), tmp_path / "tunnel.json", crop_field=tunnel.CROP, first=tunnel.FIRST,
           stored=stored, name="tunnel")
    frames = m.stream(m.initial(tunnel.start_given(board)), 120, tunnel.CROP, first=tunnel.FIRST, stored=stored)
    board.astype(np.uint8).tofile(tmp_path / "board.bin")
    subprocess.run(["node", str(ROOT / "web" / "test_parity.mjs"), str(tmp_path / "tunnel.json"),
                    str(tmp_path / "board.bin"), "120", str(tmp_path / "js")], check=True)
    assert (tmp_path / "js.264").read_bytes() == b"".join(frames)
    assert (tmp_path / "js.mp4").read_bytes() == mp4.mux(frames, 1920, 1080, 60)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_browser_writer_matches_python_primes(tmp_path):
    """The same for the CPU: 16 x 64 boards, starting values shipped in the JSON, the display picture given."""
    m = primes.build()
    given = primes_given(m)
    export(m, given, tmp_path / "primes.json", crop_field=primes.CROP, name="primes", period=primes.PERIOD,
           ship_given=True)
    frames = m.stream(m.initial(given), 120, primes.CROP)
    subprocess.run(["node", str(ROOT / "web" / "test_parity.mjs"), str(tmp_path / "primes.json"), "-", "120",
                    str(tmp_path / "js")], check=True)
    assert (tmp_path / "js.264").read_bytes() == b"".join(frames)
    assert (tmp_path / "js.mp4").read_bytes() == mp4.mux(frames, primes.PIC_W, primes.PIC_H, 60)


def test_program_frames_do_not_depend_on_the_start(tmp_path):
    """The central claim: the start-up frames carry the pattern, and the program frames after them are the same
    16 frames whatever the pattern, repeating. So the state cannot be in them; it is in the decoded pictures."""
    m = life.build()
    a, b = life.soup(seed=1, density=0.2), life.soup(seed=2, density=0.5)
    fa, fb = (m.stream(m.initial(life.given(x)), 60, "D") for x in (a, b))
    start = m.first_program_frame
    assert fa[:start] != fb[:start]
    assert fa[start:] == fb[start:]
    assert len(set(fa[start:start + 16])) == 16 and fa[start:start + 16] == fa[start + 16:start + 32]
    pa, pb = (export(m, life.given(x), tmp_path / f"{n}.json")["programFrames"] for n, x in (("a", a), ("b", b)))
    assert pa == pb
