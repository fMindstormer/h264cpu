"""python -m h264cpu life|spiral|turing|tunnel [--seconds 30] [--out out] [--no-check] [--hwaccel videotoolbox]
python -m h264cpu glassbox life|spiral|turing|tunnel [--out out]
python -m h264cpu web [--docs docs]"""
from __future__ import annotations

import argparse
import sys

from .programs import PROGRAMS


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["glassbox"]:
        from .glassbox import main as glassbox
        p = argparse.ArgumentParser(prog="python -m h264cpu glassbox")
        p.add_argument("program", choices=PROGRAMS)
        p.add_argument("--out", default="out")
        a = p.parse_args(argv[1:])
        glassbox(PROGRAMS[a.program], a.out)
        return
    if argv[:1] == ["web"]:
        from .web import main as web
        p = argparse.ArgumentParser(prog="python -m h264cpu web")
        p.add_argument("--docs", default="docs")
        web(p.parse_args(argv[1:]).docs)
        return
    from .build import write
    p = argparse.ArgumentParser(prog="python -m h264cpu", description="Write an H.264 video whose decoder runs a program.")
    p.add_argument("program", choices=PROGRAMS)
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument("--out", default="out")
    p.add_argument("--no-check", action="store_true", help="skip decoding every frame with ffmpeg")
    p.add_argument("--hwaccel", help="check with this ffmpeg hardware decoder, e.g. videotoolbox")
    a = p.parse_args(argv)
    _, _, result = write(PROGRAMS[a.program], a.seconds, a.out, check=not a.no_check, hwaccel=a.hwaccel)
    if result and result["identical"] != result["frames"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
