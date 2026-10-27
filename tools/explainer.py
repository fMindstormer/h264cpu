"""The README's still: starting state, the 16 repeated program frames, decoder output, and the loop.

    python tools/explainer.py docs/images/explainer.png

The boards are frames as ffmpeg decodes them. Fonts are macOS system fonts."""
import subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from h264cpu import mp4
from h264cpu.programs import life

N, GEN = life.N, 260
GUN = "24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$2o8bo3bob2o4bobo$10bo5bo7bo$11bo3bo$12b2o!"
def rle(t):
    cells, x, y, n = [], 0, 0, ""
    for ch in t:
        if ch.isdigit(): n += ch; continue
        k = int(n) if n else 1; n = ""
        if ch == "b": x += k
        elif ch == "o": cells += [(x + i, y) for i in range(k)]; x += k
        elif ch == "$": y += k; x = 0
        elif ch == "!": break
    return cells
board = np.zeros((N, N), bool)
def stamp(cells, ox, oy, flip=False):
    w, h = max(c[0] for c in cells), max(c[1] for c in cells)
    for x, y in cells:
        board[(oy + (h - y if flip else y)) % N, (ox + (w - x if flip else x)) % N] = True
stamp(rle(GUN), 30, 40); stamp(rle(GUN), 120, 130, True)          # the page's "two glider guns"
m = life.build()
init = m.initial(life.given(board)); m.stream(init, 1, "D")          # sets first_program_frame
frames = m.stream(init, m.first_program_frame + 6 * GEN + 1, "D")
first, prog_bytes = m.first_program_frame, len(frames[m.first_program_frame])
tmp = Path(tempfile.mkdtemp())
(tmp / "a.mp4").write_bytes(mp4.mux(frames, 2 * N, 2 * N, 60))
def decoded(n):
    out = tmp / f"f{n}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-cpuflags", "0", "-i", str(tmp / "a.mp4"), "-vf", f"select=eq(n\\,{n})",
                    "-frames:v", "1", "-update", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")
f_out = first + 6 * (GEN - 1)          # first program frame = generation 1
start, later = decoded(0), decoded(f_out)

F = "/System/Library/Fonts/Avenir Next.ttc"
h1, body, small = ImageFont.truetype(F, 34, index=2), ImageFont.truetype(F, 25, index=5), ImageFont.truetype(F, 22, index=7)
mono = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 20)
INK, MUTED, EMBER, TEAL, PAPER = (22, 25, 28), (89, 97, 105), (184, 70, 27), (47, 111, 115), (242, 243, 239)
img = Image.new("RGB", (1800, 940), PAPER); d = ImageDraw.Draw(img)

def title(x, num, text):
    d.ellipse((x, 62, x + 44, 106), fill=EMBER); d.text((x + 22, 84), num, font=h1, fill="white", anchor="mm")
    d.text((x + 58, 84), text, font=h1, fill=INK, anchor="lm")
def lines(x, y, rows, font=body, fill=MUTED, gap=34, anchor="la"):
    for r in rows: d.text((x, y), r, font=font, fill=fill, anchor=anchor); y += gap
def arrow(points, colour=INK, width=5):
    d.line(points, fill=colour, width=width, joint="curve")
    (x0, y0), (x1, y1) = points[-2], points[-1]
    v = np.array([x1 - x0, y1 - y0], float); v /= np.linalg.norm(v); n = np.array([-v[1], v[0]])
    tip = np.array([x1, y1]); a, b = tip - 22 * v + 11 * n, tip - 22 * v - 11 * n
    d.polygon([tuple(tip), tuple(a), tuple(b)], fill=colour)

# 1. starting state
title(60, "1", "Starting state"); img.paste(start.resize((440, 440), Image.NEAREST), (60, 140))
lines(60, 600, ["Two glider guns, written once", "as raw samples in the first frames"])
# 2. repeated instructions
title(650, "2", "Repeated instructions")
for k in range(16):
    x, y = 660 + (k % 8) * 62, 150 + (k // 8) * 66
    if k == 5: d.rounded_rectangle((x, y, x + 54, y + 54), 6, fill=TEAL)
    else: d.rounded_rectangle((x, y, x + 54, y + 54), 6, outline=TEAL, width=3)
    d.text((x + 27, y + 27), str(k), font=mono, fill="white" if k == 5 else TEAL, anchor="mm")
lines(660, 300, [f"16 program frames, {prog_bytes / 1000:.1f} KB each,", "identical except a 4-bit counter,", "fed in turn for as long as it plays"])
# the decoder
d.rounded_rectangle((690, 470, 1160, 590), 14, fill=INK)
d.text((925, 512), "H.264 decoder", font=h1, fill="white", anchor="mm")
d.text((925, 556), "weighted prediction from its own pictures", font=small, fill=(200, 204, 206), anchor="mm")
# 3. output
title(1300, "3", "Decoder output"); img.paste(later.resize((440, 440), Image.NEAREST), (1300, 140))
lines(1300, 600, [f"Generation {GEN}: frame {f_out}, as ffmpeg", "decodes it"])
# arrows
arrow([(505, 530), (684, 530)]); arrow([(910, 400), (910, 464)]); arrow([(1166, 530), (1294, 530)])
arrow([(1520, 680), (1520, 790), (960, 790), (960, 596)], colour=EMBER, width=6)
lines(1000, 812, ["Each decoded picture is read by the next frames.", "This loop is the only place the state lives."], font=body, fill=EMBER)
d.text((60, 900), "The instructions repeat; the state changes. Game of Life on a 200 × 200 torus, one generation every 6 frames.", font=small, fill=MUTED)
img.save(sys.argv[1])
print(sys.argv[1], first, f_out, prog_bytes)
