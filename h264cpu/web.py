"""The browser builder: export the compiled programs and build the GitHub Pages site in docs/.

    python -m h264cpu web     writes docs/index.html, docs/h264cpu.js and life.json, tunnel.json, primes.json

The program frames do not depend on the starting pattern, so they are compiled here once; the page
(web/page.html with web/h264cpu.js) writes everything that does depend on it, byte for byte as Python.
"""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import numpy as np

from .programs import life, primes, tunnel

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/fMindstormer/h264cpu"


def export(m, given, path, crop_field="D", first=None, stored=None, level=51, fps=60, name="life", period=6,
           ship_given=False, extra=None):
    """The compiled program as JSON for web/h264cpu.js: layout, the cell ops (to write the starting
    state), and the 16 program frames. Picture fields start grey unless given. With ship_given, the
    starting values go in the JSON too, for a program whose start the page does not edit. extra: more
    keys for the page."""
    init = m.initial(given)
    frames = m.stream(init, 64, crop_field, level, fps, first=first, stored=stored)
    start = m.first_program_frame
    variants = {f % 16: frames[f] for f in range(start, start + 16)}
    prog = {
        "name": name, "W": m.W, "H": m.H, "period": period, "widthMbs": m.width_mbs, "heightMbs": m.height_mbs, "warm": m.max_delay(),
        "crop": crop_field, "first": sorted(m.first_picture), "level": level, "fps": fps,
        "firstProgramFrame": start,
        "fields": [{"name": n, "x0": f.x0, "y0": f.y0, "halo": f.halo, "shown": list(f.shown_px),
                    **({"image": list(f.image)} if f.image else {})} for n, f in m.fields.items()],
        "ops": [{"out": o.out, "kind": o.kind, "inputs": [list(i) for i in o.inputs],
                 "params": [list(p) for p in o.params], "L": list(o.L)} for o in m.ops.values() if o.kind != "warp"],
        "given": sorted(n for n in given if ship_given or not m.fields[n].image),
        "chunks": [sorted(c) for c in m.pcm_chunks],
        "programFrames": [base64.b64encode(variants[k]).decode() for k in range(16)],
        **(extra or {}),
    }
    if ship_given:      # each field's planes as base64 bytes, row by row
        prog["givenValues"] = {n: [base64.b64encode(np.asarray(p, np.uint8).tobytes()).decode() for p in given[n]]
                               for n in prog["given"]}
    Path(path).write_text(json.dumps(prog, separators=(",", ":")))
    return prog


def primes_given(m):
    """The CPU's starting values: the circuit's constants and state, and the first picture of the display."""
    init, _, _ = primes.start(m)
    return {n: init[n] for n in [*m.circuit.given(), primes.CROP]}


def page_document(page: str) -> str:
    """web/page.html is a page body for a host that adds the document skeleton; this adds it for Pages."""
    page = page.replace("<p id=\"repo-line\">Code, the Python compiler and the tests: the h264cpu repository.</p>",
                        f"<p id=\"repo-line\">Code, the Python compiler and the tests: <a href=\"{REPO}\">{REPO[8:]}</a>.</p>")
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<meta name="description" content="Can a video decoder execute a program? This page compiles Game of Life '
            'or a small CPU into a standard H.264 stream; after start-up the same 16 instruction frames repeat, and '
            'your browser\'s decoder computes every new state.">\n'
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
    m = primes.build()
    export(m, primes_given(m), docs / "primes.json", crop_field=primes.CROP, name="primes", period=primes.PERIOD,
           ship_given=True, extra={"program": sorted(primes.PROGRAM.items())})
    shutil.copy(ROOT / "web" / "h264cpu.js", docs / "h264cpu.js")
    (docs / "index.html").write_text(page_document((ROOT / "web" / "page.html").read_text()))
    (docs / ".nojekyll").write_text("")
    print(f"wrote {docs}/index.html, h264cpu.js, life.json, tunnel.json, primes.json")
