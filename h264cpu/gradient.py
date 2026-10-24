"""A colour gradient map as decoder ops: each plane is a piecewise-linear function of a field, built
from four ramps (one op each), two weighted pair sums and one exact sum. The ops are the same in all
three planes; only the weights differ, which explicit weighted prediction allows per plane."""
from __future__ import annotations

import numpy as np

from . import vsim

STOPS = [0, 64, 128, 192, 255]


def rgb_to_ycbcr(c):
    r, g, b = c
    return (0.299 * r + 0.587 * g + 0.114 * b, 128 - 0.168736 * r - 0.331264 * g + 0.5 * b,
            128 + 0.5 * r - 0.418688 * g - 0.081312 * b)


def ramp_params(t):
    """clip(4 (x - t)): bi(x, const255, 8, w1, 0, o)."""
    best = None
    for w1 in range(-128, 128):
        if not -128 <= 8 + w1 <= 128:
            continue
        o = round(-4 * t - w1 * 127.5)
        if -128 <= o <= 127:
            err = abs(w1 * 127.5 + o + 4 * t)
            if best is None or err < best[0]:
                best = (err, w1, o)
    return 8, best[1], 0, best[2]


def plane_weights(values, L=6):
    """Pair-sum weights for one plane: f = y0 + sum d_i ramp_i / 255, d_i = value steps."""
    d = np.diff(values)
    # pair A: y0 + d0 g0 + d1 g1 ; pair B: 127 + d2 g2 + d3 g3 ; weights are d * 2^(L+1) / 255
    k = 2 ** (L + 1) / 255
    wa = [int(round(d[0] * k)), int(round(d[1] * k))]
    wb = [int(round(d[2] * k)), int(round(d[3] * k))]
    return wa, wb, int(round(values[0])), L


def apply(x, palette):
    """x: field (int array). palette: 5 RGB stops at STOPS. Returns Y, Cb, Cr planes."""
    k = np.full_like(x, 255)
    ramps = [vsim.bi(x, k, *ramp_params(t)) for t in STOPS[:4]]
    out = []
    for plane in range(3):
        values = [rgb_to_ycbcr(c)[plane] for c in palette]
        wa, wb, y0, L = plane_weights(values)
        oa = max(-128, min(127, y0))
        a = vsim.bi(ramps[0], ramps[1], wa[0], wa[1], L, oa)
        b = vsim.bi(ramps[2], ramps[3], wb[0], wb[1], L, 127)
        out.append(vsim.bi(a, b, 2, 2, 0, -127 + (y0 - oa)))
    return out
