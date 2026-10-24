"""Write a program's video (raw H.264 stream and MP4) and check every frame against the simulation."""
from __future__ import annotations

import os
import time

from . import mp4
from .machine import check_level_sizes
from .verify import verify


def write(program, seconds=30, out="out", check=True, fps=60, log=print, hwaccel=None):
    t0 = time.time()
    m = program.build()
    init, stored, reference = program.start(m)
    crop = getattr(program, "CROP", "D")
    n = seconds * fps
    frames = m.stream(init, n, crop, fps=fps, stored=stored, first=getattr(program, "FIRST", None))
    ext = m.mv_extent()
    log(f"{program.NAME}: {len(m.fields)} fields in a {m.width_mbs * 16}x{m.height_mbs * 16} frame, "
        f"{len(m.instructions())} slices, motion vectors x {ext[0]}..{ext[1]}, y {ext[2]}..{ext[3]}")
    check_level_sizes(m, frames, fps)
    os.makedirs(out, exist_ok=True)
    raw = os.path.join(out, f"{program.NAME}.264")
    with open(raw, "wb") as fh:
        fh.write(b"".join(frames))
    with open(os.path.join(out, f"{program.NAME}.mp4"), "wb") as fh:
        fh.write(mp4.mux(frames, *m.fields[crop].shown_px, fps))
    c = len(m.pcm_chunks)
    log(f"wrote {n} frames ({seconds} s), {sum(map(len, frames)) / 1e6:.1f} MB: frame 0 {len(frames[0]) / 1e3:.1f} KB, "
        f"stored state {sum(map(len, frames[1:c + 1])) / 1e6:.2f} MB in {c} frame(s), "
        f"{len(frames[-1]) / 1e3:.1f} KB per program frame from frame {m.first_program_frame} "
        f"({time.time() - t0:.0f} s)")
    result = None
    if check:
        args = ("-hwaccel", hwaccel) if hwaccel else ()
        result = verify(m, init, raw, n, crop_field=crop, reference=reference, log=log, args=args)
        by = f"ffmpeg ({hwaccel})" if hwaccel else "ffmpeg"
        log(f"checked: {result['identical']} of {result['frames']} frames decoded by {by} are identical to the "
            f"simulation in every sample" + (f"; {result['generations']} generations equal the reference"
                                              if reference else "") + f" ({result['seconds']:.0f} s)")
    return m, frames, result
