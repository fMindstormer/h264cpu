"""Circuits of bit signals on a Machine, scheduled into pipeline stages.

Every signal is a field of W x H cells, each 0 or 255 (in all three planes). A gate is one op:

    OR(a, b)      clip(a + b)        bi, weights 2, 2 at L = 0
    ANDNOT(a, b)  clip(a - b)        a AND NOT b: bi, weights 2, -2 at L = 0
    NOT(a)        ANDNOT(K, a)       K is the constant 255

and may read its inputs shifted by (dy, dx) cells on the torus. Gates are written without delays: each
op runs at a stage one later than its latest input, and reads every input that many frames back.
State signals start each wave at stage 0; their ops all run at stage P, the longest of them, so the
whole state advances once every P frames, like Life's board. P copies of the computation are
interleaved in the pipeline; they stay equal because they start equal. A read further back than the
15 frames that frame_num tells apart goes through relay copies. A field read at an offset that is not a multiple of
8 cells gets an 8-cell halo; whole-macroblock offsets wrap without one.
"""
from __future__ import annotations

import numpy as np

MAX_DELAY = 15                     # frame_num wraps at 16, so 15 frames back is the furthest reference
OR_P, ANDNOT_P, COPY_P = (2, 2, 0), (2, -2, 0), (1, 0)


class Sig:
    def __init__(self, c, name, kind, inputs=(), params=None, L=(0, 0), init=None):
        self.c, self.name, self.kind = c, name, kind
        self.inputs = [i if isinstance(i, tuple) else (i, 0, 0) for i in inputs]
        self.params, self.L, self.init = params, L, init

    def at(self, dy=0, dx=0):
        """This signal read shifted: cell (y, x) of the result is cell (y + dy, x + dx) of this one."""
        return (self, dy, dx)


class Circuit:
    def __init__(self, W, H):
        self.W, self.H = W, H
        self.sigs, self.count = {}, {}
        self.K = self.const("K", np.full((H, W), 255))

    def _new(self, name, *a, **k):
        if name.endswith("#"):                                      # auto-numbered helper
            n = self.count.get(name, 0)
            self.count[name] = n + 1
            name = f"{name[:-1]}{n}"
        assert name not in self.sigs, name
        s = Sig(self, name, *a, **k)
        self.sigs[name] = s
        return s

    # ------------------------------------------------------------------ signals
    def const(self, name, values):
        v = np.asarray(values, np.int32)
        assert v.shape == (self.H, self.W) and v.min() >= 0 and v.max() <= 255
        return self._new(name, "const", init=v)

    def state(self, name, init):
        v = np.asarray(init, np.int32)
        assert v.shape == (self.H, self.W)
        return self._new(name, "state", init=v)

    def op(self, name, inputs, params, L=(0, 0)):
        return self._new(name, "op", inputs, params, L)

    def set(self, state, inputs, params, L=(0, 0)):
        """The op that gives a state signal its next value."""
        assert state.kind == "state" and state.params is None
        state.inputs = [i if isinstance(i, tuple) else (i, 0, 0) for i in inputs]
        state.params, state.L = params, L

    # ------------------------------------------------------------------ gates
    def OR(self, name, a, b):
        return self.op(name, [a, b], OR_P)

    def ANDNOT(self, name, a, b):
        return self.op(name, [a, b], ANDNOT_P)

    def NOT(self, name, a):
        return self.op(name, [self.K, a], ANDNOT_P)

    def COPY(self, name, a):
        return self.op(name, [a], COPY_P)

    def MUX(self, name, s, ns, a, b):
        """a where s, b where not: s and ns are a select signal and its complement."""
        return self.OR(name, self.ANDNOT(name + "a", a, ns), self.ANDNOT(name + "b", b, s))

    def reduce(self, name, x, axis, into=None):
        """OR of all cells along a row (axis 1) or a column (axis 0), in every cell of it: a butterfly of
        cyclic shifts 1, 2, 4, ... With `into`, a state signal, the last step is that state's op."""
        n = self.W if axis == 1 else self.H
        s = 1
        while s < n:
            shifted = x.at(*((0, s) if axis == 1 else (s, 0)))
            if 2 * s < n:
                x = self.OR(f"{name}.{s}", x, shifted)
            elif into is not None:
                self.set(into, [x, shifted], OR_P)
                x = into
            else:
                x = self.OR(name, x, shifted)
            s *= 2
        return x

    # ------------------------------------------------------------------ compiling
    def stages(self):
        st = {}

        def stage(s):
            if s.kind == "const":
                return None
            if s.kind == "state":
                return 0
            if s.name not in st:
                st[s.name] = None                                    # cycle guard
                ins = [stage(i) for (i, _, _) in s.inputs]
                ins = [v for v in ins if v is not None]
                assert ins, f"{s.name} reads only constants"
                st[s.name] = 1 + max(ins)
            assert st[s.name] is not None, f"combinational loop through {s.name}"
            return st[s.name]

        for s in self.sigs.values():
            if s.kind == "op":
                stage(s)
        P = 0
        for s in self.sigs.values():
            if s.kind == "state":
                assert s.params is not None, f"state {s.name} has no op"
                ins = [stage(i) for (i, _, _) in s.inputs]
                P = max(P, 1 + max(v for v in ins if v is not None))
        return st, P

    def compile(self, m):
        """Fields and ops on Machine m (W x H cells). Returns the period P."""
        assert (m.W, m.H) == (self.W, self.H)
        st, P = self.stages()
        reads = []                                                  # (reader, source, delay, dy, dx)
        relays = {}

        def source(src, delay):
            """src read `delay` frames back, through relay copies if that is beyond the reference list."""
            while delay > MAX_DELAY:
                key = (src.name, delay)
                if key not in relays:
                    r = Sig(self, f"{src.name}~{len(relays)}", "relay", [(src, 0, 0)], COPY_P)
                    relays[key] = r
                    reads.append((r, src, MAX_DELAY, 0, 0))
                src, delay = relays[key], delay - MAX_DELAY
            return src, delay

        for s in list(self.sigs.values()):
            if s.kind == "const":
                reads.append((s, s, 1, 0, 0))
                continue
            here = P if s.kind == "state" else st[s.name]
            for (i, dy, dx) in s.inputs:
                d = 1 if i.kind == "const" else here - (0 if i.kind == "state" else st[i.name])
                src, d = source(i, d)
                reads.append((s, src, d, dy, dx))
        sigs = list(self.sigs.values()) + list(relays.values())
        halo = {s.name: 0 for s in sigs}
        for (_, src, _, dy, dx) in reads:
            if dy % 8 or dx % 8:
                halo[src.name] = 8
        for s in sigs:
            m.field(s.name, halo=halo[s.name])
        by_reader = {}
        for (r, src, d, dy, dx) in reads:
            by_reader.setdefault(r.name, []).append((src.name, d, dy, dx))
        for s in sigs:
            params = COPY_P if s.kind == "const" else s.params
            m.op(s.name, by_reader[s.name], params, s.L)
        self.P, self.halo = P, halo
        return P

    def given(self):
        """Starting values of the constants and the state, in all three planes."""
        return {s.name: np.repeat(s.init[None], 3, 0) for s in self.sigs.values() if s.kind in ("const", "state")}
