"""The browser builder: export the compiled Life program and build the GitHub Pages site in docs/.

    python -m h264cpu web     writes docs/index.html, docs/h264cpu.js, docs/life.json and docs/tunnel.json

The program frames do not depend on the starting pattern, so they are compiled here once; the page
(web/page.html with web/h264cpu.js) writes everything that does depend on it, byte for byte as Python.
"""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

from .programs import life, tunnel

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/fMindstormer/h264cpu"


def export(m, given, path, crop_field="D", first=None, stored=None, level=51, fps=60, name="life"):
    """The compiled program as JSON for web/h264cpu.js: layout, the cell ops (to write the starting
    state), and the 16 program frames. Picture fields start grey and live only in the decoder."""
    init = m.initial(given)
    frames = m.stream(init, 64, crop_field, level, fps, first=first, stored=stored)
    start = m.first_program_frame
    variants = {f % 16: frames[f] for f in range(start, start + 16)}
    prog = {
        "name": name, "N": m.W, "widthMbs": m.width_mbs, "heightMbs": m.height_mbs, "warm": m.max_delay(),
        "crop": crop_field, "first": sorted(m.first_picture), "level": level, "fps": fps,
        "firstProgramFrame": start,
        "fields": [{"name": n, "x0": f.x0, "y0": f.y0, "halo": f.halo, "image": bool(f.image),
                    "shown": list(f.shown_px)} for n, f in m.fields.items()],
        "ops": [{"out": o.out, "kind": o.kind, "inputs": [list(i) for i in o.inputs],
                 "params": [list(p) for p in o.params], "L": list(o.L)} for o in m.ops.values() if o.kind != "warp"],
        "given": sorted(n for n in given if not m.fields[n].image),
        "chunks": [sorted(c) for c in m.pcm_chunks],
        "programFrames": [base64.b64encode(variants[k]).decode() for k in range(16)],
    }
    Path(path).write_text(json.dumps(prog, separators=(",", ":")))
    return prog


def page_document(page: str) -> str:
    """web/page.html is a page body for a host that adds the document skeleton; this adds it for Pages."""
    page = page.replace("<p id=\"repo-line\">Code, the Python compiler and the tests: the h264cpu repository.</p>",
                        f"<p id=\"repo-line\">Code, the Python compiler and the tests: <a href=\"{REPO}\">{REPO[8:]}</a>.</p>")
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="description" content="Draw a Game of Life pattern. The page hands your browser\'s H.264 '
            'decoder one small program frame, forever, and the decoder computes every generation, in a 1920x1080 '
            'tunnel it also zooms and turns.">\n'
            '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);'
            'padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}'
            '[hidden]{display:none!important}</style>\n</head>\n<body>\n' + page + '\n</body>\n</html>\n')


def main(docs="docs"):
    docs = Path(docs)
    docs.mkdir(parents=True, exist_ok=True)
    m = life.build()
    export(m, life.given(life.soup()), docs / "life.json")
    m = tunnel.build()
    _, stored, _ = tunnel.start(m)
    export(m, tunnel.start_given(tunnel.soup()), docs / "tunnel.json", crop_field=tunnel.CROP, first=tunnel.FIRST,
           stored=stored, name="tunnel")
    shutil.copy(ROOT / "web" / "h264cpu.js", docs / "h264cpu.js")
    (docs / "index.html").write_text(page_document((ROOT / "web" / "page.html").read_text()))
    (docs / ".nojekyll").write_text("")
    print(f"wrote {docs}/index.html, h264cpu.js, life.json, tunnel.json")
