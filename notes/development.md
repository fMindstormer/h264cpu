# Notes from the work

[← Back to the README](../README.md)

What went wrong on the way, and what it taught.

## Notes

- **It started with neural networks.** The first question was whether a neural network could run in a
  video decoder. A per-pixel digit classifier was trained through the exact decoder arithmetic, with
  straight-through gradients. Its pixels then "gossiped" towards a consensus.
  - Replayed with exact integer ops, it matched the training forward pass on 98.5% of its scores.
  - It got about 60% of test digits right.
  - It worked, but it was dull to watch. Cellular automata turned out to be the natural fit: local
    rules, iterated forever, with something to see.
- **FFmpeg's SIMD bi-prediction departs from the standard.** On an Apple-silicon Mac, ffmpeg 9.0.2
  failed the random writer test. Bi-prediction from two flat pictures shows it: with weights 64 and 63
  and both offsets 127 at a weight denominator of 2^7, the standard gives 254 and the default decode
  gives 0. FFmpeg's C code (`-cpuflags 0`) and VideoToolbox both give 254.
  - The cause: the SIMD functions compute in 16 bits. The weighted sum plus the offset term can pass
    32,767 at a denominator of 2^7, where FFmpeg's x86 code (SSE2, SSSE3) saturates, giving 127, and
    9.0.2's arm64 code wrapped, giving 0 (and also failed some cases at 2^6).
  - FFmpeg master fixed the 2^6 cases on arm64 in September 2026 and now saturates like x86, so on
    master both give 127. FFmpeg's own `checkasm` test skips the 2^7 case for 8-bit video, noting that
    the x86 code is exact only up to 2^6. Chromium's software decoder is FFmpeg, so it inherits this.
  - h264cpu never uses 2^7 (a slice at 2^7 would need a copy weight of 128, one beyond the limit), so
    all five files decode exactly on these decoders; the writer test, whose random streams do use it,
    decodes with the C code.
- **The Wireworld computer came first as cells.** An 800×600 version of it runs in plain NumPy, and
  13% of its cells are wire, so a sparse layout fit the level. Owen's own figures ended it: 2,304
  generations per instruction is minutes per instruction here. The instruction set, built directly, is
  hundreds of times faster.
- **frame_num limits how far back a frame can read.** The 16 program frames differ only in a 4-bit
  frame_num, so a reference 16 frames back has the current frame's number, which H.264 forbids. The CPU's
  first build read that far, and ffmpeg misread slice headers from then on. Reads now stop at 15 frames
  back, through relay copies.
- **An L = 7 slice needs an illegal weight.** Unused macroblocks copy the previous frame through a list
  entry of weight 2^L, which is 128 when L = 7, one beyond the limit. The display first used L = 7.
- **Players ignore the crop's left and top offsets.** An early spiral build put the display field in the
  middle of the frame. QuickTime and the Claude desktop app showed the top-left field instead.
  - A screenshot matched ffmpeg's decode of that field cell for cell, in 3580 of 3584 visible cells.
  - That put the cause on the crop rather than on the decoding.
- **Frame 0 was too big.** Storing the whole starting state in the first frame broke the level's limit
  on one access unit, which follows from its minimum compression ratio. The state now goes into P frames,
  in chunks.
- **Reference lists overflowed.** With its own list entries for every field, the stream made ffmpeg
  report a reference overflow, because a frame slice has at most 16 entries per list. Ops now share
  entries, and slices split before a list overflows.
- **An MP4 lost its first frame.** ffmpeg's MP4 muxer gave these raw streams a negative first timestamp
  and an edit list that cut frame 0, the frame that holds the first picture. `mp4.py` writes its own
  minimal container instead.
- **The tunnel's first layout was impossible.** With four bands of fields, the annealer could not keep
  every read within the vertical vector range. Following Life's chain of reads showed why: every link
  must stay within one band of the last. So the fields went into three bands, and the frame grew wider.
- **Blending the board into the tunnel.**
  - Adding the board to the zoomed history, or taking the maximum, washed the picture out to orange or
    beige.
  - Drawing the board over its history worked. The streaks are then exactly the history of the board's
    edge.
- **Block size did not matter.** Before the tunnel was built, NumPy previews with the exact interpolation
  compared 16×16, 8×8 and 4×4 blocks with a warp computed per pixel. They looked the same, because the
  notches along each streak are generations, not block edges. So the tunnel uses one vector per
  macroblock, and its program frame is 24.7 KB. With 8×8 blocks it would be 62 KB.
- **No infinite Mandelbrot zoom.** It was the obvious showpiece, and it does not fit. Each iteration
  squares a number, which here means a whole multiplier circuit over multi-field values, and a deeper
  zoom needs ever more bits per number. The frame, and the macroblock rate level 5.1 allows, are fixed.


