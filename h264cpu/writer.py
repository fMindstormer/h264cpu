"""A small H.264 writer: just enough of the standard to make a video decoder compute.

Main profile, CAVLC, progressive frames, 4:2:0, 8-bit. It writes:
  * IDR frames that are flat mid-grey (Intra 16x16 DC prediction, no residual) except for chosen
    I_PCM macroblocks (raw samples),
  * P frames whose macroblocks are skipped (exact copies of the previous frame) except for chosen
    I_PCM macroblocks,
  * B frames whose macroblocks are skipped, B_L0/L1/Bi_16x16, or B_8x8 with L0/L1/Bi 8x8 sub-macroblocks,
    with quarter-sample motion vectors, no residual, explicit weighted prediction, and reference lists
    rebuilt by modification commands (the same picture may appear many times, each time with its own
    weights and offsets).
The in-loop deblocking filter is switched off in every slice, so predictions are never smoothed.
"""
from __future__ import annotations

import re

import numpy as np

LOG2_MAX_FRAME_NUM = 4            # frame_num counts 0..15 and wraps; at most 8 reference frames are kept
MAX_FRAME_NUM = 1 << LOG2_MAX_FRAME_NUM


class Bits:
    def __init__(self):
        self.buf = bytearray()
        self.cur = 0
        self.n = 0

    def u(self, nbits, value):
        for i in range(nbits - 1, -1, -1):
            self.cur = (self.cur << 1) | ((value >> i) & 1)
            self.n += 1
            if self.n == 8:
                self.buf.append(self.cur)
                self.cur = 0
                self.n = 0

    def ue(self, v):
        assert v >= 0
        v1 = v + 1
        L = v1.bit_length() - 1
        self.u(L, 0)
        self.u(L + 1, v1)

    def se(self, v):
        self.ue(2 * v - 1 if v > 0 else -2 * v)

    def te(self, cmax, v):
        if cmax > 1:
            self.ue(v)
        else:
            self.u(1, 1 - v)

    def align(self):
        while self.n:
            self.u(1, 0)

    def trailing(self):
        self.u(1, 1)
        self.align()

    def raw(self, data):
        assert self.n == 0
        self.buf.extend(data)

    def bitpos(self):
        return len(self.buf) * 8 + self.n

    def getvalue(self):
        assert self.n == 0
        return bytes(self.buf)


_EP = re.compile(b"\x00\x00(?=[\x00-\x03])")


def nal(ref_idc, nal_type, rbsp: bytes) -> bytes:
    """Annex B: start code, header byte, payload with emulation prevention bytes."""
    return b"\x00\x00\x00\x01" + bytes([(ref_idc << 5) | nal_type]) + _EP.sub(b"\x00\x00\x03", rbsp)


def sps(width_mbs, height_mbs, crop, num_ref_frames, level=51, fps=60):
    """crop = (left, right, top, bottom) in luma pixels (even)."""
    b = Bits()
    b.u(8, 77)                    # profile_idc: Main
    b.u(8, 0)                     # constraint flags + reserved
    b.u(8, level)
    b.ue(0)                       # seq_parameter_set_id
    b.ue(LOG2_MAX_FRAME_NUM - 4)
    b.ue(2)                       # pic_order_cnt_type 2: output order = decoding order
    b.ue(num_ref_frames)
    b.u(1, 0)                     # gaps_in_frame_num_value_allowed_flag
    b.ue(width_mbs - 1)
    b.ue(height_mbs - 1)
    b.u(1, 1)                     # frame_mbs_only_flag
    b.u(1, 1)                     # direct_8x8_inference_flag
    if any(crop):
        b.u(1, 1)
        for c in crop:
            assert c % 2 == 0
            b.ue(c // 2)
    else:
        b.u(1, 0)
    b.u(1, 1)                     # vui_parameters_present_flag
    b.u(1, 0)                     # aspect_ratio_info_present_flag
    b.u(1, 0)                     # overscan_info_present_flag
    b.u(1, 1)                     # video_signal_type_present_flag
    b.u(3, 5)                     # video_format: unspecified
    b.u(1, 1)                     # video_full_range_flag
    b.u(1, 1)                     # colour_description_present_flag
    b.u(8, 1), b.u(8, 1), b.u(8, 6)   # BT.709 primaries and transfer, BT.601 matrix
    b.u(1, 0)                     # chroma_loc_info_present_flag
    b.u(1, 1)                     # timing_info_present_flag
    b.u(32, 1)                    # num_units_in_tick
    b.u(32, 2 * fps)              # time_scale
    b.u(1, 1)                     # fixed_frame_rate_flag
    b.u(1, 0), b.u(1, 0)          # no HRD parameters
    b.u(1, 0)                     # pic_struct_present_flag
    b.u(1, 1)                     # bitstream_restriction_flag
    b.u(1, 1)                     # motion_vectors_over_pic_boundaries_flag
    b.ue(0), b.ue(0)              # max_bytes_per_pic_denom, max_bits_per_mb_denom
    b.ue(15), b.ue(15)            # log2_max_mv_length horizontal, vertical
    b.ue(0)                       # max_num_reorder_frames
    b.ue(num_ref_frames)          # max_dec_frame_buffering
    b.trailing()
    return nal(3, 7, b.getvalue())


def pps():
    b = Bits()
    b.ue(0)                       # pic_parameter_set_id
    b.ue(0)                       # seq_parameter_set_id
    b.u(1, 0)                     # entropy_coding_mode_flag: CAVLC
    b.u(1, 0)                     # bottom_field_pic_order_in_frame_present_flag
    b.ue(0)                       # num_slice_groups_minus1
    b.ue(0), b.ue(0)              # num_ref_idx_l0/l1_default_active_minus1
    b.u(1, 0)                     # weighted_pred_flag (P frames are plain copies)
    b.u(2, 1)                     # weighted_bipred_idc: explicit weights in B slices
    b.se(0), b.se(0), b.se(0)     # pic_init_qp, pic_init_qs, chroma_qp_index_offset
    b.u(1, 1)                     # deblocking_filter_control_present_flag
    b.u(1, 0)                     # constrained_intra_pred_flag
    b.u(1, 0)                     # redundant_pic_cnt_present_flag
    b.trailing()
    return nal(3, 8, b.getvalue())


def idr_pcm(y, cb, cr):
    """One IDR frame of I_PCM macroblocks. y: (H, W) uint8, cb, cr: (H/2, W/2)."""
    H, W = y.shape
    b = Bits()
    b.ue(0)                       # first_mb_in_slice
    b.ue(7)                       # slice_type: I (all slices)
    b.ue(0)                       # pic_parameter_set_id
    b.u(LOG2_MAX_FRAME_NUM, 0)    # frame_num
    b.ue(0)                       # idr_pic_id
    b.u(1, 0), b.u(1, 0)          # no_output_of_prior_pics_flag, long_term_reference_flag
    b.se(0)                       # slice_qp_delta
    b.ue(1)                       # disable_deblocking_filter_idc
    for my in range(H // 16):
        for mx in range(W // 16):
            b.ue(25)              # mb_type I_PCM
            b.align()             # pcm_alignment_zero_bit
            b.raw(y[my * 16:my * 16 + 16, mx * 16:mx * 16 + 16].tobytes())
            b.raw(cb[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8].tobytes())
            b.raw(cr[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8].tobytes())
    b.trailing()
    return nal(3, 5, b.getvalue())


def _pcm_mb(b, blocks):
    b.align()                     # pcm_alignment_zero_bit
    for blk in blocks:            # 16x16 luma, 8x8 Cb, 8x8 Cr, each in raster order
        b.raw(np.ascontiguousarray(blk, np.uint8).tobytes())


def idr_mixed(pcm, width_mbs, height_mbs):
    """An IDR frame: I_PCM where `pcm` ({mb_addr: (y16x16, cb8x8, cr8x8)}) has samples, flat grey elsewhere.

    A grey macroblock is Intra 16x16 DC prediction with no residual, which averages its left and top
    neighbours (128 when it has none). A new slice starts wherever grey follows PCM, so inside a slice
    all grey macroblocks come before all PCM ones and only ever see grey: every one is exactly 128 in
    all three planes. Keeps the first access unit far below the level's size limit (MinCR)."""
    n = width_mbs * height_mbs
    starts = [0] + [a for a in range(1, n) if a not in pcm and (a - 1) in pcm]
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else n
        b = Bits()
        b.ue(s)                   # first_mb_in_slice
        b.ue(7)                   # slice_type: I (all slices)
        b.ue(0)                   # pic_parameter_set_id
        b.u(LOG2_MAX_FRAME_NUM, 0)
        b.ue(0)                   # idr_pic_id (same in every slice of the picture)
        b.u(1, 0), b.u(1, 0)      # no_output_of_prior_pics_flag, long_term_reference_flag
        b.se(0)                   # slice_qp_delta
        b.ue(1)                   # disable_deblocking_filter_idc
        for a in range(s, e):
            if a in pcm:
                b.ue(25)          # mb_type I_PCM
                _pcm_mb(b, pcm[a])
            else:
                b.ue(3)           # mb_type I_16x16_2_0_0: DC prediction, no coded blocks
                b.ue(0)           # intra_chroma_pred_mode: DC
                b.se(0)           # mb_qp_delta
                b.u(1, 1)         # Intra16x16DCLevel coeff_token: no coefficients (nC = 0)
        b.trailing()
        out.append(nal(3, 5, b.getvalue()))
    return b"".join(out)


def p_pcm(frame_num, pcm, n_mbs):
    """A P frame: I_PCM where `pcm` has samples, skipped elsewhere. Every skipped macroblock gets
    motion vector 0 (its neighbours are skipped with 0 or intra), so it copies the previous frame."""
    b = Bits()
    b.ue(0), b.ue(5), b.ue(0)
    b.u(LOG2_MAX_FRAME_NUM, frame_num % MAX_FRAME_NUM)
    b.u(1, 1), b.ue(0)            # one reference: the previous frame
    b.u(1, 0)                     # ref_pic_list_modification_flag_l0
    b.u(1, 0)                     # adaptive_ref_pic_marking_mode_flag
    b.se(0), b.ue(1)
    run = 0
    for a in range(n_mbs):
        if a in pcm:
            b.ue(run)             # mb_skip_run
            run = 0
            b.ue(30)              # mb_type I_PCM in a P slice
            _pcm_mb(b, pcm[a])
        else:
            run += 1
    if run:
        b.ue(run)
    b.trailing()
    return nal(2, 1, b.getvalue())


def i_pcm(frame_num, y, cb, cr):
    """A non-IDR frame of I_PCM macroblocks (used to give tests different reference pictures)."""
    H, W = y.shape
    b = Bits()
    b.ue(0), b.ue(7), b.ue(0)
    b.u(LOG2_MAX_FRAME_NUM, frame_num % MAX_FRAME_NUM)
    b.u(1, 0)                     # adaptive_ref_pic_marking_mode_flag
    b.se(0), b.ue(1)
    for my in range(H // 16):
        for mx in range(W // 16):
            b.ue(25)
            b.align()
            b.raw(y[my * 16:my * 16 + 16, mx * 16:mx * 16 + 16].tobytes())
            b.raw(cb[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8].tobytes())
            b.raw(cr[my * 8:my * 8 + 8, mx * 8:mx * 8 + 8].tobytes())
    b.trailing()
    return nal(2, 1, b.getvalue())


def p_copy(frame_num, n_mbs):
    """A P frame in which every macroblock is skipped: an exact copy of the previous frame."""
    b = Bits()
    b.ue(0)                       # first_mb_in_slice
    b.ue(5)                       # slice_type: P (all slices)
    b.ue(0)                       # pic_parameter_set_id
    b.u(LOG2_MAX_FRAME_NUM, frame_num % MAX_FRAME_NUM)
    b.u(1, 1)                     # num_ref_idx_active_override_flag
    b.ue(0)                       # one reference: the previous frame
    b.u(1, 0)                     # ref_pic_list_modification_flag_l0
    b.u(1, 0)                     # adaptive_ref_pic_marking_mode_flag: sliding window
    b.se(0)                       # slice_qp_delta
    b.ue(1)                       # disable_deblocking_filter_idc
    b.ue(n_mbs)                   # mb_skip_run: everything
    b.trailing()
    return nal(2, 1, b.getvalue())


# ------------------------------------------------------------------------------------------ B slices
class Entry:
    """One reference list entry: a picture `delay` frames back, with weights and offsets per plane."""

    def __init__(self, delay, wo):
        self.delay = delay
        self.wo = tuple(tuple(x) for x in wo)        # ((wY, oY), (wCb, oCb), (wCr, oCr))

    def key(self):
        return (self.delay, self.wo)


def _list_modification(b, delays):
    """Commands that build the list [frame - d for d in delays] in order; relative, so identical every frame."""
    b.u(1, 1)
    pred_back = 0                                    # picNumPred starts at CurrPicNum: 0 frames back
    for d in delays:
        diff = (d - pred_back) % MAX_FRAME_NUM       # step backwards; 0 means a full wrap to the same picture
        b.ue(0)                                      # modification_of_pic_nums_idc 0: subtract
        b.ue((diff - 1) % MAX_FRAME_NUM)             # abs_diff_pic_num_minus1
        pred_back = d
    b.ue(3)


class Quads:
    """A macroblock whose 8x8 quadrants may move differently: parts are 4 (pred, ref0, mv0, ref1, mv1) in
    the order top-left, top-right, bottom-left, bottom-right, with motion vectors in quarter luma samples."""

    def __init__(self, parts, copy_ok=False):
        assert len(parts) == 4
        self.parts = tuple(parts)
        self.copy_ok = copy_ok


def _quads(mb):
    """((ref0, mv0), (ref1, mv1)) for each 8x8 quadrant, vectors in quarter samples; ref -1: list unused."""
    if isinstance(mb, Quads):
        parts, copy_ok = mb.parts, mb.copy_ok
    else:                                            # (pred, ref0, mv0, ref1, mv1[, copy_ok]), whole samples
        pred, r0, mv0, r1, mv1 = mb[:5]
        copy_ok = len(mb) > 5 and mb[5]
        parts = [(pred, r0, (4 * mv0[0], 4 * mv0[1]), r1, (4 * mv1[0], 4 * mv1[1]))] * 4
    return tuple(((r0, tuple(mv0)) if pred & 1 else (-1, (0, 0)),
                  (r1, tuple(mv1)) if pred & 2 else (-1, (0, 0))) for pred, r0, mv0, r1, mv1 in parts), copy_ok


def b_slice(frame_num, first_mb, L, Lc, l0, l1, mbs, width_mbs, skip=True, stats=None):
    """mbs: consecutive macroblocks from first_mb, each either (pred, ref0, mv0, ref1, mv1[, copy_ok]) with
    whole-sample vectors (pred 1: list 0, 2: list 1, 3: both) or a Quads with quarter-sample vectors.

    A macroblock whose quadrants all move alike is coded as one 16x16 partition, otherwise as B_8x8 with
    B_L0_8x8 / B_L1_8x8 / B_Bi_8x8 sub-macroblocks. With skip, it is coded as B_Skip (part of a run,
    almost free) whenever spatial direct prediction derives exactly its references and vectors. copy_ok
    marks a macroblock that only has to copy the previous frame in place: any derivation using reference
    index 0 with zero motion will do. This relies on index 0 of both lists being that copy and being used
    only with zero motion, so the co-located zero-motion rule of direct prediction never changes a result.
    stats, if given, counts the macroblocks coded as "skip", "16x16" and "8x8"."""
    b = Bits()
    b.ue(first_mb)
    b.ue(6)                                          # slice_type: B (all slices)
    b.ue(0)
    b.u(LOG2_MAX_FRAME_NUM, frame_num % MAX_FRAME_NUM)
    b.u(1, 1)                                        # direct_spatial_mv_pred_flag
    b.u(1, 1)                                        # num_ref_idx_active_override_flag
    b.ue(len(l0) - 1)
    b.ue(len(l1) - 1)
    _list_modification(b, [e.delay for e in l0])
    _list_modification(b, [e.delay for e in l1])
    b.ue(L)                                          # luma_log2_weight_denom
    b.ue(Lc)                                         # chroma_log2_weight_denom
    for lst in (l0, l1):
        for e in lst:
            (wy, oy), (wb, ob), (wr, or_) = e.wo
            b.u(1, 1), b.se(wy), b.se(oy)
            b.u(1, 1), b.se(wb), b.se(ob), b.se(wr), b.se(or_)
    b.u(1, 0)                                        # adaptive_ref_pic_marking_mode_flag
    b.se(0)                                          # slice_qp_delta
    b.ue(1)                                          # disable_deblocking_filter_idc
    header_bits = b.bitpos()
    info = {}                                        # macroblock address -> its quadrants
    n = (len(l0), len(l1))
    run = 0
    for i, mb in enumerate(mbs):
        addr = first_mb + i
        quads, copy_ok = _quads(mb)
        if skip:
            d = _direct(info, addr, first_mb, width_mbs)
            if d == quads or (copy_ok and _is_copy(d[0])):
                run += 1
                info[addr] = d
                if stats is not None:
                    stats["skip"] = stats.get("skip", 0) + 1
                continue
        b.ue(run)                                    # mb_skip_run
        run = 0
        preds = [(q[0][0] >= 0) | ((q[1][0] >= 0) << 1) for q in quads]
        if stats is not None:
            k = "16x16" if all(q == quads[0] for q in quads) else "8x8"
            stats[k] = stats.get(k, 0) + 1
        if all(q == quads[0] for q in quads):
            b.ue(preds[0])                           # mb_type B_L0_16x16 / B_L1_16x16 / B_Bi_16x16
            for X in (0, 1):
                if preds[0] & (1 << X) and n[X] > 1:
                    b.te(n[X] - 1, quads[0][X][0])
            for X in (0, 1):
                if preds[0] & (1 << X):
                    ref, mv = quads[0][X]
                    p = _mvp(info, addr, first_mb, width_mbs, {}, 0, 0, 16, X, ref)
                    b.se(mv[0] - p[0])
                    b.se(mv[1] - p[1])
        else:
            b.ue(22)                                 # mb_type B_8x8
            for pr in preds:
                b.ue(pr)                             # sub_mb_type B_L0_8x8 / B_L1_8x8 / B_Bi_8x8
            for X in (0, 1):
                for q, pr in zip(quads, preds):
                    if pr & (1 << X) and n[X] > 1:
                        b.te(n[X] - 1, q[X][0])
            for X in (0, 1):
                done = {}
                for k, (q, pr) in enumerate(zip(quads, preds)):
                    if pr & (1 << X):
                        ref, mv = q[X]
                        p = _mvp(info, addr, first_mb, width_mbs, done, 8 * (k % 2), 8 * (k // 2), 8, X, ref)
                        b.se(mv[0] - p[0])
                        b.se(mv[1] - p[1])
                    done[k] = q
        b.ue(0)                                      # coded_block_pattern 0: no residual
        info[addr] = quads
    if run:
        b.ue(run)
    b.trailing()
    return b.getvalue(), header_bits


def _minpos(a, b):
    return min(a, b) if a >= 0 and b >= 0 else max(a, b)


def _neighbour(info, addr, first_mb, W, cur, xN, yN):
    """Motion of the 8x8 block covering luma location (xN, yN), relative to macroblock addr (H.264 6.4.12),
    or None when it is not available: outside the picture or the slice, not yet decoded, or to the right
    of the current macroblock below its top row. cur: the current macroblock's quadrants decoded so far."""
    mx, my = addr % W, addr // W
    if 0 <= xN <= 15 and 0 <= yN <= 15:
        return cur.get((yN // 8) * 2 + xN // 8)
    if yN > 15 or (xN > 15 and yN >= 0):
        return None
    if yN < 0:
        if xN < 0:
            nb = addr - W - 1 if mx > 0 and my > 0 else None
        elif xN <= 15:
            nb = addr - W if my > 0 else None
        else:
            nb = addr - W + 1 if my > 0 and mx < W - 1 else None
    else:
        nb = addr - 1 if mx > 0 else None
    if nb is None or nb < first_mb or nb not in info:
        return None
    return info[nb][((yN % 16) // 8) * 2 + (xN % 16) // 8]


def _mvp(info, addr, first_mb, W, cur, x, y, w, X, ref):
    """Median motion vector prediction (H.264 8.4.1.3) for list X of a w-wide partition at (x, y) of the
    macroblock (16x16 partitions, 8x8 sub-macroblocks, and direct prediction with x = y = 0, w = 16)."""
    def nb(xn, yn):
        return _neighbour(info, addr, first_mb, W, cur, xn, yn)

    A, B, C = nb(x - 1, y), nb(x, y - 1), nb(x + w, y - 1)
    if C is None:
        C = nb(x - 1, y - 1)
    if B is None and C is None and A is not None:
        B = C = A
    A, B, C = [(-1, (0, 0)) if q is None else q[X] for q in (A, B, C)]
    same = [q for q in (A, B, C) if q[0] == ref]
    if len(same) == 1:
        return same[0][1]
    med = lambda a, b, c: a + b + c - min(a, b, c) - max(a, b, c)   # noqa: E731
    return (med(A[1][0], B[1][0], C[1][0]), med(A[1][1], B[1][1], C[1][1]))


def _direct(info, addr, first_mb, W):
    """The quadrants of a B_Skip macroblock under spatial direct prediction (H.264 8.4.1.2.2), assuming
    the co-located zero-motion rule cannot change them (see b_slice)."""
    def nb(xn, yn):
        return _neighbour(info, addr, first_mb, W, {}, xn, yn)

    A, B, C = nb(-1, 0), nb(0, -1), nb(16, -1)
    if C is None:
        C = nb(-1, -1)
    refs = []
    for X in (0, 1):
        r = [-1 if q is None else q[X][0] for q in (A, B, C)]
        refs.append(_minpos(r[0], _minpos(r[1], r[2])))
    if refs[0] < 0 and refs[1] < 0:
        m = ((0, (0, 0)), (0, (0, 0)))
    else:
        m = tuple((refs[X], _mvp(info, addr, first_mb, W, {}, 0, 0, 16, X, refs[X])) if refs[X] >= 0
                  else (-1, (0, 0)) for X in (0, 1))
    return (m,) * 4


def _is_copy(m):
    """True if the motion only uses reference index 0 with zero motion (a copy of the previous frame)."""
    return all(r < 0 or (r == 0 and mv == (0, 0)) for r, mv in m)
