"""The Life tunnel: Game of Life on a 128x128 torus at the centre of a 1920x1080 picture that the decoder
zooms outward and turns, every frame, from its own previous frame.

The board's display field D sits in the middle of a picture field T. Every macroblock of T copies the
previous frame from a point a little nearer the centre and a little turned back, at quarter-sample
precision, so the decoder interpolates, and fades it. What leaves the board's edge therefore streams
outward on a spiral, and each streak is the history of one edge cell, one tooth per generation.
Everything else is Life exactly as in life.py, 6 frames per generation.
"""
from __future__ import annotations

import math

import numpy as np

from ..layout import anneal
from ..machine import Machine
from . import life

NAME = "tunnel"
N = 128                                   # board cells per side
TW, TH = 1920, 1088                       # the picture field; players show 1920x1080
WIDTH_MBS, HEIGHT_MBS = 232, 68           # T, then the other 17 fields in three bands to its right
PERIOD = life.PERIOD
ZOOM, TURN = 1.03, 0.8                    # per frame: scale about the centre, and degrees of rotation
FADE = ((62, -1), (62, 5), (62, 3))      # per plane (weight / 64, offset): fade to black; aging streaks drift blue
CENTRE = (TW / 2 - 0.5, TH / 2 - 0.5)     # between the four middle pixels, where the board's centre is


def plan(m):
    """Each macroblock of T reads the previous frame where its centre was one frame ago."""
    T = m.fields["T"]
    th = math.radians(TURN)
    ca, sa = math.cos(-th) / ZOOM, math.sin(-th) / ZOOM
    blocks = {}
    for my in range(TH // 16):
        for mx in range(TW // 16):
            px, py = mx * 16 + 7.5 - CENTRE[0], my * 16 + 7.5 - CENTRE[1]
            sx, sy = ca * px - sa * py, sa * px + ca * py
            mv = (round((sx - px) * 4), round((sy - py) * 4))
            blocks[(mx, my)] = (((1, mv, FADE),),) * 4
    return blocks


def build(iters=150000, seed=0):
    """T at the top-left; the other 17 fields in three bands to its right. Reads reach at most one band
    up or down (the level's vertical vector range), so the pipeline runs p (top) -> q -> c, t, ge -> S
    (middle) -> d, H, r (bottom); within a band the L = 6 fields come first, next to T, which is L = 6
    too, so each macroblock row needs at most two slices."""
    m = Machine(N, N, width_mbs=WIDTH_MBS, height_mbs=HEIGHT_MBS)
    life.program(m)
    m.image("T", TW, TH, display=(TW, 1080))
    m.warp("T", plan, L=(6, 6))
    m.place("T", 0, 0)                                   # the crop then trims only the right and bottom
    m.place("D", TW // 2 - N, TH // 2 - N)               # the board, in the middle of the picture
    t = 2 * N
    m.place("S", TW + t, t)
    slots = [(TW + t * i, 0, 6) for i in range(5)] + [(TW + t * i, 0, 0) for i in (5, 6)] \
        + [(TW, t, 6)] + [(TW + t + 2 * N + 32 + t * i, t, 0) for i in range(4)] \
        + [(TW, 2 * t + 32, 6)] + [(TW + t * i, 2 * t + 32, 0) for i in range(1, 6)]
    cls = {n: (6 if m.ops[n].L == (6, 6) else 0) for n, f in m.fields.items() if f.x0 is None}
    anneal(m, slots, cls, iters, seed)
    m.check()
    return m


CROP, FIRST = "T", {"D"}                  # players show T; frame 0 holds only the board as raw samples


def soup(seed=1, density=0.3):
    return np.random.default_rng(seed).random((N, N)) < density


def given(board):
    s0 = np.repeat((board.astype(np.int32) * 255)[None], 3, 0)
    return {"S": s0, "H": s0.copy(), "K": np.full((3, N, N), 255, np.int32)}


def start_given(board):
    """given() plus the picture, which is not stored: the tunnel starts grey and fades to black."""
    g = given(board)
    g["T"] = (np.full((TH, TW), 128, np.int32), np.full((TH // 2, TW // 2), 128, np.int32),
              np.full((TH // 2, TW // 2), 128, np.int32))
    return g


def start(m, board=None):
    board = soup() if board is None else board
    init = m.initial(start_given(board))

    def read(m, y):
        sx, sy = m.fields["S"].board
        return y[sy:sy + 2 * N:2, sx:sx + 2 * N:2] > 127

    stored = set(m.fields) - {"T"}
    return init, stored, (PERIOD, board, life.life_step, read)
