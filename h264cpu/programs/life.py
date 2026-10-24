"""Conway's Game of Life (B3/S23) on a 200x200 torus, 18 fields in a 4032x832 frame.

One generation takes 6 frames (10 per second at 60 fps):
    p1..p4  pairs of neighbours at L = 6: (8a + 8b + 64) >> 7 is 16 per live neighbour (cells are 0 or 255)
    p5      the cell itself at L = 6: 8 if alive
    q1, q2  pair sums;  c = q1 + q2 - 16;  t = c + p5, so t = 16 * neighbours + 8 * alive - 16
    S       alive next  <=>  24 <= t <= 40  <=>  3 neighbours, or 2 neighbours and alive
The display glows: H = max(S, 0.8 * H a generation ago), then a three-colour map (ember palette).
"""
from __future__ import annotations

import numpy as np

from .. import vsim
from ..layout import anneal
from ..machine import Machine

NAME = "life"
N = 200                                    # board cells per side
TILE, HTILE = 2 * N, 2 * N + 32            # a field's side in pixels, without and with an 8-cell halo
WIDTH_MBS, HEIGHT_MBS = 252, 52            # one band of L = 6 fields, one of L = 0 fields
PERIOD = 6                                 # frames per generation
# ember palette in YCbCr: dead (black), a cell that died a few generations ago (orange), alive (warm white)
PALETTE_YCBCR = [(0, 127, 127), (125.0, 74.4, 202.9), (239.9, 105.5, 138.7)]


def threshold(lo, hi, values):
    """(w0, w1, o) for bi(x, const 255, w0, w1, 0, o): 0 for every value <= lo, 255 for every value >= hi."""
    values = np.array(sorted(values))
    for w0 in range(2, 128, 2):
        for w1 in range(-128, 128):
            if not -128 <= w0 + w1 <= 128:
                continue
            o_max = -((w0 * lo + 255 * w1 + 1) >> 1)
            o_min = 255 - ((w0 * hi + 255 * w1 + 1) >> 1)
            if max(o_min, -128) <= min(o_max, 127):
                o = max(o_min, -128)
                got = vsim.bi(values, np.full(len(values), 255), w0, w1, 0, o)
                if (got[values <= lo] == 0).all() and (got[values >= hi] == 255).all():
                    return w0, w1, o
    raise ValueError("no threshold op")


def program(m):
    m.field("S", halo=8)
    m.field("K")
    m.op("K", [("K", 1, 0, 0)], (64, 0), L=(6, 6))                                    # constant 255
    pairs = [((-1, -1), (-1, 0)), ((-1, 1), (0, -1)), ((0, 1), (1, -1)), ((1, 0), (1, 1))]
    for i, ((ay, ax), (by, bx)) in enumerate(pairs, 1):
        m.field(f"p{i}")
        m.op(f"p{i}", [("S", 1, ay, ax), ("S", 1, by, bx)], (8, 8, 0), L=(6, 6))       # 16 per live neighbour
    m.field("p5")
    m.op("p5", [("S", 1, 0, 0)], (2, 0), L=(6, 6))                                    # 8 if alive
    for n in ("q1", "q2", "c", "t", "ge24", "ge48"):
        m.field(n)
    m.op("q1", [("p1", 1, 0, 0), ("p2", 1, 0, 0)], (2, 2, 0))
    m.op("q2", [("p3", 1, 0, 0), ("p4", 1, 0, 0)], (2, 2, 0))
    m.op("c", [("q1", 1, 0, 0), ("q2", 1, 0, 0)], (2, 2, -16))                        # 16 * neighbours - 16
    m.op("t", [("c", 1, 0, 0), ("p5", 3, 0, 0)], (2, 2, 0))                           # + 8 if alive
    tvals = [max(0, 16 * k - 16) + 8 * a for k in range(9) for a in (0, 1)]
    m.op("ge24", [("t", 1, 0, 0), ("K", 1, 0, 0)], threshold(16, 24, tvals))
    m.op("ge48", [("t", 1, 0, 0), ("K", 1, 0, 0)], threshold(40, 48, tvals))
    m.op("S", [("ge24", 1, 0, 0), ("ge48", 1, 0, 0)], (2, -2, 0))                     # 24 <= t <= 40
    # glowing trails: d = relu(0.8 H - S), H = S + d = max(S, 0.8 H), H read one generation back
    m.field("d"), m.field("H")
    m.op("d", [("H", PERIOD - 1, 0, 0), ("S", 1, 0, 0)], (102, -128, 0), L=(6, 6))
    m.op("H", [("S", 2, 0, 0), ("d", 1, 0, 0)], (2, 2, 0))
    # colour: two ramps (clip(2H), clip(2H - 255)) and one three-stop mix at L = 6
    m.field("r0"), m.field("r1"), m.field("D")
    m.op("r0", [("H", 1, 0, 0)], (2, 0))
    m.op("r1", [("H", 1, 0, 0), ("K", 1, 0, 0)], (4, -2, 0))
    k = 128 / 255
    mix = [(round((c1 - c0) * k), round((c2 - c1) * k), round(c0)) for c0, c1, c2 in zip(*PALETTE_YCBCR)]
    m.op("D", [("r0", 1, 0, 0), ("r1", 1, 0, 0)], mix, L=(6, 6))


def build(iters=150000, seed=0):
    m = Machine(N, N, width_mbs=WIDTH_MBS, height_mbs=HEIGHT_MBS)
    program(m)
    m.place("D", 0, 0)                               # the crop then trims only the right and bottom
    m.place("S", 4 * TILE, TILE)                     # the board sits mid-row; its halo reads stay in range
    top = [(TILE * i, 0, 6) for i in range(1, 10)]
    bottom = [(TILE * i, TILE, 0) for i in range(4)] + [(4 * TILE + HTILE + TILE * i, TILE, 0) for i in range(5)]
    cls = {n: (6 if m.ops[n].L == (6, 6) else 0) for n, f in m.fields.items() if f.x0 is None}
    anneal(m, top + bottom, cls, iters, seed)
    m.check()
    return m


def life_step(board):
    n = sum(np.roll(np.roll(board, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
    return ((n == 3) | (board & (n == 2))).astype(bool)


def soup(seed=1, density=0.3):
    return np.random.default_rng(seed).random((N, N)) < density


def given(board):
    """The fields a writer is given: the board, its glow (equal to it at the start) and the constant."""
    s0 = np.repeat((board.astype(np.int32) * 255)[None], 3, 0)
    return {"S": s0, "H": s0.copy(), "K": np.full((3, N, N), 255, np.int32)}


def start(m, board=None):
    board = soup() if board is None else board
    init = m.initial(given(board))

    def read(m, y):
        sx, sy = m.fields["S"].board
        return y[sy:sy + 2 * N:2, sx:sx + 2 * N:2] > 127

    return init, None, (PERIOD, board, life_step, read)
