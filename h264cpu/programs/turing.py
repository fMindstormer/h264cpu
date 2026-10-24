"""Multi-scale Turing patterns, after Jonathan McCabe, on a 104x104 torus: 70 fields in a 4096x896 frame.

The state S is blurred into a pyramid B1..B5 (pairs of averages, each level twice as wide). At each
scale k the activator Bk is compared with the inhibitor B(k+1); the scale whose difference is smallest
moves the cell one step towards its activator, and a slow pull keeps S away from the clipping edges.
The display is B1 through a colour gradient map. Two weight precisions are used: L = 0 (exact integer
logic) and L = 6 (averages, the decay and the colour pairs). The pattern takes one step every frame.
"""
from __future__ import annotations

import numpy as np

from .. import gradient as gradient_map
from ..layout import anneal
from ..machine import Machine

NAME = "turing"
N = 104                     # board cells per side
C = 127                     # the zero of signed quantities
PALETTE = [(8, 12, 38), (22, 74, 122), (52, 170, 160), (244, 196, 104), (252, 246, 228)]
PARAMS = dict(first=1, K=4, steps=(1, 2, 2, 3), gain=4)
SEED = 3
# stored as raw samples: the random board, the constant and the display chain (so the first frames show
# the board in colour); every other field starts grey, and grey inputs make the step zero until the
# pipeline has filled
STORED = {"S", "K", "T1", "B1", "ramp0", "ramp1", "ramp2", "ramp3", "pa", "pb"}
TILE, HTILE = 2 * N, 2 * N + 32           # a field's side in pixels, without and with an 8-cell halo
WIDTH_MBS, HEIGHT_MBS = 256, 56           # a 4096x896 frame


def program(m, first=2, K=3, steps=(2, 2, 3), gain=4):
    """Add the fields and ops of the Turing program to machine m. Returns the display field name."""
    top = first + K                                   # deepest blur level needed (inhibitor of the last scale)
    assert 1 << max(0, top - 2) <= 8, "blur offsets must fit an 8-cell halo"
    m.field("K")
    m.op("K", [("K", 1, 0, 0)], (1, 0))               # constant 255
    m.field("S", halo=8)
    # ---- blur pyramid at L = 6: (64a + 64b + 64) >> 7 is exactly (a + b + 1) >> 1
    prev = "S"
    offs = {1: (0, 1), 2: (-1, 0)}
    avg = (64, 64, 0)
    for k in range(1, top + 1):
        a, b = offs[k] if k in offs else (-(1 << (k - 2)), 1 << (k - 2))
        m.field(f"T{k}", halo=8)
        m.field(f"B{k}", halo=8 if k < top else 0)
        if k % 2:      # alternate which direction goes first, so neither lags behind
            m.op(f"T{k}", [(prev, 1, 0, a), (prev, 1, 0, b)], avg, L=(6, 6))
            m.op(f"B{k}", [(f"T{k}", 1, a, 0), (f"T{k}", 1, b, 0)], avg, L=(6, 6))
        else:
            m.op(f"T{k}", [(prev, 1, a, 0), (prev, 1, b, 0)], avg, L=(6, 6))
            m.op(f"B{k}", [(f"T{k}", 1, 0, a), (f"T{k}", 1, 0, b)], avg, L=(6, 6))
        prev = f"B{k}"
    # ---- per scale: difference, its sign and size
    scales = list(range(first, first + K))
    for k, s in zip(scales, steps):
        for n in ("dif", "pos", "neg", "var", "nup", "ndn"):
            m.field(f"{n}{k}")
        m.op(f"dif{k}", [(f"B{k}", 1, 0, 0), (f"B{k + 1}", 1, 0, 0)], (2 * gain, -2 * gain, C))   # C + g(act - inh)
        m.op(f"pos{k}", [(f"dif{k}", 1, 0, 0)], (1, -C))                         # positive part
        m.op(f"neg{k}", [(f"dif{k}", 1, 0, 0)], (-1, C))                         # negative part
        m.op(f"var{k}", [(f"pos{k}", 1, 0, 0), (f"neg{k}", 1, 0, 0)], (2, 2, 0))  # |dif - C|
        m.op(f"nup{k}", [(f"pos{k}", 1, 0, 0)], (-s, s))                         # s where not positive
        m.op(f"ndn{k}", [(f"neg{k}", 1, 0, 0)], (-s, s))                         # s where not negative
    # ---- minimum variation over the scales: min(a, b) = a - relu(a - b), two frames per level
    names, level = [f"var{k}" for k in scales], 0
    while len(names) > 1:
        nxt = []
        for i in range(0, len(names) - 1, 2):
            a, b, d, mn = names[i], names[i + 1], f"md{level}_{i}", f"mn{level}_{i}"
            m.field(d), m.field(mn)
            m.op(d, [(a, 1, 0, 0), (b, 1, 0, 0)], (2, -2, 0))
            m.op(mn, [(a, 2, 0, 0), (d, 1, 0, 0)], (2, -2, 0))
            nxt.append(mn)
        if len(names) % 2:                            # odd one out: two copies keep it in step
            c1, c2 = f"mc{level}", f"mcc{level}"
            m.field(c1), m.field(c2)
            m.op(c1, [(names[-1], 1, 0, 0)], (1, 0))
            m.op(c2, [(c1, 1, 0, 0)], (1, 0))
            nxt.append(c2)
        names, level = nxt, level + 1
    mn, lag = names[0], 2 * level
    # ---- the scale with the smallest variation moves the cell by its step, towards its activator
    terms = []
    for k, s in zip(scales, steps):
        for n in ("mask", "up", "dn", "st"):
            m.field(f"{n}{k}")
        # s where this scale has the smallest variation: s - s * (var - min), var read from the frame the
        # minimum was computed from
        m.op(f"mask{k}", [(f"var{k}", lag + 1, 0, 0), (mn, 1, 0, 0)], (-2 * s, 2 * s, s))
        m.op(f"up{k}", [(f"mask{k}", 1, 0, 0), (f"nup{k}", lag + 2, 0, 0)], (2, -2, 0))
        m.op(f"dn{k}", [(f"mask{k}", 1, 0, 0), (f"ndn{k}", lag + 2, 0, 0)], (2, -2, 0))
        m.op(f"st{k}", [(f"up{k}", 1, 0, 0), (f"dn{k}", 1, 0, 0)], (2, -2, C))   # C + s, C - s or C
        terms.append(f"st{k}")
    lvl = 0
    while len(terms) > 1:
        nxt = []
        for i in range(0, len(terms) - 1, 2):
            t = f"sum{lvl}_{i}"
            m.field(t)
            m.op(t, [(terms[i], 1, 0, 0), (terms[i + 1], 1, 0, 0)], (2, 2, -C))
            nxt.append(t)
        if len(terms) % 2:
            t = f"sumc{lvl}"
            m.field(t)
            m.op(t, [(terms[-1], 1, 0, 0)], (1, 0))
            nxt.append(t)
        terms, lvl = nxt, lvl + 1
    # ---- update with a slow pull to the middle: Z = 127 + floor((32 - S) / 64), i.e. 125 + (2 .. -2)
    m.field("Z"), m.field("SZ")
    m.op("Z", [("S", 1, 0, 0)], (-1, C), L=(6, 6))
    m.op("SZ", [(terms[0], 1, 0, 0), ("Z", 1, 0, 0)], (2, 2, -125))           # C + dS + pull
    m.op("S", [("S", 1, 0, 0), ("SZ", 1, 0, 0)], (2, 2, -C))                  # S + dS + pull
    # ---- display: B1 through a gradient map (four ramps, two colour pairs at L = 6, one exact sum)
    k255 = ("K", 1, 0, 0)
    for i, t in enumerate(gradient_map.STOPS[:4]):
        w0, w1, _, o = gradient_map.ramp_params(t)
        m.field(f"ramp{i}")
        m.op(f"ramp{i}", [("B1", 1, 0, 0), k255], (w0, w1, o))
    pa, pb, dd = [], [], []
    for p in range(3):
        values = [gradient_map.rgb_to_ycbcr(c)[p] for c in PALETTE]
        wa, wb, y0, _ = gradient_map.plane_weights(values)
        oa = max(-128, min(127, y0))
        pa.append((wa[0], wa[1], oa))
        pb.append((wb[0], wb[1], 127))
        dd.append((2, 2, -127 + (y0 - oa)))
    m.field("pa"), m.field("pb"), m.field("D")
    m.op("pa", [("ramp0", 1, 0, 0), ("ramp1", 1, 0, 0)], pa, L=(6, 6))
    m.op("pb", [("ramp2", 1, 0, 0), ("ramp3", 1, 0, 0)], pb, L=(6, 6))
    m.op("D", [("pa", 1, 0, 0), ("pb", 1, 0, 0)], dd)
    return "D"


def build(iters=400000, seed=0):
    """D at the top-left corner. Tile row 1 holds the L = 6 fields (colour pairs, decay, blur pyramid)
    and 5 free tiles; S sits at the left of row 2; the other fields go to free tiles by annealing."""
    m = Machine(N, N, width_mbs=WIDTH_MBS, height_mbs=HEIGHT_MBS)
    program(m, **PARAMS)
    m.place("D", 0, 0)
    x = 0
    for n in ["pa", "pb", "Z"] + [f"{t}{k}" for k in range(1, 6) for t in "TB"]:
        m.place(n, x, TILE)
        x += m.fields[n].size_px[0]
    y2, y3 = TILE + HTILE, TILE + 2 * HTILE
    m.place("S", 0, y2)
    slots = ([(TILE * i, 0, 0) for i in range(1, 19)] + [(x + TILE * i, TILE, 0) for i in range(5)]
             + [(HTILE + TILE * i, y2, 0) for i in range(18)] + [(TILE * i, y3, 0) for i in range(19)])
    anneal(m, slots, {n: 0 for n, f in m.fields.items() if f.x0 is None}, iters, seed)
    m.check()
    return m


def start(m, seed=SEED):
    rng = np.random.default_rng(seed)
    s0 = rng.integers(0, 256, (N, N))
    init = m.initial({"S": np.repeat(s0[None], 3, 0).astype(np.int32), "K": np.full((3, N, N), 255, np.int32)})
    init = {n: v if n in STORED or n == "D" else np.full_like(v, 128) for n, v in init.items()}
    return init, STORED, None
