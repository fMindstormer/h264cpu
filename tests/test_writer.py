"""The writer, macroblock by macroblock: ffmpeg must decode each test stream to exactly the expected samples."""
import shutil

import numpy as np
import pytest

from h264cpu import writer as h264w
from h264cpu.verify import decode_frames
from h264cpu.writer import Entry

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def decode(path, W, H):
    # ffmpeg's C decoder, the reference: its arm64 NEON code (seen in ffmpeg 9.0.2) gets some bi-predicted
    # samples wrong for large negative weights, which these random streams use and the programs never do.
    return [tuple(p.copy() for p in f) for f in decode_frames(path, W, H, ("-cpuflags", "0"))]


def test_grey_idr_and_pcm_p_frames(tmp_path):
    """PCM blocks in awkward places: corners, row ends, runs across rows; grey and skipped elsewhere."""
    W, H = 9, 6
    rng = np.random.default_rng(1)

    def blocks():
        return (rng.integers(0, 256, (16, 16), np.uint8), rng.integers(0, 256, (8, 8), np.uint8),
                rng.integers(0, 256, (8, 8), np.uint8))

    def paint(frame, pcm):
        y, cb, cr = (p.copy() for p in frame)
        for a, (by, bcb, bcr) in pcm.items():
            mx, my = a % W, a // W
            y[my * 16:my * 16 + 16, mx * 16:mx * 16 + 16] = by
            cb[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8] = bcb
            cr[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8] = bcr
        return y, cb, cr

    pcm0 = {a: blocks() for a in [0, 1, 8, 9, 13, 14, 15, 22, 23, 24, 30, 40, 41, 53]}
    pcm1 = {a: blocks() for a in [2, 3, 17, 26, 27, 35, 44, 52, 53]}
    grey = (np.full((H * 16, W * 16), 128, np.uint8), np.full((H * 8, W * 8), 128, np.uint8),
            np.full((H * 8, W * 8), 128, np.uint8))
    want = [paint(grey, pcm0)]
    want += [paint(want[0], pcm1)] * 2
    data = (h264w.sps(W, H, (0, 0, 0, 0), 1) + h264w.pps() + h264w.idr_mixed(pcm0, W, H)
            + h264w.p_pcm(1, pcm1, W * H) + h264w.p_copy(2, W * H))
    (tmp_path / "t.264").write_bytes(data)
    got = decode(tmp_path / "t.264", W * 16, H * 16)
    assert len(got) == 3
    for g, w in zip(got, want):
        for a, b in zip(g, w):
            assert np.array_equal(a, b)


def test_random_weighted_b_frames(tmp_path):
    """Random weights, offsets, references and motion over 4 random reference pictures, in two slices with
    different weight denominators; skipped macroblocks wherever direct prediction happens to match."""
    rng = np.random.default_rng(1)
    W, H = 96, 64
    WM, HM = W // 16, H // 16

    def rand_frame():
        return (rng.integers(0, 256, (H, W), dtype=np.uint8), rng.integers(0, 256, (H // 2, W // 2), dtype=np.uint8),
                rng.integers(0, 256, (H // 2, W // 2), dtype=np.uint8))

    refs = [rand_frame() for _ in range(4)]
    stream = h264w.sps(WM, HM, (0, 0, 0, 0), 8) + h264w.pps() + h264w.idr_pcm(*refs[0])
    for i in range(1, 4):
        stream += h264w.i_pcm(i, *refs[i])
    history = list(refs)

    def rand_entries(n):
        return [Entry(int(rng.integers(1, 5)), [(int(rng.integers(-60, 61)), int(rng.integers(-128, 128)))
                                                for _ in range(3)]) for _ in range(n)]

    def predict(e, mv, mx, my, plane):
        ref = history[-e.delay][plane]
        if plane == 0:
            y0, x0, s = my * 16 + mv[1], mx * 16 + mv[0], 16
        else:
            y0, x0, s = my * 8 + mv[1] // 2, mx * 8 + mv[0] // 2, 8
        return ref[y0:y0 + s, x0:x0 + s].astype(np.int32)

    for fnum in range(4, 8):
        slices = [(0, 0, 0), (WM * 2, 5, 3)]
        out = [np.zeros((H, W), np.uint8), np.zeros((H // 2, W // 2), np.uint8), np.zeros((H // 2, W // 2), np.uint8)]
        for si, (first, L, Lc) in enumerate(slices):
            last = slices[si + 1][0] if si + 1 < len(slices) else WM * HM
            l0, l1 = rand_entries(5), rand_entries(4)
            mbs = []
            for addr in range(first, last):
                mx, my = addr % WM, addr // WM
                while True:
                    pred = int(rng.integers(1, 4))
                    r0, r1 = int(rng.integers(0, len(l0))), int(rng.integers(0, len(l1)))
                    lims = [(L, l0[r0].wo[p][0] + l1[r1].wo[p][0]) for p in range(1)] + \
                           [(Lc, l0[r0].wo[p][0] + l1[r1].wo[p][0]) for p in (1, 2)]
                    if pred != 3 or all(-128 <= s <= (127 if ll == 7 else 128) for ll, s in lims):
                        break

                def rmv():
                    return (2 * int(rng.integers(-mx * 8, (WM - 1 - mx) * 8 + 1)),
                            2 * int(rng.integers(-my * 8, (HM - 1 - my) * 8 + 1)))

                mv0, mv1 = rmv(), rmv()
                mbs.append((pred, r0, mv0, r1, mv1))
                for plane in range(3):
                    LL = L if plane == 0 else Lc
                    if pred == 3:
                        a, b = predict(l0[r0], mv0, mx, my, plane), predict(l1[r1], mv1, mx, my, plane)
                        o = (l0[r0].wo[plane][1] + l1[r1].wo[plane][1] + 1) >> 1
                        v = np.clip(((l0[r0].wo[plane][0] * a + l1[r1].wo[plane][0] * b + (1 << LL)) >> (LL + 1)) + o, 0, 255)
                    else:
                        e, mv = (l0[r0], mv0) if pred == 1 else (l1[r1], mv1)
                        a = predict(e, mv, mx, my, plane)
                        w, o = e.wo[plane]
                        v = np.clip((((w * a + (1 << (LL - 1))) >> LL) + o) if LL >= 1 else (w * a + o), 0, 255)
                    s = 16 if plane == 0 else 8
                    out[plane][my * s:my * s + s, mx * s:mx * s + s] = v
            rbsp, _ = h264w.b_slice(fnum, first, L, Lc, l0, l1, mbs, WM)
            stream += h264w.nal(2, 1, rbsp)
        history.append(tuple(out))
    (tmp_path / "b.264").write_bytes(stream)
    frames = decode(tmp_path / "b.264", W, H)
    assert len(frames) == 8
    for f, h in zip(frames, history):
        for a, b in zip(f, h):
            assert np.array_equal(a, b)


def test_random_quarter_sample_motion_and_8x8_quadrants(tmp_path):
    """Quarter-sample vectors at every fractional position, some reaching past the picture's edges, in
    16x16 macroblocks and in B_8x8 macroblocks whose quadrants each predict from list 0, list 1 or both;
    ffmpeg must decode each frame to exactly what interp.py and the weighted-prediction formulas give."""
    from h264cpu import interp
    from h264cpu.writer import Quads

    rng = np.random.default_rng(7)
    W, H = 128, 80
    WM, HM = W // 16, H // 16

    def rand_frame():
        return (rng.integers(0, 256, (H, W), dtype=np.uint8), rng.integers(0, 256, (H // 2, W // 2), dtype=np.uint8),
                rng.integers(0, 256, (H // 2, W // 2), dtype=np.uint8))

    refs = [rand_frame() for _ in range(4)]
    stream = h264w.sps(WM, HM, (0, 0, 0, 0), 8) + h264w.pps() + h264w.idr_pcm(*refs[0])
    for i in range(1, 4):
        stream += h264w.i_pcm(i, *refs[i])
    history = list(refs)

    def rand_entries(n):
        return [Entry(int(rng.integers(1, 5)), [(int(rng.integers(-70, 71)), int(rng.integers(-128, 128)))
                                                for _ in range(3)]) for _ in range(n)]

    def rand_mv(x0, y0, w, h):
        # up to 24 samples past each edge, any quarter position
        return (int(rng.integers(-(x0 + 24) * 4, (W - x0 - w + 24) * 4 + 1)),
                int(rng.integers(-(y0 + 24) * 4, (H - y0 - h + 24) * 4 + 1)))

    phases = set()
    for fnum in range(4, 10):
        prepared = [interp.refs_of(f) for f in history]
        slices = [(0, int(rng.integers(0, 8)), int(rng.integers(0, 8))),
                  (WM * 2 + 3, int(rng.integers(0, 8)), int(rng.integers(0, 8)))]
        out = [np.zeros((H, W), np.uint8), np.zeros((H // 2, W // 2), np.uint8), np.zeros((H // 2, W // 2), np.uint8)]
        for si, (first, L, Lc) in enumerate(slices):
            last = slices[si + 1][0] if si + 1 < len(slices) else WM * HM
            l0, l1 = rand_entries(int(rng.integers(1, 6))), rand_entries(int(rng.integers(1, 5)))

            def part(x0, y0, w, h):
                while True:
                    pred = int(rng.integers(1, 4))
                    r0, r1 = int(rng.integers(0, len(l0))), int(rng.integers(0, len(l1)))
                    ok = all(-128 <= l0[r0].wo[p][0] + l1[r1].wo[p][0] <= (127 if (L if p == 0 else Lc) == 7 else 128)
                             for p in range(3))
                    if pred != 3 or ok:
                        return (pred, r0, rand_mv(x0, y0, w, h), r1, rand_mv(x0, y0, w, h))

            mbs = []
            for addr in range(first, last):
                mx, my = addr % WM, addr // WM
                kind = rng.random()
                if kind < 0.3:
                    p = part(mx * 16, my * 16, 16, 16)
                    parts = [p] * 4
                    mbs.append(Quads(parts))
                elif kind < 0.4 and mbs:
                    parts = list(mbs[-1].parts)              # same motion as the left neighbour: often skipped
                    mbs.append(Quads(parts))
                else:
                    parts = [part(mx * 16 + 8 * (k % 2), my * 16 + 8 * (k // 2), 8, 8) for k in range(4)]
                    mbs.append(Quads(parts))
                for k, (pred, r0, mv0, r1, mv1) in enumerate(parts):
                    x0, y0 = mx * 16 + 8 * (k % 2), my * 16 + 8 * (k // 2)
                    for mv in ((mv0,) if pred == 1 else (mv1,) if pred == 2 else (mv0, mv1)):
                        phases.add((mv[0] & 3, mv[1] & 3))
                    p0 = interp.block(prepared[-l0[r0].delay], x0, y0, 8, 8, mv0) if pred & 1 else None
                    p1 = interp.block(prepared[-l1[r1].delay], x0, y0, 8, 8, mv1) if pred & 2 else None
                    for plane in range(3):
                        LL = L if plane == 0 else Lc
                        if pred == 3:
                            (w0, o0), (w1, o1) = l0[r0].wo[plane], l1[r1].wo[plane]
                            v = np.clip(((w0 * p0[plane] + w1 * p1[plane] + (1 << LL)) >> (LL + 1)) + ((o0 + o1 + 1) >> 1), 0, 255)
                        else:
                            a = p0[plane] if pred == 1 else p1[plane]
                            w, o = (l0[r0] if pred == 1 else l1[r1]).wo[plane]
                            v = np.clip((((w * a + (1 << (LL - 1))) >> LL) + o) if LL >= 1 else (w * a + o), 0, 255)
                        if plane == 0:
                            out[0][y0:y0 + 8, x0:x0 + 8] = v
                        else:
                            out[plane][y0 // 2:y0 // 2 + 4, x0 // 2:x0 // 2 + 4] = v
            rbsp, _ = h264w.b_slice(fnum, first, L, Lc, l0, l1, mbs, WM)
            stream += h264w.nal(2, 1, rbsp)
        history.append(tuple(out))
    assert len(phases) == 16
    (tmp_path / "q.264").write_bytes(stream)
    frames = decode(tmp_path / "q.264", W, H)
    assert len(frames) == len(history)
    for i, (f, h) in enumerate(zip(frames, history)):
        for p, (a, b) in enumerate(zip(f, h)):
            assert np.array_equal(a, b), f"frame {i} plane {p}: {int((a != b).sum())} samples differ"
