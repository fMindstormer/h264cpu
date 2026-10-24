"""Fractional-sample interpolation exactly as H.264 defines it (8.4.2.2), for 8-bit 4:2:0 frames.

Luma motion vectors are in quarter samples. Half-sample values come from the 6-tap filter
(1, -5, 20, 20, -5, 1), rounded and clipped; the centre half-sample j filters the unrounded vertical sums
again; quarter samples average two neighbouring integer or half samples, rounding up. Chroma vectors are
in eighth samples and interpolate bilinearly. A reference position outside the picture is clamped to its
edge, sample by sample, before filtering.

LumaRef and ChromaRef precompute the planes of one reference picture once; luma() and chroma() then look
up any array of absolute fractional positions: 4 * x + mvx for luma, 8 * x + mvx for chroma (x in that
plane's samples, the vector in quarter luma samples, which are eighth chroma samples in 4:2:0).
"""
from __future__ import annotations

import numpy as np

TAPS = (1, -5, 20, 20, -5, 1)
PAD = 16            # every position is clamped to within 8 samples of the picture, where padding is exact


def _taps(a, axis):
    """sum_k TAPS[k] * a[i + k - 2] along axis, valid from index 2 to n - 4 (zero elsewhere)."""
    n = a.shape[axis]
    out = np.zeros_like(a)
    acc = sum(t * np.take(a, np.arange(k, n - 5 + k), axis=axis) for k, t in enumerate(TAPS))
    idx = [slice(None)] * a.ndim
    idx[axis] = slice(2, n - 3)
    out[tuple(idx)] = acc
    return out


class LumaRef:
    def __init__(self, plane):
        self.h, self.w = plane.shape
        g = np.pad(plane.astype(np.int32), PAD, mode="edge")
        h1 = _taps(g, 0)                                  # vertical sums, unrounded
        self.S = np.stack([g,                                          # integer samples
                           np.clip((_taps(g, 1) + 16) >> 5, 0, 255),   # b: half sample to the right
                           np.clip((h1 + 16) >> 5, 0, 255),            # h: half sample below
                           np.clip((_taps(h1, 1) + 512) >> 10, 0, 255)])  # j: half sample right and below
        self.G, self.b, self.hh, self.j = self.S


def _index(ref, xi, yi):
    return (np.clip(yi, -8, ref.h + 8) + PAD, np.clip(xi, -8, ref.w + 8) + PAD)


def luma(ref: LumaRef, xq, yq):
    """Predicted luma samples at absolute quarter-sample positions xq, yq (int arrays of one shape)."""
    xq, yq = np.asarray(xq), np.asarray(yq)
    Y, X = _index(ref, xq >> 2, yq >> 2)
    fx, fy = xq & 3, yq & 3
    G, H, M = ref.G[Y, X], ref.G[Y, X + 1], ref.G[Y + 1, X]
    b, s = ref.b[Y, X], ref.b[Y + 1, X]
    h, m = ref.hh[Y, X], ref.hh[Y, X + 1]
    j = ref.j[Y, X]

    def avg(p, q):
        return (p + q + 1) >> 1

    table = {(0, 0): G, (1, 0): avg(G, b), (2, 0): b, (3, 0): avg(H, b),
             (0, 1): avg(G, h), (1, 1): avg(b, h), (2, 1): avg(b, j), (3, 1): avg(b, m),
             (0, 2): h, (1, 2): avg(h, j), (2, 2): j, (3, 2): avg(j, m),
             (0, 3): avg(M, h), (1, 3): avg(h, s), (2, 3): avg(j, s), (3, 3): avg(m, s)}
    out = np.empty(G.shape, np.int32)
    for (px, py), v in table.items():
        sel = (fx == px) & (fy == py)
        out[sel] = v[sel]
    return out


class ChromaRef:
    def __init__(self, plane):
        self.h, self.w = plane.shape
        self.G = np.pad(plane.astype(np.int32), PAD, mode="edge")


def chroma(ref: ChromaRef, xe, ye):
    """Predicted chroma samples at absolute eighth-sample positions xe, ye."""
    xe, ye = np.asarray(xe), np.asarray(ye)
    Y, X = _index(ref, xe >> 3, ye >> 3)
    fx, fy = xe & 7, ye & 7
    g = ref.G
    return ((8 - fx) * (8 - fy) * g[Y, X] + fx * (8 - fy) * g[Y, X + 1]
            + (8 - fx) * fy * g[Y + 1, X] + fx * fy * g[Y + 1, X + 1] + 32) >> 6


# luma(): which two of the planes G, b, h, j (at offsets dy, dx) are averaged for each fractional position
_TERMS = {(0, 0): ((0, 0, 0), (0, 0, 0)), (1, 0): ((0, 0, 0), (1, 0, 0)), (2, 0): ((1, 0, 0), (1, 0, 0)),
          (3, 0): ((0, 0, 1), (1, 0, 0)), (0, 1): ((0, 0, 0), (2, 0, 0)), (1, 1): ((1, 0, 0), (2, 0, 0)),
          (2, 1): ((1, 0, 0), (3, 0, 0)), (3, 1): ((1, 0, 0), (2, 0, 1)), (0, 2): ((2, 0, 0), (2, 0, 0)),
          (1, 2): ((2, 0, 0), (3, 0, 0)), (2, 2): ((3, 0, 0), (3, 0, 0)), (3, 2): ((3, 0, 0), (2, 0, 1)),
          (0, 3): ((0, 1, 0), (2, 0, 0)), (1, 3): ((2, 0, 0), (1, 1, 0)), (2, 3): ((3, 0, 0), (1, 1, 0)),
          (3, 3): ((2, 0, 1), (1, 1, 0))}


class LumaPlan:
    """luma() for fixed positions in references of a fixed size, precomputed: two lookups per sample."""

    def __init__(self, h, w, xq, yq):
        xq, yq = np.asarray(xq), np.asarray(yq)
        Y = np.clip(yq >> 2, -8, h + 8) + PAD
        X = np.clip(xq >> 2, -8, w + 8) + PAD
        fx, fy = xq & 3, yq & 3
        Hp, Wp = h + 2 * PAD, w + 2 * PAD
        self.shape, self.i1, self.i2 = (h, w), np.empty(xq.shape, np.int64), np.empty(xq.shape, np.int64)
        for (px, py), terms in _TERMS.items():
            sel = (fx == px) & (fy == py)
            for out, (pl, dy, dx) in zip((self.i1, self.i2), terms):
                out[sel] = (pl * Hp + Y[sel] + dy) * Wp + X[sel] + dx

    def __call__(self, ref: LumaRef):
        assert (ref.h, ref.w) == self.shape
        S = ref.S.reshape(-1)
        return (S[self.i1] + S[self.i2] + 1) >> 1


class ChromaPlan:
    """chroma() for fixed positions in references of a fixed size, precomputed."""

    def __init__(self, h, w, xe, ye):
        xe, ye = np.asarray(xe), np.asarray(ye)
        Y = np.clip(ye >> 3, -8, h + 8) + PAD
        X = np.clip(xe >> 3, -8, w + 8) + PAD
        fx, fy = xe & 7, ye & 7
        Wp = w + 2 * PAD
        self.shape = (h, w)
        self.idx = [(Y + dy) * Wp + X + dx for dy in (0, 1) for dx in (0, 1)]
        self.wts = [(8 - fx) * (8 - fy), fx * (8 - fy), (8 - fx) * fy, fx * fy]

    def __call__(self, ref: ChromaRef):
        assert (ref.h, ref.w) == self.shape
        g = ref.G.reshape(-1)
        return (sum(w * g[i] for w, i in zip(self.wts, self.idx)) + 32) >> 6


def block(refs, x0, y0, w, h, mv):
    """The (Y, Cb, Cr) prediction of a w x h luma block at (x0, y0) of a picture with planes refs
    (LumaRef, ChromaRef, ChromaRef) for motion vector mv (quarter luma samples)."""
    yy, xx = np.mgrid[y0:y0 + h, x0:x0 + w]
    cy, cx = np.mgrid[y0 // 2:(y0 + h) // 2, x0 // 2:(x0 + w) // 2]
    return (luma(refs[0], 4 * xx + mv[0], 4 * yy + mv[1]),
            chroma(refs[1], 8 * cx + mv[0], 8 * cy + mv[1]),
            chroma(refs[2], 8 * cx + mv[0], 8 * cy + mv[1]))


def refs_of(frame):
    y, cb, cr = frame
    return LumaRef(y), ChromaRef(cb), ChromaRef(cr)
