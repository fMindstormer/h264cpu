"""Every program, 3 seconds: every decoded frame equals the simulation, the board equals the reference
automaton every generation, and the MP4 decodes to the same frames as the raw stream."""
import hashlib
import shutil

import pytest

from h264cpu.build import write
from h264cpu.programs import PROGRAMS
from h264cpu.verify import decode_frames

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def digests(path, w, h):
    return [hashlib.md5(b"".join(p.tobytes() for p in f)).hexdigest() for f in decode_frames(path, w, h)]


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_program_decodes_exactly(name, tmp_path):
    m, frames, r = write(PROGRAMS[name], seconds=3, out=str(tmp_path), check=True, log=lambda *a: None)
    assert r["frames"] == 180 and r["identical"] == 180
    if name != "turing":
        assert r["generations"] >= 15
    w, h = m.width_mbs * 16, m.height_mbs * 16
    assert digests(tmp_path / f"{name}.mp4", w, h) == digests(tmp_path / f"{name}.264", w, h)
