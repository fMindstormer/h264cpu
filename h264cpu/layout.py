"""Place fields in a frame so that every read stays inside the level's motion vector range.

Fields that are already placed stay put. Each movable field goes to a free slot of its own class
(classes keep, say, the L = 6 fields in their band), chosen by simulated annealing on the motion
vector extent of every read, including the wrapped halo reads of haloed fields.
"""
from __future__ import annotations

import numpy as np


def anneal(m, slots, cls_of, iters=200000, seed=0, xl=2040, yl=504):
    """slots: [(x0, y0, cls)]; cls_of: {field: cls} for every field still to place."""
    movable = [n for n, f in m.fields.items() if f.x0 is None]
    assert set(movable) == set(cls_of), "every unplaced field needs a class"
    for c in set(cls_of.values()):
        need = sum(1 for n in movable if cls_of[n] == c)
        have = sum(1 for s in slots if s[2] == c)
        assert need <= have, f"class {c}: {need} fields for {have} slots"
    edges = [(o.out, src, dy, dx) for o in m.ops.values() for (src, _, dy, dx) in o.inputs]
    touching = {n: [i for i, e in enumerate(edges) if n in (e[0], e[1])] for n in m.fields}
    rng = np.random.default_rng(seed)
    slot_of, owner = {}, {}
    for c in sorted(set(cls_of.values()), key=str):
        free = [i for i, s in enumerate(slots) if s[2] == c]
        rng.shuffle(free)
        for n in [n for n in movable if cls_of[n] == c]:
            slot_of[n] = free.pop()
            owner[slot_of[n]] = n
    W = m.W

    def board(n):
        f = m.fields[n]
        x0, y0 = slots[slot_of[n]][:2] if n in slot_of else (f.x0, f.y0)
        return x0 + 2 * f.halo, y0 + 2 * f.halo

    def cost(i):
        dst, src, dy, dx = edges[i]
        (fx, fy), (sx, sy) = board(dst), board(src)
        bx, by = sx + 2 * dx - fx, sy + 2 * dy - fy
        w = 2 * W if m.fields[dst].halo else 0                 # halo macroblocks read the far side
        wx, wy = w, (2 * m.H if w else 0)
        h = m.fields[src].halo                                 # so do reads that wrap beyond the halo
        wx, wy = (2 * m.W if abs(dx) > h else wx), (2 * m.H if abs(dy) > h else wy)
        over = max(0, -xl - (bx - wx)) + max(0, bx + wx - xl) + max(0, -yl - (by - wy)) + max(0, by + wy - yl)
        return 1000 * over + abs(bx) / 64 + abs(by) / 16

    cur = [cost(i) for i in range(len(edges))]
    temps = np.geomspace(50, 0.05, iters)
    for it in range(iters):
        n = movable[rng.integers(len(movable))]
        same = [i for i, s in enumerate(slots) if s[2] == cls_of[n]]
        s_new = same[rng.integers(len(same))]
        s_old = slot_of[n]
        if s_new == s_old:
            continue
        other = owner.get(s_new)
        aff = set(touching[n]) | (set(touching[other]) if other else set())
        before = sum(cur[i] for i in aff)
        slot_of[n] = s_new
        if other:
            slot_of[other] = s_old
        new = {i: cost(i) for i in aff}
        delta = sum(new.values()) - before
        if delta <= 0 or rng.random() < np.exp(-delta / temps[it]):
            for i, c in new.items():
                cur[i] = c
            owner[s_new] = n
            if other:
                owner[s_old] = other
            else:
                del owner[s_old]
        else:
            slot_of[n] = s_old
            if other:
                slot_of[other] = s_new
    worst = int(np.argmax(cur))
    assert cur[worst] < 1000, f"layout leaves a read outside the motion vector range: {edges[worst]}"
    for n, s in slot_of.items():
        m.place(n, *slots[s][:2])
