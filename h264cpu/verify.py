"""Check a written stream against the simulation: every frame, every sample, every plane, uncropped."""
from __future__ import annotations

import subprocess
import time

import numpy as np


def decode_frames(path, width, height, args=()):
    """Yield (y, cb, cr) planes of every frame ffmpeg decodes from path, ignoring the crop, unconverted.
    args go before the input, e.g. ("-hwaccel", "videotoolbox") to decode on Apple's hardware decoder."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", *args, "-flags2", "+ignorecrop", "-i", str(path),
                          "-f", "rawvideo", "-pix_fmt", "yuvj420p", "-"], stdout=subprocess.PIPE)
    fsize = width * height * 3 // 2
    try:
        while True:
            raw = p.stdout.read(fsize)
            if len(raw) < fsize:
                break
            a = np.frombuffer(raw, np.uint8)
            yield (a[:width * height].reshape(height, width),
                   a[width * height:width * height * 5 // 4].reshape(height // 2, width // 2),
                   a[width * height * 5 // 4:].reshape(height // 2, width // 2))
    finally:
        p.stdout.close()
        p.wait()


def verify(m, init, path, n, crop_field="D", reference=None, log=print, args=()):
    """Compare every decoded frame with the simulation.

    reference: optional (period, state0, step, read): at the last frame of each period after the program
    starts, read(m, y_plane) must equal the reference state advanced by step(). Returns a summary dict."""
    Wp, Hp = m.width_mbs * 16, m.height_mbs * 16
    warm, start = m.max_delay(), m.first_program_frame
    history = [init] * (warm + 1)
    mism, gens, t0, f = 0, 0, time.time(), -1
    state = reference[1].copy() if reference else None
    for f, planes in enumerate(decode_frames(path, Wp, Hp, args)):
        if f >= n:
            break
        if f >= start:
            history.append(m.step(history))
            del history[0]
        want = m.render(history[-1]) if f >= start else m.warmup_frame(init, crop_field, f)
        bad = sum(int((a != b).sum()) for a, b in zip(planes, want))
        if bad:
            mism += 1
            if mism <= 3:
                log(f"frame {f}: {bad} samples differ from the simulation")
        if reference and f >= start and (f - start + 1) % reference[0] == 0:
            state = reference[2](state)
            gens += 1
            if not np.array_equal(reference[3](m, planes[0]), state):
                raise AssertionError(f"frame {f}: the board differs from the reference at generation {gens}")
    frames = f + 1
    assert frames == n, f"the decoder produced {frames} frames, expected {n}"
    return {"frames": frames, "identical": frames - mism, "generations": gens, "seconds": time.time() - t0}
