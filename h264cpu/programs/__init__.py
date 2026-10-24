"""Programs the decoder runs. Each module has NAME, build() -> Machine and start(m) -> (initial
values, stored fields or None for all, reference or None). Optional: CROP, the field players show
(default "D"), and FIRST, the fields frame 0 holds as raw samples (default: the cropped field)."""
from . import life, primes, spiral, tunnel, turing

PROGRAMS = {p.NAME: p for p in (life, spiral, turing, tunnel, primes)}
