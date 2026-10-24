"""Ordinary re-encodes of a computing file, for viewing. They are NOT computing files themselves.

    python -m h264cpu glassbox life|spiral|turing|tunnel

out/<name>_glassbox.mp4      the decoder's whole frame (crop ignored), every field labelled: work fields as
                             grey levels (their luma value; fields with a small range of values get a
                             contrast stretch, marked in their label), the picture fields and the
                             display tile D in colour
out/spiral_view_768.mp4      the spiral's 128x128 picture, enlarged with hard pixels
Needs ffmpeg (with libx264) and Pillow; reads out/<name>.mp4, written by python -m h264cpu <name>.
"""
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
TO_TV = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
# contrast stretches for fields with a small range of values: name prefix -> (centre, gain)
TURING_STRETCH = {"mask": (0, 80), "up": (0, 80), "dn": (0, 80), "nup": (0, 80), "ndn": (0, 80),
                  "st": (127, 40), "sum": (127, 15), "SZ": (127, 12), "Z": (125, 60)}
LIFE_STRETCH = {"p": (0, 6), "q": (0, 3), "c": (0, 2), "t": (0, 2)}
SETTINGS = {
    "spiral": dict(scale=6, cell_px=2, stretch={}, crf=18, every=1, seconds=30, view_crf=14,
                   note="one generation every 9 frames"),
    "turing": dict(scale=4, cell_px=1, stretch=TURING_STRETCH, crf=24, every=2, seconds=12, view_crf=None,
                   note="the pattern takes one step every frame"),
    "life": dict(scale=2, cell_px=1, stretch=LIFE_STRETCH, crf=26, every=2, seconds=12, view_crf=None,
                 note="one generation every 6 frames"),
    "tunnel": dict(scale=1, cell_px=1, stretch=LIFE_STRETCH, crf=26, every=2, seconds=12, view_crf=None,
                   note="one generation every 6 frames; the picture T is a quarter-pixel warp of itself"),
}


def stretch_of(name, table):
    for prefix in sorted(table, key=len, reverse=True):
        if name.startswith(prefix) and (len(name) == len(prefix) or not name[len(prefix)].isalpha()):
            return table[prefix]
    return None


def overlay(m, name, note, cell_px, table, cap, crop="D"):
    """Labels and caption as an RGBA image at the glass box's scale (cell_px pixels per cell)."""
    k = cell_px / 2
    Wp, Hp = int(m.width_mbs * 16 * k), int(m.height_mbs * 16 * k)
    sw, sh = m.fields[crop].shown_px
    im = Image.new("RGBA", (Wp, Hp + cap), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    small = ImageFont.truetype(FONT, 13 if cell_px == 2 else 11)
    big = ImageFont.truetype(FONT, 17 if cell_px == 2 else 13)
    for fname, f in m.fields.items():
        x, y = int(f.x0 * k) + 3, int(f.y0 * k) + 3
        s = stretch_of(fname, table)
        text = fname + (" (board + halo)" if fname == "S" else "") + (" (displayed)" if fname == crop else "")
        text += f" x{s[1]}" if s else ""
        box = d.textbbox((x, y), text, font=small)
        d.rectangle((box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), fill=(0, 0, 0, 170))
        d.text((x, y), text, font=small, fill=(255, 255, 255, 255))
    d.rectangle((0, Hp, Wp, Hp + cap), fill=(16, 16, 16, 255))
    line1 = (f"{name}.mp4 with its crop ignored: the whole {m.width_mbs * 16}x{m.height_mbs * 16} frame the decoder "
             f"computes. {len(m.fields)} fields, each rewritten every frame by one weighted-prediction op; {note}.")
    colour = [n for n, o in m.ops.items() if o.kind != "warp" and len(set(o.params)) > 1]
    pictures = [n for n, f in m.fields.items() if f.image]
    line2 = ("Grey level = a field's value in the luma plane (Cb and Cr hold the same numbers, except in the colour "
             f"stage{'s' if len(colour) > 1 else ''} {', '.join(colour)}){'; xN = contrast stretched' if table else ''}. "
             + (f"{crop}, in colour, is the {sw}x{sh} picture a normal player shows, with D in its middle."
                if pictures else f"D, in colour, is the {sw}x{sh} picture a normal player shows."))
    d.text((8, Hp + 5), line1, font=big, fill=(235, 235, 235, 255))
    d.text((8, Hp + cap // 2 + 2), line2, font=big, fill=(170, 170, 170, 255))
    return np.asarray(im).astype(np.float32)


def glassbox(m, name, note, cell_px, table, crf, every, seconds, out="out", crop="D"):
    Wp, Hp = m.width_mbs * 16, m.height_mbs * 16
    cap = 48 if cell_px == 2 else 36
    lab = overlay(m, name, note, cell_px, table, cap, crop)
    alpha = lab[..., 3:] / 255
    W, H = lab.shape[1], lab.shape[0]
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-flags2", "+ignorecrop", "-i", os.path.join(out, f"{name}.mp4"),
                            "-f", "rawvideo", "-pix_fmt", "yuvj420p", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(60 // every), "-i", "-", "-vf", TO_TV, "-c:v", "libx264", "-preset", "medium",
                            "-crf", str(crf), *TAGS, "-movflags", "+faststart", os.path.join(out, f"{name}_glassbox.mp4")],
                           stdin=subprocess.PIPE)
    in_colour = [f for f in m.fields.values() if f.image] + [m.fields["D"]]
    regions = []
    for fname, f in m.fields.items():
        s = stretch_of(fname, table)
        if s:
            fw, fh = f.size_px
            regions.append((f.y0 // 2, (f.y0 + fh) // 2, f.x0 // 2, (f.x0 + fw) // 2, s))
    fsize = Wp * Hp * 3 // 2
    n = -1
    while True:
        raw = dec.stdout.read(fsize)
        if len(raw) < fsize:
            break
        n += 1
        if n >= seconds * 60:
            break
        if n % every:
            continue
        a = np.frombuffer(raw, np.uint8)
        y = a[:Wp * Hp].reshape(Hp, Wp)[::2, ::2].astype(np.float32)          # one sample per cell
        cb = a[Wp * Hp:Wp * Hp * 5 // 4].reshape(Hp // 2, Wp // 2).astype(np.float32)
        cr = a[Wp * Hp * 5 // 4:].reshape(Hp // 2, Wp // 2).astype(np.float32)
        g = y.copy()
        for (y0, y1, x0, x1, (c, k)) in regions:
            g[y0:y1, x0:x1] = 128 + (y[y0:y1, x0:x1] - c) * k if c else y[y0:y1, x0:x1] * k
        img = np.repeat(np.clip(g, 0, 255)[..., None], 3, 2)
        for f in in_colour:
            fw, fh = f.size_px
            ys, xs = slice(f.y0 // 2, (f.y0 + fh) // 2), slice(f.x0 // 2, (f.x0 + fw) // 2)
            Y, U, V = y[ys, xs], cb[ys, xs] - 128, cr[ys, xs] - 128
            img[ys, xs] = np.clip(np.stack([Y + 1.402 * V, Y - 0.344136 * U - 0.714136 * V, Y + 1.772 * U], -1), 0, 255)
        if cell_px == 2:
            img = img.repeat(2, 0).repeat(2, 1)
        img = np.concatenate([img, np.zeros((cap, img.shape[1], 3), np.float32)], 0)
        img = img * (1 - alpha) + lab[..., :3] * alpha
        enc.stdin.write(np.round(img).astype(np.uint8).tobytes())
    enc.stdin.close()
    dec.kill(), dec.wait(), enc.wait()


def main(program, out="out"):
    name = program.NAME
    p = SETTINGS[name]
    m = program.build()
    glassbox(m, name, p["note"], p["cell_px"], p["stretch"], p["crf"], p["every"], p["seconds"], out,
             getattr(program, "CROP", "D"))
    if p["view_crf"] is None:          # (the Turing and Life pictures change everywhere every few frames: an
        return                         # enlarged copy costs as much as the original, which plays fine full-screen)
    size = 2 * m.fields["D"].w * p["scale"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(out, f"{name}.mp4"),
                    "-vf", f"scale={size}:{size}:flags=neighbor,{TO_TV}", "-c:v", "libx264", "-preset", "slow",
                    "-crf", str(p["view_crf"]), *TAGS, "-movflags", "+faststart",
                    os.path.join(out, f"{name}_view_{size}.mp4")], check=True)
