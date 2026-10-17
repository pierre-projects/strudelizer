"""NFR-6 benchmark: convert a dense, deterministic 5-minute MIDI song.

    python tests/bench_dense.py [--strict]

Builds 150 bars of 4/4 at 120 bpm (5 minutes) with four busy parts
(~5,900 notes) and times the default one-shot pipeline. Not part of the
test suite, because timings depend on the machine.
"""

from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

import mido

from strudelizer import Pipeline

BARS = 150


def build(path: Path) -> int:
    rng = random.Random(1)
    mid = mido.MidiFile(ticks_per_beat=480)
    for channel, (low, high, step) in [(0, (36, 50, 120)), (1, (48, 72, 240)), (2, (60, 84, 120)), (9, (36, 42, 120))]:
        track = mido.MidiTrack()
        now = 0
        for tick in range(0, BARS * 1920, step):
            if rng.random() < 0.7:
                pitch = rng.choice([36, 38, 42]) if channel == 9 else rng.randint(low, high)
                track.append(mido.Message("note_on", channel=channel, note=pitch, velocity=rng.randint(60, 120), time=tick - now))
                track.append(mido.Message("note_off", channel=channel, note=pitch, time=step - 10))
                now = tick + step - 10
        mid.tracks.append(track)
    mid.save(str(path))
    return sum(1 for t in mid.tracks for m in t if m.type == "note_on")


def main() -> None:
    strict = "--strict" in sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dense.mid"
        notes = build(path)
        Pipeline(strict=strict).run(path)  # warm-up: imports, schema compile
        runs = []
        for _ in range(3):
            start = time.perf_counter()
            Pipeline(strict=strict).run(path)
            runs.append(time.perf_counter() - start)
    mode = "strict" if strict else "default"
    print(f"{notes} notes, {BARS} bars, {mode} mode: best {min(runs):.2f}s of {len(runs)} runs")


if __name__ == "__main__":
    main()
