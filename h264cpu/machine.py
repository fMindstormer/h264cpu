"""Turn a program of weighted-prediction ops into H.264 frames, and simulate what the decoder will output.

A program is a set of fields (boards of cells) and one op per field. Every frame, every op reads up
to two fields of earlier frames (a delay of 1 means the previous frame) and writes its field:

    bi : clip(((w0 * a + w1 * b + 2^L) >> (L + 1)) + o)      one B_Bi_16x16 macroblock per 16x16 pixels
    uni: clip(((w * a + 2^(L-1)) >> L) + o)                  one B_L0_16x16 macroblock

A cell is 2x2 luma pixels and 1 chroma pixel, so all three planes compute the same board in lockstep
(motion vectors are whole chroma samples). Weights and offsets may differ per plane; L is shared by a
slice. Fields sit in tiles of the frame; reads at an offset are only allowed from a field with a
halo, which its op fills with wrapped values so the board behaves like a torus.

A picture field is a plain region of pixels, rewritten by a warp: each of its macroblocks (or each 8x8
quadrant) predicts from one or two earlier frames at its own quarter-sample motion vector, so the
decoder interpolates (interp.py). Cell fields may sit inside a picture field; their macroblocks are theirs.
"""
from __future__ import annotations

import numpy as np

from . import interp
from . import writer as h264w
from . import vsim
from .writer import Entry, Quads

PLANES = 3
MAX_ENTRIES = 16                   # reference list entries per list in a frame slice (H.264 7.4.3)


class Field:
    def __init__(self, name, w, h, halo=0, image=None, display=None):
        self.name, self.w, self.h, self.halo = name, w, h, halo
        self.image = image                           # (width, height) in pixels for a picture field
        self.display = display or image              # the part a player shows, if this is the crop
        self.x0 = self.y0 = None                     # top-left of the region (luma pixels)

    @property
    def size_px(self):
        if self.image:
            return self.image
        return (self.w + 2 * self.halo) * 2, (self.h + 2 * self.halo) * 2

    @property
    def shown_px(self):
        return self.display if self.image else self.size_px

    @property
    def board(self):                                 # luma pixel origin of cell (0, 0)
        return self.x0 + 2 * self.halo, self.y0 + 2 * self.halo


class Op:
    """inputs: [(field, delay, dy, dx)]; params: per plane (w0, w1, o) for bi or (w, o) for uni, written
    for weight denominators L = (luma L, chroma L); the field must sit in a slice with those."""

    def __init__(self, out, inputs, params, L=(0, 0)):
        self.out, self.inputs, self.L = out, inputs, tuple(L)
        params = list(params) if isinstance(params[0], (tuple, list)) else [tuple(params)] * PLANES
        assert len(params) == PLANES
        self.params = [tuple(p) for p in params]
        self.kind = "bi" if len(inputs) == 2 else "uni"


class Warp:
    """The op of a picture field. plan(m) gives, after placement, {(mx, my): quadrants} for the field's
    macroblocks (mx, my relative to its top-left): 4 quadrants (top-left, top-right, bottom-left,
    bottom-right), each a tuple of one read (list 0) or two (list 0, list 1). A read is
    (delay, (mvx, mvy) in quarter luma samples, ((wY, oY), (wCb, oCb), (wCr, oCr))); two reads mix as
    bi-prediction, whose offset is the rounded mean of the two."""
    kind = "warp"
    inputs = ()

    def __init__(self, out, plan, L):
        self.out, self.plan, self.L = out, plan, tuple(L)


class Machine:
    def __init__(self, W, H, width_mbs, height_mbs):
        """Slices are cut automatically wherever the weight denominators (L, Lc) change in raster order."""
        self.W, self.H = W, H
        self.width_mbs, self.height_mbs = width_mbs, height_mbs
        self.fields, self.ops = {}, {}
        self.background = (128, 128, 128)            # what the grey IDR macroblocks decode to

    def field(self, name, halo=0):
        f = Field(name, self.W, self.H, halo)
        self.fields[name] = f
        return f

    def image(self, name, w, h, display=None):
        assert w % 16 == 0 and h % 16 == 0
        f = Field(name, self.W, self.H, image=(w, h), display=display)
        self.fields[name] = f
        return f

    def op(self, out, inputs, params, L=(0, 0)):
        self.ops[out] = Op(out, inputs, params, L)

    def warp(self, out, plan, L):
        assert self.fields[out].image, "a warp writes a picture field"
        self.ops[out] = Warp(out, plan, L)

    def place(self, name, x0, y0):
        f = self.fields[name]
        assert x0 % 16 == 0 and y0 % 16 == 0
        f.x0, f.y0 = x0, y0

    # ------------------------------------------------------------------ checks
    def check(self):
        Wp, Hp = self.width_mbs * 16, self.height_mbs * 16
        occupied = {}
        for f in sorted(self.fields.values(), key=lambda f: f.image is not None):   # cells, then pictures
            assert f.x0 is not None, f"{f.name} not placed"
            fw, fh = f.size_px
            assert f.x0 + fw <= Wp and f.y0 + fh <= Hp, f"{f.name} outside the frame"
            assert fw % 16 == 0 and fh % 16 == 0
            for my in range(f.y0 // 16, (f.y0 + fh) // 16):
                for mx in range(f.x0 // 16, (f.x0 + fw) // 16):
                    if (mx, my) in occupied:
                        assert f.image and not self.fields[occupied[(mx, my)]].image, \
                            f"{f.name} overlaps {occupied[(mx, my)]}"
                        continue                     # a cell field inside a picture field
                    occupied[(mx, my)] = f.name
        self.plans = {}
        for o in self.ops.values():
            if o.kind == "warp":
                self.plans[o.out] = self._check_plan(o, occupied)
                continue
            for (src, delay, dy, dx) in o.inputs:
                assert not self.fields[src].image, f"{o.out}: cell ops read cell fields, not the picture {src}"
                for d in (dy, dx):           # beyond the halo, a read wraps by whole macroblocks
                    assert abs(d) <= self.fields[src].halo or d % 8 == 0, f"{o.out} reads {src} off its board"
                assert 1 <= delay <= 15, f"{o.out} reads {delay} frames back; frame_num tells 16 apart"
            L = [o.L[0], o.L[1], o.L[1]]
            for p in range(PLANES):
                if o.kind == "bi":
                    w0, w1, off = o.params[p]
                    vsim.bi(np.zeros(1), np.zeros(1), w0, w1, L[p], off)        # raises if illegal
                else:
                    w, off = o.params[p]
                    vsim.uni(np.zeros(1), w, L[p], off)
        self.occupied = occupied
        return occupied

    def _check_plan(self, o, occupied):
        f = self.fields[o.out]
        plan = o.plan(self)
        mine = {(mx - f.x0 // 16, my - f.y0 // 16) for (mx, my), n in occupied.items() if n == o.out}
        assert mine <= set(plan), f"{o.out}: the plan misses macroblocks"
        plan = {k: tuple(tuple(q) for q in plan[k]) for k in mine}
        L = [o.L[0], o.L[1], o.L[1]]
        for quads in plan.values():
            assert len(quads) == 4
            for reads in quads:
                assert len(reads) in (1, 2)
                for (delay, mv, wo) in reads:
                    assert 1 <= delay <= 15
                    assert -8192 <= mv[0] <= 8191 and -2048 <= mv[1] <= 2047, f"{o.out}: vector {mv} beyond level 5.1"
                for p in range(PLANES):
                    if len(reads) == 2:
                        vsim.bi(np.zeros(1), np.zeros(1), reads[0][2][p][0], reads[1][2][p][0], L[p],
                                (reads[0][2][p][1] + reads[1][2][p][1] + 1) >> 1)
                        vsim._check_o(reads[0][2][p][1]), vsim._check_o(reads[1][2][p][1])
                    else:
                        vsim.uni(np.zeros(1), reads[0][2][p][0], L[p], reads[0][2][p][1])
        return plan

    def _delays(self, o):
        if o.kind == "warp":
            return {d for quads in self.plans[o.out].values() for reads in quads for (d, _, _) in reads}
        return {d for (_, d, _, _) in o.inputs}

    def max_delay(self):
        if not hasattr(self, "plans"):
            self.check()
        return max(d for o in self.ops.values() for d in self._delays(o))

    # ------------------------------------------------------------------ macroblock instructions
    def _mv(self, out_f, mb_px, src_f, dy, dx, wrap):
        """Motion vector (luma pixels) for the macroblock at mb_px of field out_f reading src_f."""
        mx, my = mb_px
        bx, by = out_f.board
        cx, cy = (mx - bx) // 2, (my - by) // 2              # cell of the macroblock's top-left pixel
        if wrap:
            cx %= self.W
            cy %= self.H
        sx, sy = src_f.board
        return (sx + 2 * self._wrapped(cx + dx, self.W, src_f.halo) - mx,
                sy + 2 * self._wrapped(cy + dy, self.H, src_f.halo) - my)

    @staticmethod
    def _wrapped(c, n, halo):
        """The first of 8 cells to read, from c on a torus of n cells: c itself if they lie on the board
        or its halo, else c moved by whole turns of the torus."""
        for r in (c, c % n, c % n - n):
            if -halo <= r and r + 8 <= n + halo:
                return r
        raise AssertionError(f"cells {c}..{c + 7} wrap across the edge of a board of {n} with halo {halo}")

    def slices(self):
        """[(first_mb, end_mb, L, Lc)]: runs of macroblocks whose ops share weight denominators. An unused
        macroblock takes its predecessor's (L, Lc), so it never starts a slice of its own."""
        occupied = self.check()
        n = self.width_mbs * self.height_mbs
        names = [occupied.get((a % self.width_mbs, a // self.width_mbs)) for a in range(n)]
        L = next(self.ops[nm].L for nm in names if nm is not None)
        runs, s, keys = [], 0, (set(), set())
        for a, nm in enumerate(names):
            if nm is None:
                continue
            Lf = self.ops[nm].L
            mine = self._mb_entries(nm, a % self.width_mbs, a // self.width_mbs)
            grow = [keys[0] | mine[0], keys[1] | mine[1]]
            if Lf != L or max(len(grow[0]), len(grow[1])) > MAX_ENTRIES - 1:
                runs.append((s, a, *L))
                s, L = a, Lf
                grow = list(mine)
            keys = grow
        runs.append((s, n, *L))
        return runs

    def _mb_entries(self, name, mx, my):
        """The keys of the list 0 and list 1 entries macroblock (mx, my) of field name uses."""
        o = self.ops[name]
        if o.kind != "warp":
            k0, k1 = self._entries(o)
            return {k0.key()}, ({k1.key()} if k1 else set())
        f = self.fields[name]
        quads = self.plans[name][(mx - f.x0 // 16, my - f.y0 // 16)]
        return ({Entry(r[0][0], r[0][2]).key() for r in quads},
                {Entry(r[1][0], r[1][2]).key() for r in quads if len(r) > 1})

    @staticmethod
    def _entries(o):
        """The list 0 and list 1 entries (None if unused) of an op: delay, then weight and offset per plane."""
        if o.kind == "bi":
            (_, da, _, _), (_, db, _, _) = o.inputs
            return Entry(da, [(p[0], p[2]) for p in o.params]), Entry(db, [(p[1], p[2]) for p in o.params])
        (_, da, _, _), = o.inputs
        return Entry(da, [(p[0], p[1]) for p in o.params]), None

    def instructions(self):
        """Per slice: (first_mb, L, Lc, l0 entries, l1 entries, macroblock list). Identical every frame.
        Each macroblock is (pred, ref0, mv0, ref1, mv1, copy_ok).

        Index 0 of both lists is the plain copy of the previous frame, used only with zero motion (by
        unused macroblocks), so the co-located zero-motion rule of skipped macroblocks never changes a
        prediction. Ops with the same delay, weights and offsets share an entry; motion vectors say
        which field each macroblock reads."""
        occupied = self.check()
        W = self.width_mbs
        out = []
        for (s, e, L, Lc) in self.slices():
            assert L <= 6 and Lc <= 6, "the copy entry's weight 2^L must stay within -128..127"
            ident_y, ident_c = 1 << L, 1 << Lc
            copy = Entry(1, [(ident_y, 0), (ident_c, 0), (ident_c, 0)])
            l0, l1, idx0, idx1 = [copy], [copy], {}, {}

            def entry(lst, idx, ent):
                if ent.key() not in idx:
                    idx[ent.key()] = len(lst)
                    lst.append(ent)
                return idx[ent.key()]

            mbs = []
            for a in range(s, e):
                mx, my = a % W, a // W
                name = occupied.get((mx, my))
                if name is None:                                         # unused: keep its content
                    mbs.append((1, 0, (0, 0), 0, (0, 0), True))
                    continue
                f, o = self.fields[name], self.ops[name]
                if o.kind == "warp":
                    parts = []
                    for reads in self.plans[name][(mx - f.x0 // 16, my - f.y0 // 16)]:
                        r0 = entry(l0, idx0, Entry(reads[0][0], reads[0][2]))
                        if len(reads) == 2:
                            parts.append((3, r0, reads[0][1], entry(l1, idx1, Entry(reads[1][0], reads[1][2])), reads[1][1]))
                        else:
                            parts.append((1, r0, reads[0][1], 0, (0, 0)))
                    mbs.append(Quads(parts))
                    continue
                px = (mx * 16, my * 16)
                bx, by = f.board
                in_halo = not (bx <= px[0] < bx + 2 * f.w and by <= px[1] < by + 2 * f.h)
                mvs = [self._mv(f, px, self.fields[src], dy, dx, in_halo) for (src, _, dy, dx) in o.inputs]
                e0, e1 = self._entries(o)
                if e1 is not None:
                    mbs.append((3, entry(l0, idx0, e0), mvs[0], entry(l1, idx1, e1), mvs[1], False))
                else:
                    mbs.append((1, entry(l0, idx0, e0), mvs[0], 0, (0, 0), False))
            while len(l0) < 3:                                           # keep ref_idx as ue(v)
                l0.append(copy)
            while len(l1) < 3:
                l1.append(copy)
            assert len(l0) <= MAX_ENTRIES and len(l1) <= MAX_ENTRIES, (len(l0), len(l1))
            out.append((s, L, Lc, l0, l1, mbs))
        return out

    def mv_extent(self):
        """[min x, max x, min y, max y] of all motion vectors, in luma pixels."""
        ext = [0, 0, 0, 0]
        for _, _, _, _, _, mbs in self.instructions():
            for mb in mbs:
                for (r0, mv0), (r1, mv1) in h264w._quads(mb)[0]:
                    for mv in ([mv0] if r0 >= 0 else []) + ([mv1] if r1 >= 0 else []):
                        x, y = mv[0] / 4, mv[1] / 4
                        ext = [min(ext[0], x), max(ext[1], x), min(ext[2], y), max(ext[3], y)]
        return [int(v) if v == int(v) else v for v in ext]

    # ------------------------------------------------------------------ simulation
    def _eval(self, o, fetch):
        L = [o.L[0], o.L[1], o.L[1]]
        out = np.empty((PLANES, self.H, self.W), np.int32)
        vals = [fetch(src, d, dy, dx) for (src, d, dy, dx) in o.inputs]
        for p in range(PLANES):
            if o.kind == "bi":
                w0, w1, off = o.params[p]
                out[p] = vsim.bi(vals[0][p], vals[1][p], w0, w1, L[p], off)
            else:
                w, off = o.params[p]
                out[p] = vsim.uni(vals[0][p], w, L[p], off)
        return out

    def initial(self, given):
        """Values of every field in the first frame: `given` fields as they are, every other field
        computed once from them (the pipeline full of the same wave), so all phases start alike.
        Picture fields must be given: (y, cb, cr) planes of their size."""
        vals = dict(given)
        for n, f in self.fields.items():
            if f.image:
                assert n in vals, f"picture field {n} needs a starting picture"
        pending = [n for n in self.ops if n not in vals]
        while pending:
            progress = False
            for n in list(pending):
                o = self.ops[n]
                if all(src in vals for (src, _, _, _) in o.inputs):
                    vals[n] = self._eval(o, lambda s, d, dy, dx: np.stack([vsim.shift(v, dy, dx) for v in vals[s]]))
                    pending.remove(n)
                    progress = True
            assert progress, f"cannot order {pending}"
        return vals

    def step(self, history):
        """One frame: every op reads history[-delay]."""
        def fetch(src, d, dy, dx):
            return np.stack([vsim.shift(v, dy, dx) for v in history[-d][src]])
        new = {n: self._eval(o, fetch) for n, o in self.ops.items() if o.kind != "warp"}
        warps = [o for o in self.ops.values() if o.kind == "warp"]
        if warps:
            frames = {d: self.render(history[-d]) for o in warps for d in self._delays(o)}
            for o in warps:
                new[o.out] = self._eval_warp(o, frames)
        return new

    def _warp_tables(self, o):
        """Per read slot (0, 1) and delay: the pixels that read it, an interpolation plan for a reference
        crop holding every sample they touch, and their weights; built once per warp."""
        if o.out in getattr(self, "_tables", {}):
            return self._tables[o.out]
        f = self.fields[o.out]
        fw, fh = f.size_px
        Wp, Hp = self.width_mbs * 16, self.height_mbs * 16
        plan = self.plans[o.out]
        nreads = np.zeros((fh // 8, fw // 8), np.int8)
        cols = {}                         # (slot, delay) -> lists of (block y, block x, mv, wo)
        for (bx, by), quads in plan.items():
            for k, reads in enumerate(quads):
                qy, qx = 2 * by + k // 2, 2 * bx + k % 2
                nreads[qy, qx] = len(reads)
                for slot, (d, mv, wo) in enumerate(reads):
                    cols.setdefault((slot, d), []).append((qy, qx, mv, wo))
        tables = {"nreads": nreads, "reads": []}
        for (slot, d), blocks in sorted(cols.items()):
            qy = np.array([b[0] for b in blocks]); qx = np.array([b[1] for b in blocks])
            mvx = np.array([b[2][0] for b in blocks]); mvy = np.array([b[2][1] for b in blocks])
            # luma: every pixel of every 8x8 block; positions absolute in the frame, in quarter samples
            oy, ox = np.mgrid[0:8, 0:8]
            ly = f.y0 + 8 * qy[:, None, None] + oy
            lx = f.x0 + 8 * qx[:, None, None] + ox
            xq, yq = 4 * lx + mvx[:, None, None], 4 * ly + mvy[:, None, None]
            x_lo, x_hi = max(0, int((xq >> 2).min()) - 3), min(Wp, int((xq >> 2).max()) + 6)
            y_lo, y_hi = max(0, int((yq >> 2).min()) - 3), min(Hp, int((yq >> 2).max()) + 6)
            x_lo, y_lo = x_lo - x_lo % 2, y_lo - y_lo % 2
            x_hi, y_hi = x_hi + x_hi % 2, y_hi + y_hi % 2
            lplan = interp.LumaPlan(y_hi - y_lo, x_hi - x_lo, xq - 4 * x_lo, yq - 4 * y_lo)
            cy, cx = np.mgrid[0:4, 0:4]
            cyy = f.y0 // 2 + 4 * qy[:, None, None] + cy
            cxx = f.x0 // 2 + 4 * qx[:, None, None] + cx
            cplan = interp.ChromaPlan((y_hi - y_lo) // 2, (x_hi - x_lo) // 2, 8 * cxx + mvx[:, None, None] - 4 * x_lo,
                                      8 * cyy + mvy[:, None, None] - 4 * y_lo)
            w = np.array([[b[3][p][0] for p in range(3)] for b in blocks])
            off = np.array([[b[3][p][1] for p in range(3)] for b in blocks])
            tables["reads"].append({"slot": slot, "delay": d, "qy": qy, "qx": qx, "crop": (y_lo, y_hi, x_lo, x_hi),
                                    "luma": lplan, "chroma": cplan, "w": w, "o": off})
        self._tables = getattr(self, "_tables", {})
        self._tables[o.out] = tables
        return tables

    def _eval_warp(self, o, frames):
        f = self.fields[o.out]
        fw, fh = f.size_px
        t = self._warp_tables(o)
        L = [o.L[0], o.L[1], o.L[1]]
        nb = t["nreads"]
        # per plane, per 8x8 block (luma) / 4x4 block (chroma): prediction, weight and offset of each slot
        pred = [[np.zeros((fh // 8, fw // 8, 8, 8), np.int32), np.zeros((fh // 8, fw // 8, 4, 4), np.int32),
                 np.zeros((fh // 8, fw // 8, 4, 4), np.int32)] for _ in range(2)]
        wt = [np.zeros((2, fh // 8, fw // 8), np.int32) for _ in range(3)]
        of = [np.zeros((2, fh // 8, fw // 8), np.int32) for _ in range(3)]
        refs = {}
        for r in t["reads"]:
            y_lo, y_hi, x_lo, x_hi = r["crop"]
            key = (r["delay"], r["crop"])
            if key not in refs:
                Y, Cb, Cr = frames[r["delay"]]
                refs[key] = (interp.LumaRef(Y[y_lo:y_hi, x_lo:x_hi]),
                             interp.ChromaRef(Cb[y_lo // 2:y_hi // 2, x_lo // 2:x_hi // 2]),
                             interp.ChromaRef(Cr[y_lo // 2:y_hi // 2, x_lo // 2:x_hi // 2]))
            lref, cbref, crref = refs[key]
            s, qy, qx = r["slot"], r["qy"], r["qx"]
            pred[s][0][qy, qx] = r["luma"](lref)
            pred[s][1][qy, qx] = r["chroma"](cbref)
            pred[s][2][qy, qx] = r["chroma"](crref)
            for p in range(3):
                wt[p][s, qy, qx] = r["w"][:, p]
                of[p][s, qy, qx] = r["o"][:, p]
        out = []
        for p in range(3):
            Lp = L[p]
            a, b = pred[0][p], pred[1][p]
            w0, w1 = wt[p][0][..., None, None], wt[p][1][..., None, None]
            o0, o1 = of[p][0][..., None, None], of[p][1][..., None, None]
            uni = (((w0 * a + (1 << (Lp - 1))) >> Lp) + o0) if Lp >= 1 else (w0 * a + o0)
            bi = ((w0 * a + w1 * b + (1 << Lp)) >> (Lp + 1)) + ((o0 + o1 + 1) >> 1)
            v = np.clip(np.where((nb == 2)[..., None, None], bi, uni), 0, 255)
            n = 8 if p == 0 else 4
            out.append(v.transpose(0, 2, 1, 3).reshape(fh // 8 * n, fw // 8 * n).astype(np.int32))
        return tuple(out)

    def render(self, vals):
        """Full decoded frame (all planes) for field values at cell resolution; fields missing from
        `vals` show the grey background."""
        Wp, Hp = self.width_mbs * 16, self.height_mbs * 16
        y = np.full((Hp, Wp), self.background[0], np.uint8)
        cb = np.full((Hp // 2, Wp // 2), self.background[1], np.uint8)
        cr = np.full((Hp // 2, Wp // 2), self.background[2], np.uint8)
        for name, f in sorted(self.fields.items(), key=lambda kv: kv[1].image is None):   # pictures first
            if name not in vals:
                continue
            v = vals[name]
            if f.image:
                fw, fh = f.size_px
                y[f.y0:f.y0 + fh, f.x0:f.x0 + fw] = v[0]
                cb[f.y0 // 2:(f.y0 + fh) // 2, f.x0 // 2:(f.x0 + fw) // 2] = v[1]
                cr[f.y0 // 2:(f.y0 + fh) // 2, f.x0 // 2:(f.x0 + fw) // 2] = v[2]
                continue
            if f.halo:
                v = np.pad(v, ((0, 0), (f.halo, f.halo), (f.halo, f.halo)), mode="wrap")
            fw, fh = f.size_px
            y[f.y0:f.y0 + fh, f.x0:f.x0 + fw] = v[0].repeat(2, 0).repeat(2, 1)
            cb[f.y0 // 2:(f.y0 + fh) // 2, f.x0 // 2:(f.x0 + fw) // 2] = v[1]
            cr[f.y0 // 2:(f.y0 + fh) // 2, f.x0 // 2:(f.x0 + fw) // 2] = v[2]
        return y, cb, cr

    # ------------------------------------------------------------------ the stream
    def _pcm_blocks(self, frame, names):
        """{mb_addr: (y, cb, cr) samples} for the macroblocks of the named fields."""
        y, cb, cr = frame
        out = {}
        for (mx, my), name in self.occupied.items():
            if name in names:
                out[my * self.width_mbs + mx] = (y[my * 16:my * 16 + 16, mx * 16:mx * 16 + 16],
                                                 cb[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8],
                                                 cr[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8])
        return out

    def warmup_frame(self, initial_vals, crop_field, f):
        """What warm-up frame f (before the program starts) decodes to."""
        shown = set(self.first_picture).union(*self.pcm_chunks[:f])
        return self.render({n: initial_vals[n] for n in shown})

    def stream(self, initial_vals, n_frames, crop_field, level=51, fps=60, pcm_budget=2_000_000, stored=None,
               first=None):
        """SPS, PPS, then:
        frame 0          IDR: grey, with the displayed field as raw samples (the first picture shown),
        frames 1..c      P: the other stored fields (default: all) as raw samples, in chunks of at most
                         pcm_budget bytes, the rest copied; fields not stored start grey (128), which
                         initial_vals must say too,
        then copies until every delay of the program reads a frame holding the whole starting state,
        then             program frames, from self.first_program_frame on.
        Splitting the raw samples this way keeps every access unit inside the level's size limits.
        first: the fields frame 0 holds as raw samples (default: the cropped field)."""
        first = {crop_field} if first is None else set(first)
        self.first_picture = first
        stored = set(self.fields) if stored is None else set(stored) | first
        for name in set(self.fields) - stored:
            assert all((np.asarray(v) == self.background[0]).all() for v in initial_vals[name]), \
                f"{name} is not stored, so it must start grey"
        Wp, Hp = self.width_mbs * 16, self.height_mbs * 16
        n_mbs = self.width_mbs * self.height_mbs
        c = self.fields[crop_field]
        cx, cy = c.board
        cw, ch = c.shown_px
        crop = (cx, Wp - cx - cw, cy, Hp - cy - ch)
        warm = self.max_delay()
        assert warm >= 1
        self.check()
        full = self.render(initial_vals)
        chunks, cur, size = [], [], 0
        for name, f in self.fields.items():
            if name in first or name not in stored:
                continue
            b = sum(1 for n in self.occupied.values() if n == name) * 384
            if cur and size + b > pcm_budget:
                chunks.append(set(cur))
                cur, size = [], 0
            cur.append(name)
            size += b
        chunks.append(set(cur))
        self.pcm_chunks = chunks
        self.first_program_frame = len(chunks) + warm
        head = h264w.sps(self.width_mbs, self.height_mbs, crop, warm, level, fps) + h264w.pps()
        frames = [head + h264w.idr_mixed(self._pcm_blocks(full, first), self.width_mbs, self.height_mbs)]
        for ch in chunks:
            frames.append(h264w.p_pcm(len(frames), self._pcm_blocks(full, ch), n_mbs))
        while len(frames) < self.first_program_frame:
            frames.append(h264w.p_copy(len(frames), n_mbs))
        slices = self.instructions()
        variants = {}                    # program frames differ only in frame_num, which repeats every 16
        for f in range(self.first_program_frame, n_frames):
            k = f % h264w.MAX_FRAME_NUM
            if k not in variants:
                variants[k] = b"".join(h264w.nal(2, 1, h264w.b_slice(f, first, L, Lc, l0, l1, mbs, self.width_mbs)[0])
                                       for (first, L, Lc, l0, l1, mbs) in slices)
            frames.append(variants[k])
        return frames


def check_level_sizes(m, frames, fps=60):
    """H.264 A.3.1: bytes per access unit at level 5.1 (MaxMBPS 983040, MinCR 2, fR 1/172)."""
    max_mbps, min_cr = 983040, 2
    pic_mbs = m.width_mbs * m.height_mbs
    assert pic_mbs <= 36864 and pic_mbs * fps <= max_mbps, "frame size or macroblock rate above level 5.1"
    n_slices = len(m.slices())
    assert n_slices <= max_mbps / fps / 24, "more slices per picture than level 5.1 allows"
    first = 384 * max(pic_mbs, max_mbps / 172) / min_cr
    later = 384 * max_mbps / fps / min_cr
    assert len(frames[0]) <= first, (len(frames[0]), first)
    worst = max(len(f) for f in frames[1:])
    assert worst <= later, (worst, later)
    print(f"level 5.1: {pic_mbs * fps:,} <= {max_mbps:,} macroblocks/s, {n_slices} slices per program frame, "
          f"frame 0 {len(frames[0]):,} <= {first:,.0f} bytes, largest later frame {worst:,} <= {later:,.0f} bytes")
