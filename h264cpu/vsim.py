"""The arithmetic of H.264 explicit weighted prediction, exactly, for 8-bit samples.

One output sample of a B-slice block that is bi-predicted with explicit weights is

    Clip1(((w0 * p0 + w1 * p1 + 2**L) >> (L + 1)) + ((o0 + o1 + 1) >> 1))        (H.264 eq. 8-301)

where p0 and p1 are samples of two reference pictures at integer motion offsets, and with one list

    Clip1(((w * p + 2**(L - 1)) >> L) + o)  if L >= 1,  else  Clip1(w * p + o)       (eq. 8-299, 8-300)

Weights are -128..127, offsets -128..127, L (log2 of the weight denominator) 0..7 and shared by a
slice, and for bi-prediction -128 <= w0 + w1 <= (127 if L == 7 else 128). Shifts of signed values are
arithmetic, as in the standard. Integer motion vectors copy samples without interpolation.
"""
from __future__ import annotations

import numpy as np


class Illegal(ValueError):
    pass


def _check_w(w):
    if not -128 <= w <= 127:
        raise Illegal(f"weight {w} outside -128..127")


def _check_o(o):
    if not -128 <= o <= 127:
        raise Illegal(f"offset {o} outside -128..127")


def bi(a, b, w0, w1, L, o):
    """Bi-prediction with explicit weights; a, b are already-shifted int arrays. o is the combined offset."""
    if not 0 <= L <= 7:
        raise Illegal(f"log2 denominator {L}")
    _check_w(w0), _check_w(w1), _check_o(o)
    if not -128 <= w0 + w1 <= (127 if L == 7 else 128):
        raise Illegal(f"w0 + w1 = {w0 + w1}")
    v = ((w0 * a.astype(np.int32) + w1 * b.astype(np.int32) + (1 << L)) >> (L + 1)) + o
    return np.clip(v, 0, 255).astype(np.int32)


def uni(a, w, L, o):
    if not 0 <= L <= 7:
        raise Illegal(f"log2 denominator {L}")
    _check_w(w), _check_o(o)
    a = a.astype(np.int32)
    v = (((w * a + (1 << (L - 1))) >> L) + o) if L >= 1 else (w * a + o)
    return np.clip(v, 0, 255).astype(np.int32)


def shift(x, dy, dx, mode="wrap"):
    """The samples a motion vector (dx, dy) fetches: out[y, x] = ref[y + dy, x + dx]."""
    if dy == 0 and dx == 0:
        return x
    if mode == "wrap":
        return np.roll(x, (-dy, -dx), axis=(0, 1))
    h, w = x.shape[-2:]
    yy = np.clip(np.arange(h) + dy, 0, h - 1)
    xx = np.clip(np.arange(w) + dx, 0, w - 1)
    return x[..., yy[:, None], xx[None, :]]
