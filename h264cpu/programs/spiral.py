"""Griffeath's cyclic cellular automaton (14 states, Moore neighbourhood, threshold 1): spiral waves.

A 64x64 torus in a 2048x768 frame, 69 fields. A cell advances to the next state when a neighbour
already holds it. The 9 pipeline stages are interleaved, so the board updates every 9 frames.
"""
from __future__ import annotations

import numpy as np

from .. import vsim
from ..machine import Machine

NAME = "spiral"
NS, STEP = 14, 9                  # 14 states, stored as 9k
SIZE = 64                         # board cells per side
TILE = 2 * SIZE                   # a field is 128x128 luma pixels
COLS, ROWS = 16, 6
PERIOD = 9                        # frames per generation
STOPS = [0, 30, 60, 90]
PALETTE = [(40, 170, 230), (150, 70, 220), (235, 60, 80), (215, 225, 60), (40, 210, 190)]   # s = 0 .. 120
MOORE = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]


def rgb_to_ycbcr(c):
    r, g, b = c
    return (0.299 * r + 0.587 * g + 0.114 * b, 128 - 0.168736 * r - 0.331264 * g + 0.5 * b,
            128 + 0.5 * r - 0.418688 * g - 0.081312 * b)


def ramp_params(t):
    """bi(S, const255, 17, w1, 0, o) ~ clip(8.5 (s - t)) on the 14 state values."""
    s = np.arange(NS) * STEP
    want = np.clip(8.5 * (s - t), 0, 255)
    best = None
    for w1 in range(-128, 112):
        for o in range(-128, 128):
            got = vsim.bi(s, np.full(NS, 255), 17, w1, 0, o)
            err = np.abs(got - want).max()
            if best is None or err < best[0]:
                best = (err, w1, o)
    return 17, best[1], best[2]


def display_params():
    vals = np.array([rgb_to_ycbcr(c) for c in PALETTE])        # (5 stops, 3 planes)
    pa, pb, dd = [], [], []
    k = 128 / 255                                                # L = 6: pair weights are w / 128
    for p in range(3):
        v = vals[:, p]
        d = np.diff(v)
        wa = [int(round(d[0] * k)), int(round(d[1] * k))]
        wb = [int(round(d[2] * k)), int(round(d[3] * k))]
        oa = int(max(-128, min(127, round(v[0]))))
        pa.append((wa[0], wa[1], oa))
        pb.append((wb[0], wb[1], 127))
        dd.append((2, 2, -127 + int(round(v[0])) - oa))
    return pa, pb, dd


def build():
    m = Machine(SIZE, SIZE, width_mbs=COLS * TILE // 16, height_mbs=ROWS * TILE // 16)
    m.field("S", halo=8)
    m.field("K")
    m.op("K", [("K", 1, 0, 0)], (1, 0))                                          # a constant 255
    for i, (dy, dx) in enumerate(MOORE):
        m.field(f"g{i}")
        m.op(f"g{i}", [("S", 1, dy, dx), ("S", 1, 0, 0)], (2, -2, 127))         # 127 + neighbour - cell
    m.field("u"), m.field("z"), m.field("nx")
    m.op("u", [("S", 1, 0, 0)], (1, 9))                                          # cell + 9
    m.op("z", [("S", 1, 0, 0), ("K", 1, 0, 0)], (127, -56, -4))                  # 255 iff cell == 117
    for i in range(8):
        for name in ("up", "hi", "wr", "win", "t1_"):
            m.field(f"{name}{i}")
        m.op(f"up{i}", [(f"g{i}", 1, 0, 0), ("K", 1, 0, 0)], (127, -65, -63))    # 255 iff diff >= +5
        m.op(f"hi{i}", [(f"g{i}", 1, 0, 0), ("K", 1, 0, 0)], (127, -70, 3))      # 255 iff diff >= +14
        m.op(f"wr{i}", [(f"g{i}", 1, 0, 0), ("K", 1, 0, 0)], (-127, 9, 0))       # 255 iff diff <= -113 (wrap)
        m.op(f"win{i}", [(f"up{i}", 1, 0, 0), (f"hi{i}", 1, 0, 0)], (2, -2, 0))  # 255 iff diff == +9
        m.op(f"t1_{i}", [(f"win{i}", 1, 0, 0), (f"wr{i}", 2, 0, 0)], (2, 2, 0))  # this neighbour matches
    m.op("nx", [("u", 1, 0, 0), ("z", 1, 0, 0)], (2, -1, 0))                     # (cell + 9) mod 126
    for j in range(4):
        m.field(f"t2_{j}")
        m.op(f"t2_{j}", [(f"t1_{2 * j}", 1, 0, 0), (f"t1_{2 * j + 1}", 1, 0, 0)], (2, 2, 0))
    for j in range(2):
        m.field(f"t3_{j}")
        m.op(f"t3_{j}", [(f"t2_{2 * j}", 1, 0, 0), (f"t2_{2 * j + 1}", 1, 0, 0)], (2, 2, 0))
    m.field("adv"), m.field("keepN"), m.field("keepO")
    m.op("adv", [("t3_0", 1, 0, 0), ("t3_1", 1, 0, 0)], (2, 2, 0))              # 255 iff any neighbour matches
    m.op("keepN", [("nx", 6, 0, 0), ("adv", 1, 0, 0)], (2, 1, -128))            # next value where advancing
    m.op("keepO", [("S", 8, 0, 0), ("adv", 1, 0, 0)], (2, -2, 0))               # old value elsewhere
    m.op("S", [("keepN", 1, 0, 0), ("keepO", 1, 0, 0)], (2, 2, 0))              # the new board (+ wrapped halo)
    # colour display: four ramps, two weighted pairs per plane (L = 6), one sum
    for i, t in enumerate(STOPS):
        m.field(f"r{i}")
        m.op(f"r{i}", [("S", 1, 0, 0), ("K", 1, 0, 0)], ramp_params(t))
    pa, pb, dd = display_params()
    m.field("pa"), m.field("pb"), m.field("D")
    m.op("pa", [("r0", 1, 0, 0), ("r1", 1, 0, 0)], pa, L=(6, 6))
    m.op("pb", [("r2", 1, 0, 0), ("r3", 1, 0, 0)], pb, L=(6, 6))
    m.op("D", [("pa", 1, 0, 0), ("pb", 1, 0, 0)], dd)
    # layout: D at the top-left corner (the crop then trims only the right and bottom), the colour pairs
    # in tile row 1, S with its halo at the left of rows 2-3; every read within level 5.1's range
    m.place("S", 0, 2 * TILE)
    rows = [
        ["D", "r0", "r1", "r2", "r3"] + [f"g{i}" for i in range(8)],
        ["pa", "pb"],
        ["K"] + [f"up{i}" for i in range(8)] + [f"hi{i}" for i in range(5)],
        ["hi5", "hi6", "hi7"] + [f"wr{i}" for i in range(8)] + ["win0", "win1", "win2"],
        ["keepN", "keepO"] + [f"win{i}" for i in range(3, 8)] + [f"t1_{i}" for i in range(8)] + ["t2_0"],
        ["t2_1", "t2_2", "t2_3", "t3_0", "t3_1", "adv", "u", "z", "nx"],
    ]
    for r, names in enumerate(rows):
        c0 = 2 if r in (2, 3) else 0
        for c, name in enumerate(names):
            m.place(name, (c0 + c) * TILE, r * TILE)
    m.check()
    return m


def cca_step(s, n=NS, threshold=1):
    nx = (s + 1) % n
    count = sum((np.roll(s, (-dy, -dx), axis=(0, 1)) == nx).astype(np.int32) for dy, dx in MOORE)
    return np.where(count >= threshold, nx, s)


def start(m, seed=4):
    """Starting values of every field, the stored fields (all: the 9 interleaved phases must start
    consistent) and the reference automaton."""
    board = np.random.default_rng(seed).integers(0, NS, (SIZE, SIZE))
    s0 = np.repeat((board * STEP)[None], 3, 0).astype(np.int32)
    init = m.initial({"S": s0, "K": np.full((3, SIZE, SIZE), 255, np.int32)})

    def read(m, y):
        sx, sy = m.fields["S"].board
        return y[sy:sy + 2 * SIZE:2, sx:sx + 2 * SIZE:2].astype(int) // STEP

    return init, None, (PERIOD, board, cca_step, read)
