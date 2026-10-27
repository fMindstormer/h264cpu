"""Annotate the page recording from tools/record_demo.cjs: a caption band per step, and a real-time tag.

    python tools/compose_demo.py <recording dir> docs/images/demo.webp

Fonts are macOS system fonts."""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

rec, out = Path(sys.argv[1]), Path(sys.argv[2])
W = 1000
times = [tuple(map(float, l.split()[:2])) for l in (rec / "times.txt").read_text().splitlines()]
steps = dict(json.loads((rec / "steps.json").read_text())["steps"])
CAPTIONS = [
    ("choose", "1", "Choose a starting pattern: two glider guns."),
    ("draw", "1", "Draw on it: a line of live cells, here with the keyboard."),
    ("run", "2", "JavaScript writes the start once. From then on the decoder is fed the same 16 program frames (the highlighted square) while the board keeps changing."),
    ("machine", "3", "The whole decoded frame: the board, the neighbour counts, the rule and the display, each a region of the picture the decoder keeps."),
    ("download", "4", "Download the same run as an ordinary MP4: any H.264 player's decoder computes the same frames."),
]
big = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 22, index=2)      # demi bold
txt = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 18, index=5)
tag = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 13)

def wrap(draw, text, font, width):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=font) > width and cur:
            lines.append(cur); cur = word
        else:
            cur = t
    return lines + [cur]

BAND = 78
def caption_at(ms):
    cur = CAPTIONS[0]
    for c in CAPTIONS:
        if steps[c[0]] <= ms:
            cur = c
    return cur

frames, durations = [], []
for k, (i, ms) in enumerate(times):
    im = Image.open(rec / f"frame-{int(i):04d}.jpg").convert("RGB")
    h = round(im.height * W / im.width)
    im = im.resize((W, h), Image.LANCZOS)
    canvas = Image.new("RGB", (W, h + BAND), (22, 25, 28))
    canvas.paste(im, (0, BAND))
    d = ImageDraw.Draw(canvas)
    _, num, text = caption_at(ms)
    d.ellipse((16, 16, 46, 46), fill=(184, 70, 27))
    d.text((31, 31), num, font=big, fill="white", anchor="mm")
    lines = wrap(d, text, txt, W - 60 - 250)
    y = BAND / 2 - 12 * len(lines) - 2
    for line in lines:
        d.text((60, y), line, font=txt, fill=(240, 236, 228)); y += 24
    d.text((W - 16, 31), "real time · Chromium, decoding", font=tag, fill=(170, 176, 180), anchor="rm")
    d.text((W - 16, 49), "through VideoToolbox", font=tag, fill=(170, 176, 180), anchor="rm")
    frames.append(canvas)
    nxt = times[k + 1][1] if k + 1 < len(times) else ms + 1500
    durations.append(max(20, round(nxt - ms)))
durations[-1] = 2500
frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, quality=70, method=6)
print(out, out.stat().st_size, len(frames), sum(durations) / 1000)
