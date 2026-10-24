"""A minimal MP4 muxer for these streams, laid out the way ffmpeg's `-c copy` writes them (moov first).

It mirrors web/h264cpu.js byte for byte, so the browser and Python write identical files. The access
units keep their parameter sets in-band; NAL units are length-prefixed instead of start-coded.
"""
from __future__ import annotations

import struct


def nal_units(au: bytes):
    """Split an Annex B access unit at its 4-byte start codes (the writer never emits 3-byte ones)."""
    out, s, i = [], -1, 0
    while i + 3 < len(au):
        if au[i] == 0 and au[i + 1] == 0 and au[i + 2] == 0 and au[i + 3] == 1:
            if s >= 0:
                out.append(au[s:i])
            s = i + 4
            i += 4
            continue
        i += 1
    if s >= 0:
        out.append(au[s:])
    return out


def _box(kind, *parts):
    body = b"".join(parts)
    return struct.pack(">I4s", len(body) + 8, kind) + body


def _full(kind, version, flags, *parts):
    return _box(kind, bytes([version]) + flags.to_bytes(3, "big"), *parts)


def mux(frames, width, height, fps=60):
    """frames: Annex B access units in decoding (= display) order; width, height: the displayed size."""
    timescale, n = 600, len(frames)
    delta = timescale // fps
    duration, movie = n * delta, round(n * 1000 / fps)
    units = nal_units(frames[0])
    sps = next(u for u in units if u[0] & 31 == 7)
    pps = next(u for u in units if u[0] & 31 == 8)
    samples = [b"".join(struct.pack(">I", len(u)) + u for u in nal_units(au)) for au in frames]
    matrix = struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
    avcc = _box(b"avcC", bytes([1, sps[1], sps[2], sps[3], 0xFF, 0xE1]), struct.pack(">H", len(sps)), sps,
                bytes([1]), struct.pack(">H", len(pps)), pps)
    colr = _box(b"colr", b"nclx", struct.pack(">HHH", 1, 1, 6), bytes([0x80]))   # BT.709/709/601, full range
    avc1 = _box(b"avc1", bytes(6), struct.pack(">H", 1), bytes(16), struct.pack(">HH", width, height),
                struct.pack(">II", 0x00480000, 0x00480000), bytes(4), struct.pack(">H", 1), bytes(32),
                struct.pack(">HH", 0x18, 0xFFFF), avcc, colr)

    def stbl(offset):
        return _box(b"stbl",
                    _full(b"stsd", 0, 0, struct.pack(">I", 1), avc1),
                    _full(b"stts", 0, 0, struct.pack(">III", 1, n, delta)),
                    _full(b"stss", 0, 0, struct.pack(">II", 1, 1)),
                    _full(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, n, 1)),
                    _full(b"stsz", 0, 0, struct.pack(">II", 0, n), b"".join(struct.pack(">I", len(s)) for s in samples)),
                    _full(b"stco", 0, 0, struct.pack(">II", 1, offset)))

    def moov(offset):
        return _box(b"moov",
                    _full(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, 1000, movie), struct.pack(">IH", 0x00010000, 0x0100),
                          bytes(10), matrix, bytes(24), struct.pack(">I", 2)),
                    _box(b"trak",
                         _full(b"tkhd", 0, 3, struct.pack(">IIIII", 0, 0, 1, 0, movie), bytes(8), bytes(8), matrix,
                               struct.pack(">II", width * 65536, height * 65536)),
                         _box(b"edts", _full(b"elst", 0, 0, struct.pack(">IIIHH", 1, movie, 0, 1, 0))),
                         _box(b"mdia",
                              _full(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, timescale, duration, 0x55C4, 0)),
                              _full(b"hdlr", 0, 0, bytes(4), b"vide", bytes(12), b"VideoHandler\x00"),
                              _box(b"minf",
                                   _full(b"vmhd", 0, 1, bytes(8)),
                                   _box(b"dinf", _full(b"dref", 0, 0, struct.pack(">I", 1), _full(b"url ", 0, 1))),
                                   stbl(offset)))))

    ftyp = _box(b"ftyp", b"isom", struct.pack(">I", 512), b"isomiso2avc1mp41")
    mdat = b"".join(samples)
    head = len(ftyp) + len(moov(0)) + 8
    return ftyp + moov(head) + struct.pack(">I4s", len(mdat) + 8, b"mdat") + mdat
