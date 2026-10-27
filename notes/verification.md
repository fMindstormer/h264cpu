# How it is checked

[← Back to the README](../README.md)

The rule is simulation first. Every program is an exact NumPy model of what a decoder must output
(`vsim.py`, `interp.py`, `machine.py`), and a real decoder has to agree with it, sample for sample.

## Four kinds of evidence

They are different in strength, so they are kept apart here.

| Kind | What runs | When | What it shows |
|---|---|---|---|
| **Short automated runs** | `pytest`: the writer's random tests, 3-second versions of all five programs decoded by ffmpeg and compared in every sample, the browser writer's byte parity, the program-frame invariant, and the page in Chromium | CI on Linux, on every push; locally on macOS | the compiler, writer and page are correct on these inputs |
| **Full release verification** | `python -m h264cpu <program>` for each release file: all 1800 frames decoded by ffmpeg and compared in every sample, plus the program's own reference (Life's boards against plain NumPy Life, the CPU's state against a reference model); then again with `--hwaccel videotoolbox` | by hand, before a release | the exact files in the release decode exactly, on two decoders |
| **Browser frame sampling** | `tests/test_browser.py`: the built page runs in Electron's Chromium, and frames are hashed as the decoder hands them over: every frame for the first 4 to 6 seconds, then every 97th frame flat out | in `pytest` | a browser's decoder computes the same frames from the page's stream |
| **Manual playback** | opening a file in a player and looking | occasionally | the file plays there; not evidence of exact computation |

## The checks

The rule is simulation first. Every program is an exact NumPy model of what a decoder must output
(`vsim.py`, `interp.py`, `machine.py`), and a real decoder has to agree with it.
- **Every pixel.** For each file, ffmpeg decodes all 1800 frames uncropped. Every sample in every plane
  equals the simulation.
- **Every generation.**
  - `life.mp4`'s board equals plain NumPy Life after each of its 298 generations, and `tunnel.mp4`'s
    after each of its 299.
  - `spiral.mp4`'s board equals the cyclic automaton after each of its 199 generations.
- **The MP4s.** Each MP4 decodes to the same frames as its raw stream.
- **The writer.** Two random tests decode streams full of random weights, offsets, references and
  motion, and compare every sample. They cover:
  - whole-pixel and quarter-pixel vectors, at all 16 fractional positions;
  - vectors reaching 24 pixels past the picture's edges;
  - 16×16 macroblocks, and macroblocks split into 8×8 quadrants that predict from list 0, list 1 or both.

  Breaking any one rounding, clamping or prediction rule on purpose makes them fail.
- **The browser writer.** `docs/h264cpu.js` writes the same streams and MP4s as the Python writer, byte
  for byte, for Life, the tunnel and the CPU.
- **The page, in a browser.** `tests/test_browser.py` runs the built page in Chromium (Electron, which
  decodes H.264) for each program. It hashes frames as the decoder hands them to the page:
  - every frame of the first 4 to 6 seconds;
  - flat out, every 97th frame up to frame 6,000 (Life), 970 (tunnel) or 1,940 (CPU).

  Every hash must equal the simulation's. The test also checks pause and a second run, that the
  download is the right file byte for byte, that the page says it is running live, that the cycle of
  program frames is lit, that the whole-machine view outlines every field, and that the keyboard draws.
  Two more runs check the page's other modes: forced into its fallback, it plays a finite 60-second MP4
  and says so; asked for reduced motion, it feeds the decoder nothing until Resume is pressed.
  - On macOS, Chromium decodes through VideoToolbox and hands the page frames converted to limited range,
    though the stream says full range: the luma through a table within 1 of 16 + 219 y / 255, the chroma
    through a colour matrix too. There the test learns the luma table from two whole frames, where each
    simulated value must always come back as the same value, and compares every hashed frame's luma
    through it. Life, the tunnel and the CPU pass on an M4 Mac.
- **Level 5.1 limits.** Every build checks:
  - macroblock rate and frame size;
  - slices per picture and access-unit sizes;
  - motion-vector ranges;
  - at most 16 entries per reference list.
- **Apple's decoder.** VideoToolbox, the hardware decoder behind QuickTime Player and Safari on the Mac,
  is not ffmpeg. `--hwaccel videotoolbox` makes a build check every frame through it instead (ffmpeg
  reports the `videotoolbox_vld` pixel format, so the hardware decoder does the work). On an M4 Mac with
  macOS 27, all 1800 frames of each of the five files equal the simulation in every sample there too.

- **The CPU.** After every instruction, `primes.mp4`'s state in the decoded frame (the 64 registers, the
  program counter, the instruction register, the display and the circulating carry) equals a reference
  model of the instruction set. The model reproduces Owen's run: 59 is written at instruction 5,790,
  13.3 million generations at 2,304 a cycle, against his "about 14 million".
- **The program frames do not depend on the start.** `test_program_frames_do_not_depend_on_the_start`
  writes Life from two different starting patterns: the start-up frames differ, and every frame after
  them is the same, a cycle of 16. So the program frames cannot hold the board.

## Release verification record

The v1.0 files, verified between 23 and 27 October 2026:

| | |
|---|---|
| Machine | Apple M4, macOS 27.0.1 |
| Decoders | ffmpeg 9.0.2 (software, its default arm64 code path); ffmpeg 9.0.2 with `-hwaccel videotoolbox` (Apple's hardware decoder) |
| Python | 3.13.3, NumPy 2.2.5, Pillow 11.2.1 |
| Browser test | Electron 38.8.6 (Chromium), decoding through VideoToolbox |
| CI | Ubuntu 24.04, ffmpeg 6.1.1, Python 3.12, NumPy 2.5.4: all tests pass (14 at the release commit) |

| File | ffmpeg, all 1800 frames | VideoToolbox, all 1800 frames | Program reference |
|---|---|---|---|
| `life.mp4` | identical in every sample | identical | 298 generations equal plain Life |
| `spiral.mp4` | identical | identical | 199 generations equal the cyclic automaton |
| `turing.mp4` | identical | identical | (no independent reference; the simulation is the model) |
| `tunnel.mp4` | identical | identical | 299 generations equal plain Life |
| `primes.mp4` | identical | identical | 104 instructions equal the reference CPU |

The build is deterministic: rebuilding `primes.mp4` on 27 October gave a byte-identical file. The SHA-256
of each file is in the release notes.

Reproduce one, about a minute and a half on the M4:

    python -m h264cpu primes --hwaccel videotoolbox

which ends with

    checked: 1800 of 1800 frames decoded by ffmpeg (videotoolbox) are identical to the simulation in every sample; 104 generations equal the reference

Manual playback, separately: QuickTime Player and the Claude desktop app played `spiral.mp4` correctly by
eye, and a screenshot of an earlier spiral build matched ffmpeg's decode cell for cell.

## Clock speed

Decoding all 1800 frames: single thread, ffmpeg 6.1, a 2.1 GHz Xeon, best of two runs.

| File | Frames a second | Generations a second | Macroblocks a second |
|---|---:|---:|---:|
| `life.mp4` | 255 | 42 | 3.3 million |
| `spiral.mp4` | 782 | 87 | 4.8 million |
| `turing.mp4` | 211 | 211 steps | 3.0 million |
| `tunnel.mp4` | 255 | 42 | 4.0 million |

For Life, that is about a billion weighted 8-bit samples a second on one core. On the page, Chromium
(Electron 38), decoding in software on 2 cores with no GPU, ran Life at 350–470 frames a second flat out
and the tunnel at 100–130. On an M4 Mac, the same Chromium decoding through VideoToolbox ran Life at
about 650, the tunnel at about 200 and the CPU at about 620 (36 instructions a second). Phones have not been timed.

On the M4 itself, single-threaded ffmpeg 9 decodes Life at 896 frames a second, the tunnel at 606 and
`primes.mp4` at 789: 46 instructions a second.

