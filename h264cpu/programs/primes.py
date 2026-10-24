"""The Wireworld computer's instruction set (David Moore and Mark Owen, 1990-92), built as a circuit of
weighted predictions, running Michael Fryers' prime program from the computer's own register bank.

The machine has one instruction, MOV Rd, Rs, and 64 sixteen-bit registers; some registers compute
(AND-NOT, select, rotate, add, NOT), R63 is the program counter and R0 the display. The program and its
constants live in the registers. Every field is 16 x 64 cells: bit k of register r is cell (r, k), and a
one-word signal holds its word in all 64 rows, so that

    reading Rs   = OR over the rows of (bank AND the row selected by Rs): a butterfly of row shifts,
                   which leaves the word in every row again
    rotating     = reading one column over: the board is a torus, 16 columns around
    adding       = carries running cyclically round the columns: the end-around carry for free

One instruction takes PERIOD frames. https://www.quinapalus.com/wires11.html describes the original.
"""
from __future__ import annotations

import numpy as np

from ..circuit import Circuit, OR_P
from ..layout import anneal
from ..machine import Machine

NAME = "primes"
W, H = 16, 64
M16 = 0xFFFF
# Michael Fryers' program, as listed at https://www.quinapalus.com/wires11.html: register -> word
PROGRAM = {1: 0x001e, 2: 0x361f, 3: 0x2021, 4: 0x3c22, 5: 0x3d23, 6: 0x3c3d, 7: 0x3d20, 8: 0x3924, 9: 0x3725,
           10: 0x383d, 11: 0x3f38, 12: 0x3d3d, 13: 0x3d3d, 14: 0x353d, 15: 0x3926, 16: 0x3727, 17: 0x3836,
           18: 0x3f38, 19: 0x3928, 20: 0x0020, 21: 0x3d20, 22: 0x3c1e, 23: 0x3f29, 24: 0x203d,
           30: 0x0002, 31: 0x7fff, 32: 0x0005, 33: 0x0003, 34: 0xfffe, 35: 0xfffd, 36: 0x0014, 37: 0x000d,
           38: 0x0009, 39: 0x0005, 40: 0x0015, 41: 0x0004, 42: 0xfffc}
REPLICATED = (55, 56, 57, 60, 61)          # registers the select and the adder read as whole words


# ---------------------------------------------------------------------------------- reference model
def add1c(a, b, carry):
    """R60 + R61. The adder feeds its carry out back into bit 0 and runs all the time. When every bit
    only propagates (b == ~a), nothing decides the circulating carry, so it keeps its last value: then
    a + ~a is 0x0000 ('plus zero') if a carry was circulating, 0xffff otherwise."""
    if a ^ b == M16:
        return (0 if carry else M16), carry
    s = a + b
    return (s & M16) + (s >> 16), s >> 16


def read(r, s, carry):
    if s in (0, 55, 57):
        return 0
    if s == 53:
        return r[54] & ~r[53] & M16
    if s == 54:
        return r[53] & ~r[54] & M16
    if s == 56:
        return r[55] if r[56] else r[57]
    if s == 58:
        return ((r[58] >> 1) | (r[58] << 15)) & M16
    if s == 59:
        return ((r[59] << 1) | (r[59] >> 15)) & M16
    if s == 61:
        return add1c(r[60], r[61], carry)[0]
    if s == 62:
        return ~r[62] & M16
    return r[s]                                    # 1..52, 60, and 63, the program counter


class CPU:
    """State: r[0..63] (r[63] is the program counter), the prefetched instruction, the display, and the
    adder's circulating carry."""

    def __init__(self, program=PROGRAM):
        self.r = [0] * 64
        for k, v in program.items():
            self.r[k] = v
        self.r[63] = 1                             # execution starts from register 1
        self.carry, self.display = 0, 0
        self.ir = self.fetch()

    def fetch(self):
        ir = self.r[self.r[63]]
        self.r[63] = (self.r[63] + 1) & M16
        return ir

    def step(self):
        """One instruction: execute the prefetched one while fetching the next (one branch delay slot)."""
        src, dst = self.ir & 63, (self.ir >> 8) & 63
        self.carry = add1c(self.r[60], self.r[61], self.carry)[1]
        v = read(self.r, src, self.carry)
        nxt = self.fetch()
        if dst == 0:
            self.display = v
        elif dst == 63:
            self.r[63] = v
        else:
            self.r[dst] = v
        self.ir = nxt
        return self

    def array(self):
        return np.array(self.r + [self.ir, self.display, self.carry], np.int64)

    @classmethod
    def of(cls, a):
        c = cls.__new__(cls)
        c.r = [int(v) for v in a[:64]]
        c.ir, c.display, c.carry = int(a[64]), int(a[65]), int(a[66])
        return c


def primes_shown(n_instructions):
    """[(instruction, value)] for every value the program writes to the display."""
    c, out = CPU(), []
    for i in range(1, n_instructions + 1):
        d = c.display
        c.step()
        if c.display != d:
            out.append((i, c.display))
    return out


# ---------------------------------------------------------------------------------- the circuit
def word(v):
    """A one-word signal: bit k of v in column k, the same in every row."""
    return np.tile(255 * ((v >> np.arange(W)) & 1), (H, 1))


def rows_except(rows):
    """255 everywhere except the given rows: a mask that ANDNOT clears outside them."""
    a = np.full((H, W), 255)
    a[list(rows)] = 0
    return a


def decoder(c, name, x, base, pattern, kill_rows=(), kill_col=None):
    """Not-match: in row r, 0 if bits base..base+5 of word x equal pattern[r], else 255 (in every
    column). Killed rows never match, through a bit that is 0 in every instruction (kill_col)."""
    c1, c2 = np.full((H, W), 255), np.zeros((H, W), np.int32)
    for r in range(H):
        for k in range(6):
            c1[r, base + k] = c2[r, base + k] = 255 * ((pattern[r] >> k) & 1)
        if r in kill_rows:
            c2[r, kill_col] = 255
    m1, m2 = c.const(name + "c1", c1), c.const(name + "c2", c2)
    mm = c.OR(name + "x", c.ANDNOT(name + "x1", x, m1), c.ANDNOT(name + "x2", m2, x))
    return c.reduce(name, mm, axis=1)


def circuit():
    c = Circuit(W, H)
    cpu = CPU()
    bank = np.zeros((H, W), np.int64)
    for r in range(1, 63):
        bank[r] = 255 * ((cpu.r[r] >> np.arange(W)) & 1)
    B = c.state("B", bank)
    IR, PC = c.state("IR", word(cpu.ir)), c.state("PC", word(cpu.r[63]))
    C, DISP = c.state("C", np.zeros((H, W))), c.state("DISP", np.zeros((H, W)))
    R = {k: c.state(f"R{k}", word(cpu.r[k])) for k in REPLICATED}
    rows = np.arange(H)

    # decoders: which register the instruction reads, which it writes, and where the next one is
    nsrc = decoder(c, "nsrc", IR, 0, rows, kill_rows=(0, 55, 56, 57, 61), kill_col=6)
    ndst = decoder(c, "ndst", IR, 8, rows, kill_rows=(0, 63), kill_col=14)
    npc = decoder(c, "npc", PC, 0, rows)
    ns56, ns61 = (decoder(c, f"ns{k}", IR, 0, np.full(H, k)) for k in (56, 61))
    nd = {k: decoder(c, f"nd{k}", IR, 8, np.full(H, k)) for k in (0, 55, 56, 57, 60, 61, 63)}

    # what each register reads as, in its own row: the bank, and R53, R54, R58, R59, R62, R63 computed
    nr = {k: c.const(f"nr{k}", rows_except([k])) for k in (53, 54, 58, 59, 63)}
    gen = c.ANDNOT("tgen", B, c.const("nrgen", rows_except(list(range(1, 53)) + [60])))
    x53 = c.ANDNOT("x53", B.at(1, 0), c.OR("x53m", B, nr[53]))             # R54 AND NOT R53
    x54 = c.ANDNOT("x54", B.at(-1, 0), c.OR("x54m", B, nr[54]))            # R53 AND NOT R54
    x58 = c.ANDNOT("x58", B.at(0, 1), nr[58])                              # R58 rotated right
    x59 = c.ANDNOT("x59", B.at(0, -1), nr[59])                             # R59 rotated left
    row62 = np.zeros((H, W)); row62[62] = 255
    x62 = c.ANDNOT("x62", c.const("row62", row62), B)                      # NOT R62
    x63 = c.ANDNOT("x63", PC, nr[63])                                      # the program counter
    ra = c.OR("ra", c.OR("ra1", c.OR("ra11", gen, x58), c.OR("ra12", x59, x62)),
              c.OR("ra2", c.OR("ra21", x53, x54), x63))
    valgen = c.reduce("valgen", c.ANDNOT("sel", ra, nsrc), axis=0)

    # R56: R55 if R56 is not zero, else R57
    nz = c.reduce("nz56", R[56], axis=1)
    v56 = c.ANDNOT("v56g", c.MUX("v56", nz, c.NOT("nnz56", nz), R[55], R[57]), ns56)

    # R61: R60 + R61, carries cyclic, with the circulating carry C when every bit propagates
    a, b = R[60], R[61]
    g = c.ANDNOT("g0", a, c.NOT("nb", b))                                  # generate: a AND b
    na = c.NOT("na", a)
    p0 = c.OR("p0", c.ANDNOT("p0a", a, b), c.ANDNOT("p0b", b, a))          # propagate: a XOR b
    np_ = c.OR("np0", g, c.ANDNOT("k0", na, b))                            # not propagate
    s = 1
    while s < W:
        g = c.OR(f"g{s}", g, c.ANDNOT(f"t{s}", g.at(0, -s), np_))
        np_ = c.OR(f"np{s}", np_, np_.at(0, -s))
        s *= 2
    carry = c.OR("carry", g.at(0, -1), c.ANDNOT("circ", C, np_))           # carry into each bit
    term1 = c.ANDNOT("sum1", c.ANDNOT("p0g", p0, ns61), carry)             # p AND NOT carry
    term2 = c.ANDNOT("sum2", carry, c.OR("p0n", p0, ns61))                 # carry AND NOT p
    col0 = np.full((H, W), 255); col0[:, 0] = 0
    c.reduce("cnext", c.ANDNOT("c0", carry, c.const("ncol0", col0)), axis=1, into=C)

    val = c.OR("val", c.OR("val1", term1, term2), c.OR("val2", valgen, v56))

    # writes: the bank, the word copies, the display, the program counter
    c.set(B, [c.ANDNOT("keep", B, c.NOT("seld", ndst)), c.ANDNOT("put", val, ndst)], OR_P)
    for k in REPLICATED:
        c.set(R[k], [c.ANDNOT(f"put{k}", val, nd[k]), c.ANDNOT(f"keep{k}", R[k], c.NOT(f"d{k}", nd[k]))], OR_P)
    c.set(DISP, [c.ANDNOT("put0", val, nd[0]), c.ANDNOT("keep0", DISP, c.NOT("d0", nd[0]))], OR_P)
    # PC + 1: bit k flips when every bit below it is 1
    npcw = c.NOT("npcw", PC)
    lt = {}
    for sh in (1, 2, 4, 8):                                                  # 255 in the columns below sh
        a_ = np.full((H, W), 255); a_[:, sh:] = 0
        lt[sh] = c.const(f"lt{sh}", a_)
    y = c.ANDNOT("z", npcw.at(0, -1), lt[1])                                 # the bit just below is 0
    for sh in (1, 2, 4, 8):                                                  # ... or any bit below
        y = c.OR(f"z{sh}", y, c.ANDNOT(f"zt{sh}", y.at(0, -sh), lt[sh]))
    ones = c.NOT("ones", y)                                                  # every bit below is 1
    inc = c.OR("inc", c.ANDNOT("inc1", PC, ones), c.ANDNOT("inc2", npcw, y))
    c.set(PC, [c.ANDNOT("put63", val, nd[63]), c.ANDNOT("keep63", inc, c.NOT("d63", nd[63]))], OR_P)
    # fetch: the next instruction is the bank row the program counter selects
    c.reduce("fetch", c.ANDNOT("fsel", B, npc), axis=0, into=IR)
    display(c, DISP)
    return c


# ---------------------------------------------------------------------------------- the display
DIGITS = 5
SEGMENTS = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc",
            8: "abcdefg", 9: "abcdfg"}


def display(c, disp):
    """Seven-segment signals for the display register, in decimal: {segment: signal}, where rows
    4j..4j+3 of a segment's signal hold, in every column, whether digit j (units first) lights it.

    Bit k of the register adds the decimal digits of 2^k to the digit sums (at most 144 each); then five
    carry steps, each digit's carry being the number of thresholds 10, 20, ... 150 its sum reaches."""
    block = np.arange(H) // 4                                    # the digit a row belongs to
    dec = np.zeros((H, W), np.int32)
    for j in range(DIGITS):
        dec[block == j] = [(1 << k) // 10 ** j % 10 for k in range(W)]
    ndisp = c.NOT("ndisp", disp)
    sums = c.reduce("dsum", c.ANDNOT("dterm", c.const("dec", dec), ndisp), axis=1)     # digit sums
    tens = c.const("tens", np.tile([255] + [10 * m for m in range(1, W)], (H, 1)))
    x, q = sums, None
    for t in range(DIGITS):
        if q is not None:
            x = c.op(f"dx{t}", [sums, q.at(-4, 0)], (2, 2, 0))                # sum + carry from below
        short = c.op(f"dshort{t}", [tens, x], (2, -2, 0))                   # 10m - x, or 0 once reached
        reached = c.op(f"dge{t}", [short], (-1, 1))                         # 1 where x >= 10m
        q = c.reduce(f"dq{t}", reached, axis=1)                             # x // 10
    digit = c.op("digit", [x, q], (2, -20, 0))                              # x - 10 (x // 10)
    v = c.const("dv", np.tile(np.arange(W), (H, 1)))
    dist = c.OR("ddist", c.op("dlo", [digit, v], (2, -2, 0)), c.op("dhi", [v, digit], (2, -2, 0)))
    eq = c.op("deq", [c.K, c.op("dfar", [dist], (64, 0))], (2, -8, 0))      # 255 where digit == column
    c.const("KD", np.full((H, W), 255))                                     # the picture's constant
    segs = {}
    for seg in "abcdefg":
        lit = np.full((H, W), 255)
        for d, on in SEGMENTS.items():
            if seg in on:
                lit[:, d] = 0
        segs[seg] = c.reduce(f"seg{seg}", c.ANDNOT(f"segm{seg}", eq, c.const(f"nsm{seg}", lit)), axis=1)
    return segs


def rgb_to_ycbcr(rgb):
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b, 128 - 0.168736 * r - 0.331264 * g + 0.5 * b,
            128 + 0.5 * r - 0.418688 * g - 0.081312 * b)


LIT, UNLIT, BACKGROUND = (255, 64, 36), (40, 12, 10), (10, 8, 8)
BLOCK = 8                                   # the picture is drawn in 8x8 blocks
# segments of a digit 10 blocks wide and 18 tall, 2 blocks thick: (x, y, w, h) in blocks
SEGMENT_RECTS = {"a": (2, 0, 6, 2), "f": (0, 2, 2, 6), "b": (8, 2, 2, 6), "g": (2, 8, 6, 2),
                 "e": (0, 10, 2, 6), "c": (8, 10, 2, 6), "d": (2, 16, 6, 2)}
MARGIN, GAP, DIGIT_W, DIGIT_H = 4, 4, 10, 18
PIC_W = BLOCK * (2 * MARGIN + DIGITS * DIGIT_W + (DIGITS - 1) * GAP)
PIC_H = BLOCK * (2 * MARGIN + DIGIT_H)


def colour_params(on, off):
    """Per plane, list 0 and list 1 (weight, offset) for bi(segment, K) at L = 6: off for 0, on for 255."""
    out = []
    for p in range(3):
        a, b = on[p], off[p]
        w0 = round((a - b) * 128 / 255)
        o = int(max(-128, min(127, round(b))))
        w1 = round((b - o) * 128 / 255)
        out.append(((w0, o), (w1, o)))
    return out


def picture_plan(m):
    """The display: every 8x8 block reads its segment signal (the row block of its digit) and the
    constant KD, or, off the segments, KD alone for the background."""
    segs = {s: m.fields[f"seg{s}"] for s in "abcdefg"}
    k = m.fields["KD"]
    seg_w = colour_params(rgb_to_ycbcr(LIT), rgb_to_ycbcr(UNLIT))
    bg = rgb_to_ycbcr(BACKGROUND)
    bg_w = tuple((round((v - max(-128, min(127, round(v)))) * 64 / 255), int(max(-128, min(127, round(v))))) for v in bg)
    owner = {}
    for j in range(DIGITS):
        x0 = MARGIN + (DIGITS - 1 - j) * (DIGIT_W + GAP)                    # units on the right
        for seg, (x, y, w, h) in SEGMENT_RECTS.items():
            for by in range(y, y + h):
                for bx in range(x, x + w):
                    owner[(x0 + bx, MARGIN + by)] = (seg, j)
    D = m.fields[CROP]

    def mv(px, py, f, row):
        sx, sy = f.board
        return (4 * (sx - px), 4 * (sy + 2 * row - py))

    plan = {}
    for my in range(PIC_H // 16):
        for mx in range(PIC_W // 16):
            quads = []
            for q in range(4):
                bx, by = 2 * mx + q % 2, 2 * my + q // 2
                px, py = D.x0 + BLOCK * bx, D.y0 + BLOCK * by
                if (bx, by) in owner:
                    seg, j = owner[(bx, by)]
                    w = seg_w
                    quads.append(((1, mv(px, py, segs[seg], 4 * j), tuple(w[p][0] for p in range(3))),
                                  (1, mv(px, py, k, 0), tuple(w[p][1] for p in range(3)))))
                else:
                    quads.append(((1, mv(px, py, k, 0), bg_w),))
            plan[(mx, my)] = quads
    return plan


# ---------------------------------------------------------------------------------- the machine
PERIOD = 17                                # frames per instruction (checked against the circuit)
CROP = "D"
WIDTH_MBS = 128


def bands(m, top, width_px):
    """Slots in bands under the top `top` pixels: 160-pixel bands of 64-pixel slots for fields with a
    halo, 128-pixel bands of 32-pixel slots for the rest, alternating, as many as the fields need."""
    need = {8: sum(1 for f in m.fields.values() if f.x0 is None and f.halo),
            0: sum(1 for f in m.fields.values() if f.x0 is None and not f.halo)}
    slots, y = [], top
    while need[8] > 0 or need[0] > 0:
        for halo, (sw, sh) in ((8, (64, 160)), (0, (32, 128))):
            if need[halo] <= 0:
                continue
            n = width_px // sw
            slots += [(i * sw, y, halo) for i in range(n)]
            need[halo] -= n
            y += sh
    return slots, -(-y // 16)


def build(iters=200000, seed=0):
    c = circuit()
    m = Machine(W, H, WIDTH_MBS, 1)
    assert c.compile(m) == PERIOD
    m.image(CROP, PIC_W, PIC_H)
    m.warp(CROP, picture_plan, L=(6, 6))       # an unused macroblock in its slice copies with weight 2^L
    m.place(CROP, 0, 0)
    # beside the picture: plain fields in 128-pixel rows, first the ones it reads; then bands below it
    beside = [(x, y, 0) for y in range(0, PIC_H - 127, 128) for x in range(PIC_W, WIDTH_MBS * 16 - 31, 32)]
    for name in ["KD"] + [f"seg{s}" for s in "abcdefg"]:
        m.place(name, *beside.pop(0)[:2])
    slots, height_mbs = bands(m, PIC_H, WIDTH_MBS * 16)
    m.height_mbs = height_mbs
    anneal(m, beside + slots, {n: f.halo for n, f in m.fields.items() if f.x0 is None}, iters, seed)
    m.check()
    m.circuit = c
    return m


def read_state(m, y):
    """The CPU state in a decoded luma plane, as CPU.array() gives it."""
    def bits(name):
        sx, sy = m.fields[name].board
        cells = y[sy:sy + 2 * H:2, sx:sx + 2 * W:2] > 127
        return (cells.astype(np.int64) << np.arange(W)).sum(1)
    r = list(bits("B"))
    r[0], r[63] = 0, int(bits("PC")[0])
    return np.array(r + [int(bits("IR")[0]), int(bits("DISP")[0]), int(bits("C")[0] & 1)], np.int64)


def start(m):
    blank = tuple(np.zeros((h, w), np.int32) for (h, w) in ((PIC_H, PIC_W), (PIC_H // 2, PIC_W // 2), (PIC_H // 2, PIC_W // 2)))
    init = m.initial({**m.circuit.given(), CROP: blank})
    init[CROP] = m._eval_warp(m.ops[CROP], {1: m.render(init)})      # the display as the first frame shows it
    step = lambda a: CPU.of(a).step().array()
    return init, None, (PERIOD, CPU().array(), step, read_state)
