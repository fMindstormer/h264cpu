# How it works

[← Back to the README](../README.md)

The mechanism in detail: what one macroblock computes, how fields and ops make a machine, how a program
becomes frames that real decoders accept, and how the page runs a stream forever.

## One macroblock is one instruction

A video decoder rebuilds most of each picture from pictures it has already decoded. In a B frame, every
16×16 macroblock is a prediction:

1. **Where from.** A motion vector says which block of an earlier picture to copy. It can point far
   away: at this level, up to 2048 pixels sideways and 512 up or down.
2. **Which picture, and how much of it.** A reference index picks an entry in one of two reference
   lists. An entry names an earlier picture and carries a weight and an offset for each colour plane. A
   slice builds its own lists, and it may name the same picture many times with different weights.
3. **Mix.** With explicit weighted prediction, a macroblock that reads from both lists computes, for
   every sample,

       clip(((w0·a + w1·b + 2^L) >> (L+1)) + ((o0 + o1 + 1) >> 1))

   and one that reads from a single list computes clip(((w·a + 2^(L−1)) >> L) + o), or clip(w·a + o)
   when L = 0. Weights and offsets are integers from −128 to 127, and L, the log2 of the weights'
   denominator, runs from 0 to 7. Board ops give both entries the same offset o, so the last term is just o.
   These are equations 8-274 to 8-276 of the standard.[^h264]
4. **Nothing else.** Encoders normally send a residual that corrects the prediction, and a deblocking
   filter smooths the edges between blocks. These files send no residual and switch deblocking off, so
   every decoded sample is exactly the prediction.

Together that is an instruction: two loads from up to 15 frames back, a multiply-add with constant
weights, and a saturating 8-bit store. A frame runs one instruction per macroblock, all of
them at once, and the next frame can read the results. The rest of this page is about building a computer out of that, and about what it took to make real
decoders run it.

## The computation model

**Fields and cells.** A program is a set of *fields*: square boards of cells, each in its own region of
one large frame.
- A cell is 2×2 luma pixels and one chroma sample (chroma is stored at half resolution), so a field is
  three boards, Y, Cb and Cr, that compute in lockstep. Weights may differ per plane.
- In every frame, one op rewrites every macroblock of a field, so an op is a single SIMD instruction over
  the whole board.
- An op's motion vectors make it read other fields, shifted by a fixed number of cells.

**Clock and memory.** A frame is one tick of the clock. An op reads fields from 1 to 15 frames back,
which the decoder still holds as reference pictures (the 4-bit frame counter, [below](#from-a-program-to-frames),
sets the limit of 15; Life's ops reach 5 frames back, the CPU's 15): the decoded picture buffer is the machine's memory.
A field that is read at an offset carries an 8-cell halo. Life's board is one such field: it is read
for its neighbours. The field's own op fills the halo through wrapped motion vectors, so boards are tori.

**Instructions.** Two inputs, constant weights, 8 bits and a clip give these building blocks:

| Operation | Weighted prediction | Used for |
|---|---|---|
| a + b, saturating | L = 0, weights 2 and 2 | Life's neighbour counts |
| a − b, clipped at 0 (a ReLU) | L = 0, weights 2 and −2 | Life's new board, `S = ge24 − ge48` |
| exact average, (a + b + 1) >> 1 | L = 6, weights 64 and 64 | the Turing program's blur pyramid |
| scale and shift | one input: ((w·a + 2^(L−1)) >> L) + o | Life's `p5`: 8 if the cell is alive |
| threshold | steep weights against `K`, a constant field of 255: 0 below one value, 255 above another | Life's `ge24` and `ge48` |
| NOT and OR, on 0 and 255 | 255 − a (against `K`); a + b | the spiral's OR tree |
| min and max | two ops each: a − relu(a − b); b + relu(a − b) | the Turing min tree; Life's glow |
| select | mask each candidate with a steep offset, then add | the spiral's next state |
| colour | ramps, then weighted pairs per plane at L = 6 | every display |

AND is a threshold on the average, so every Boolean gate takes one or two ops. In a bi-prediction,
w0 + w1 must stay between −128 and 128 (127 when L = 7), which is why steep weights come in opposing pairs, as in a
threshold against `K`.

**Pipelines.** An op reads earlier frames, so a chain of ops takes one frame per op. Every op still runs
in every frame, so a program is a pipeline. Life's chain has six stages, so it holds six interleaved
copies of its computation.
- The writer fills every stage from the same starting board, so the six copies stay equal and the
  board advances once every six frames.
- Delays line inputs up. Life's `t` adds `c`, read one frame back, to `p5`, read three frames back,
  because `p5` comes two stages earlier in the chain.

**What it can compute.** Any Boolean circuit that fits in the frame and within the level's macroblock
rate, at one or two frames per gate of depth; the CPU's 334 fields use 66% of that rate at 60 fps. With
reference pictures as registers, any finite-state machine that fits the same way. A fixed profile and level
do not stretch to arbitrary circuits: the frame size, the macroblock rate and the 15-frame reach are fixed.

The Game of Life is Turing complete on an unbounded board (Berlekamp, Conway and Guy, *Winning Ways*,
1982),[^ww] and Paul Rendell built a Turing machine in it in 2000 and a universal one in 2010.[^rendell]
That does not make a file here universal. Its board is a fixed 200×200 torus and the decoder keeps a fixed
number of 8-bit reference pictures, so each file is a finite-state machine, as every physical computer is,
and Rendell's machines need far larger boards than these. What the files demonstrate is narrower and
concrete: cellular automata on fixed boards, and a 16-bit stored-program computer with 64 registers.

**What it cannot.**
- *Choose addresses.* Motion vectors are written into the program frame, which never changes. A program
  is a circuit wired by motion vectors, closer to an FPGA bitstream than to code. The CPU still selects
  registers at run time, but as circuitry: every instruction reads all 64 registers and masks out all but
  the one it names (see [the CPU](programs.md#a-cpu-the-wireworld-computers-instruction-set)).
- *Multiply two variables in one op.* Weights belong to list entries, so they are constants: an op only
  scales its inputs by fixed numbers. A product of two fields is still computable, like any circuit, but
  as a multiplier over their bits, many ops and frames deep. Values wider than 8 bits likewise take
  several fields per number, with carries between them.
- *Scale.* Blocks are translated, never scaled or rotated. The tunnel builds zoom and rotation out of
  thousands of slightly different translations.
- *Avoid rounding.* Every op rounds and clips. The programs either stay exact (integers at L = 0,
  (a + b + 1) >> 1 at L = 6) or use the rounding on purpose (the tunnel's colours).

<img src="../docs/images/machine.png" alt="The whole 4032x832 frame of life.mp4, half size: 18 labelled fields, the coloured picture at the top left">

*`life.mp4` with its crop ignored, at half size: the 18 fields in the top band (L = 6) and the bottom band
(L = 0). Grey levels are field values; fields with small values are contrast-stretched, as their labels
say. The `glassbox` command renders this view as a video.*

## From a program to frames

`machine.py` turns fields and ops into B-frame syntax, and simulates, sample by sample, what a decoder
must output. Every piece of the syntax came with a constraint.

**Reference lists.** A frame slice can have at most 16 entries per list.
- Entry 0 of both lists is a plain copy of the previous frame.
- Ops with the same delay, weights and offsets share an entry. When a list would overflow, the writer
  starts a new slice.
- The lists are built by modification commands that count back from the current frame, so "three
  frames back" is the same command in every frame.

**Slices and precision.** L is set per slice, so fields that need L = 6 (averages, colour mixes) share a
band of the frame, and a slice starts wherever L changes. Life needs 2 slices. The tunnel, with its
picture beside the fields, needs 101. Level 5.1 allows 682 at 60 fps.

**Skipped macroblocks.** The decoder makes its own guess of each macroblock's references and motion,
from its left, top and top-right neighbours: *direct prediction*. When that guess is exactly what the
op needs, the macroblock is coded as B_Skip, which is almost free.
- Inside a field every macroblock reads like its neighbours. So the writer runs the decoder's derivation
  for each macroblock and codes only the ones where the guess fails: mostly each field's top row and
  left column, and its halo.
- In Life, 12,272 of the 13,104 macroblocks (94%) are skipped. That is why the program frame is only
  2.7 KB.
- One rule of direct prediction could have broken this. When the co-located block of a reference picture
  is still, it forces zero motion on any skipped block that uses reference index 0. Index 0 is the plain
  copy, which only unused macroblocks use, and only with zero motion, so the rule never changes a result.

**The same frame, 16 times.** A slice header carries `frame_num`, here 4 bits, which counts frames and
wraps. With picture order count type 2, display order is decode order and the headers carry no other
counter. So the program frames differ only in those 4 bits: the file is 16 different frames, repeated.

**Starting the machine.**
- Frame 0 is an IDR frame. Intra prediction with no neighbours and no residual gives exactly 128, so the
  frame is flat grey except for the first picture, stored as raw I_PCM samples.
- P frames then carry the rest of the starting state as I_PCM, in chunks small enough for the level's
  size limit on one frame.
- Skipped copies follow until the longest delay reaches the starting state.
- Then the program frames repeat.

**Fitting level 5.1.** A decoder that supports level 5.1 must handle any stream within its limits
(Annex A of the standard[^h264]), so every build checks them:

| Level 5.1 limit | `life.mp4` | `tunnel.mp4` |
|---|---|---|
| 983,040 macroblocks per second | 786,240 | 946,560 |
| 36,864 macroblocks per frame | 13,104 | 15,776 |
| 682 slices per frame, at 60 fps | 2 | 101 |
| Frame 0: 192 bytes per macroblock of the frame | 0.29 of 2.52 MB | 0.13 of 3.03 MB |
| Any later frame: 3.1 MB | 2.3 MB | 2.0 MB |
| Vertical motion vectors: −512 to 511.75 pixels | −416 to 418 | −288 to 288 |
| Reference list entries: 16 | 7 | 6 |

**Players.**
- *Crop.* The SPS crop window shows players only the display field. QuickTime and the Claude desktop app
  decode through Apple's VideoToolbox, and they ignore the window's left and top offsets. So the display
  field always sits at the frame's top-left corner, where only right and bottom offsets are needed.
- *Colour.* The stream marks its samples as full range with the BT.601 matrix, so the values a program
  computes are exactly the colours shown. The palettes are worked out in YCbCr.
- *Container.* `mp4.py` writes a minimal MP4, moov first, like `ffmpeg -c copy` does. Its samples are the
  access units unchanged, with the parameter sets in-band. The page's JavaScript writes the same file
  byte for byte.

## Running forever in a browser

The [page](https://fmindstormer.github.io/h264cpu/) never downloads a video. You draw a pattern, or start
the CPU, and your browser's own decoder runs it.
- **Writing the stream.** The 16 program frames do not depend on the pattern, so Python compiles them
  once, into `life.json`, `tunnel.json` and `primes.json`. `h264cpu.js` writes the rest from your
  pattern: frame 0, the stored state and the copies, byte for byte as Python would. The CPU always starts
  the same, so `primes.json` also carries its starting values: the registers, the circuit's constants and
  the display's first picture.
- **Why not Media Source Extensions.** MSE is the usual way to stream into a `<video>` element, and it
  cannot run these forever. Its buffer must be trimmed, and the standard's removal rule also removes
  every frame up to the next random access point,[^mse] because later frames may depend on removed ones. These
  streams have exactly one random access point, frame 0. Left untrimmed, the buffer fills: desktop Chrome
  holds about 150 MB of video, which is 15 minutes of Life or under two minutes of the tunnel.
- **WebCodecs instead.** The page hands the decoder one frame at a time, as MP4-style samples, and draws
  each decoded frame on a canvas.
  - In real time, frames are shown at 60 per second.
  - *Flat out* feeds the decoder as fast as it accepts frames, and shows the newest at each screen
    refresh.
  - Either way every frame is decoded, in order. Only showing is ever skipped.
- **Converting only what is shown.** The page draws a `VideoFrame` view of just the displayed region, so
  the browser converts 400×400, 1920×1080 or 592×208 pixels to RGB, not the whole frame. In software, that alone
  took Life flat out from about 245 to about 350–470 frames a second.

Browsers without H.264 in WebCodecs get a 60-second MP4 instead, written in the page. That run is finite:
when the video loops, it starts again from the beginning, and the page says so.

[^h264]: ITU-T, [Rec. H.264](https://www.itu.int/rec/T-REC-H.264), *Advanced video coding for generic audiovisual services*: weighted sample prediction in 8.4.2.3 (equations 8-274 to 8-276) and the constraint on w0 + w1 in 8.4.3 (8-298); fractional sample interpolation in 8.4.2.2; level limits in A.3.1, A.3.3 and Tables A-1 and A-4.
[^ww]: E. R. Berlekamp, J. H. Conway and R. K. Guy, *Winning Ways for Your Mathematical Plays*, vol. 2, ch. 25, "What Is Life?", Academic Press, 1982; [2nd ed.](https://doi.org/10.1201/9780429487309), vol. 4, A K Peters, 2004.
[^rendell]: P. Rendell, "[A Turing Machine in Conway's Game of Life](http://rendell-attic.org/gol/tm.htm)" (2000) and "[A Universal Turing Machine in Conway's Game of Life](http://rendell-attic.org/gol/utm/index.htm)" (2010); see also his book [*Turing Machine Universality of the Game of Life*](https://doi.org/10.1007/978-3-319-19842-2), Springer, 2016.
[^mse]: W3C, [Media Source Extensions](https://www.w3.org/TR/media-source-2/#sourcebuffer-coded-frame-removal), coded frame removal algorithm: after removing frames, it removes "all coded frames … between those frames removed in the previous step and the next random access point after those removed frames".
