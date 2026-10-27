# Prior art

[← Back to the README](../README.md)

## What came before

I searched the web, GitHub, Hacker News, Reddit, pouët, and work on repurposing codec hardware, in
October 2026. One earlier work computes in a video decoder: Video2NAND, which lays out logic gates in a
single VP8 frame. I found no earlier video file whose decoder carries state from frame to frame, and so
none that runs a cellular automaton, or any program, over time. A search that finds nothing is not proof
that nothing exists: if you know of earlier work, please open an issue, and this page will credit it. Neither Gwern Branwen's list of surprisingly
Turing-complete systems[^gwern] nor Andreas Zwinkau's list of accidentally Turing-complete ones[^zwinkau]
includes a video codec. The nearest relatives:

- **Video2NAND (2026).**[^v2n]
  - What it is: in one VP8 key frame, all-black and all-white blocks are bits. Horizontal and vertical
    intra prediction carry them right and down like wires, and TrueMotion prediction (left + top −
    top-left, clamped) makes NOT and AND gates, so any combinational circuit can be drawn in a frame.
    Sequential logic through inter frames is left as future work, and came up in the Hacker News
    discussion.[^v2nhn]
  - How this differs: Video2NAND showed first that a standard video decoder computes, with no exploit,
    as here. Its circuits are combinational and settle within one frame. Here inter frames carry the
    state: the decoded picture buffer is memory, each frame is a clock tick, and a repeated program frame
    runs forever. That is what cellular automata, and machines with state, need;
    `primes.mp4` runs a stored-program computer on it.
    The tool differs too: Video2NAND's gates work on black and white, while weighted prediction does
    arithmetic on 8-bit values, such as Life's neighbour counts and the Turing program's blurs.
- **JPEG XL predictor art (2021).**
  - What it is: JPEG XL predicts each pixel with a small decision tree over its neighbours, and Jon
    Sneyers pioneered art made from those trees.[^jxlart] In March 2021, code posted on pouët drew Rule 110
    down a still image, one row per step.[^pouet] D. Bohdan's write-up notes that this stops short of
    Turing completeness only because the format decodes in groups of at most 1024×1024 pixels; the
    designers kept the work per pixel bounded on purpose.[^dbohdan]
  - How this differs: that is one still image and a 1D automaton, from a feature that is close to a
    program by design. Here a 2D automaton runs over time and keeps its state between frames. It is
    built from a compression tool with no conditionals at all, on a codec that most phones and computers
    decode in hardware (these files have been checked on Apple's hardware decoder, not yet on phones).
- **FORCEDENTRY (2021).**[^pz]
  - What it is: an iMessage exploit that ran over 70,000 JBIG2 segment commands, using the image
    decoder's AND, OR, XOR and XNOR operations as a small computer with registers and a 64-bit adder. It
    needed an integer overflow (CVE-2021-30860) to reach memory beyond the image.
  - How this differs: these files use only standard features, within the level's limits.
- **Life in datamoshing (2019).**
  - What it is: artists edit motion vectors with FFglitch,[^ffglitch] and repeat P frames so that pixels
    keep flowing. Kaspar Ravel and Thomas Collet applied Game of Life rules to the motion vectors of an
    MPEG-2 video.[^ravel]
  - How this differs: their Life rule runs in a Python script while the file is made, and the decoder
    only applies the vectors it is given. Datamoshing iterates a fixed motion field, but nothing decides
    anything. The tunnel's warp is the same kind of iterated motion field, with a fade; what is new is the
    computation it carries.
- **Programmable media by design.**
  - What it is: MPEG-4 Structured Audio's SAOL[^saol] and TrueType hinting[^truetype] are languages their
    standards meant to be run. HarfBuzz's experimental WebAssembly shaper goes further: llama.ttf runs a
    language model inside a font.[^llama]
  - How this differs: H.264 has no such language.

[^gwern]: G. Branwen, "[Surprisingly Turing-Complete](https://gwern.net/turing-complete)", accessed October 2026.
[^zwinkau]: A. Zwinkau, "[Accidentally Turing-Complete](https://beza1e1.tuxen.de/articles/accidentally_turing_complete.html)", accessed October 2026.
[^v2n]: firer, "[Video2NAND](https://sharedobject.blog/posts/vp8-combinatorial-logic/)", *Shared Object*, 11 July 2026.
[^v2nhn]: "[Video2NAND – Abusing video codecs for great computational power](https://news.ycombinator.com/item?id=49145037)", Hacker News, August 2026.
[^jxlart]: J. Sneyers, [JPEG XL art gallery](https://sneyers.info/jxl/art/); Surma, [JXL Art playground](https://jxl-art.surma.technology/).
[^pouet]: "[The JPEG XL image format has demo potential](https://www.pouet.net/topic.php?which=12091)", pouët.net, from 29 March 2021; the Rule 110 code was posted on 30 March 2021.
[^dbohdan]: D. Bohdan, "[JPEG XL would be Turing-complete](https://dbohdan.com/jpeg-xl)", 2021, updated 2023; it quotes Jon Sneyers that the format is "(intentionally) not Turing complete".
[^pz]: I. Beer and S. Groß, "[A deep dive into an NSO zero-click iMessage exploit: Remote Code Execution](https://projectzero.google/2021/12/a-deep-dive-into-nso-zero-click.html)", Google Project Zero, 15 December 2021.
[^ffglitch]: R. Polla, [FFglitch](https://ffglitch.org/), a multimedia bitstream editor built on FFmpeg.
[^ravel]: K. Ravel, "[Conway's Game of Life encoded in video predictive frames](https://web.archive.org/web/20201206003023/https://www.kaspar.wtf/blog/encoding-the-game-of-life-in-datamosh)", 26 November 2019 (archived copy).
[^saol]: E. D. Scheirer and B. L. Vercoe, "[SAOL: The MPEG-4 Structured Audio Orchestra Language](https://doi.org/10.1162/014892699559742)", *Computer Music Journal* 23(2), 1999, pp. 31–51.
[^truetype]: Apple, *TrueType Reference Manual*, "[The TrueType Instruction Set](https://developer.apple.com/fonts/TrueType-Reference-Manual/RM05/Chap5.html)".
[^llama]: S. Fuglede Jørgensen, "[llama.ttf](https://fuglede.github.io/llama.ttf/)", 2024.
