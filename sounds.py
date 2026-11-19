# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""The widget's sound cues, synthesised once into config/sounds and played through the platform layer.

start is a soft low tock, needs two rising notes, done a short rising chime, warn two falling notes (usage
passed 75 % or 90 %) and limit three falling notes (100 %). Each note is a few decaying sine partials with a
smooth fade in and out and a small room echo. Your own .wav files can replace any cue. Run this file to hear
them all.
"""
import math
import struct
import sys
import threading
import time
import wave
from pathlib import Path

from platforms import get_platform

SOUND_DIR = Path(__file__).resolve().parent / "config" / "sounds"
VERSION = "3"          # bump to rebuild everyone's WAVs after changing the synthesis
RATE = 44100
TIMBRE = [(1.0, 1.0, 1.0), (2.0, 0.22, 1.8), (3.0, 0.07, 2.6), (4.2, 0.03, 4.5)]  # (ratio, level, decay factor)
ECHOES = [(0.023, 0.10), (0.041, 0.06), (0.067, 0.03)]                            # (delay s, level)
CUES = {  # name -> (peak dBFS, [(Hz, start s, decay /s)])
    "start": (-24, [(392.00, 0.00, 22.0)]),
    "needs": (-15, [(659.25, 0.00, 7.0), (880.00, 0.13, 5.5)]),
    "done": (-17, [(659.25, 0.00, 7.5), (783.99, 0.085, 7.0), (1046.50, 0.17, 4.5)]),
    "warn": (-17, [(783.99, 0.00, 7.0), (622.25, 0.16, 5.5)]),
    "limit": (-14, [(659.25, 0.00, 6.5), (523.25, 0.16, 6.0), (392.00, 0.32, 3.5)]),
}
PRIORITY = ("limit", "needs", "warn", "done", "start")      # only the most important cue of a batch plays
MIN_GAP = {"start": 2.0, "needs": 1.0, "done": 1.0, "warn": 5.0, "limit": 5.0}   # s between repeats

_volume = None         # None until configure() is first called
_files = {}
_last = {}
_worker = None


def _note(freq, decay):
    n = int(min(2.0, math.log(1000) / decay) * RATE)       # rings until about 60 dB down
    fade_in, fade_out = int(0.004 * RATE), int(0.030 * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        v = sum(level * math.exp(-decay * k * t) * math.sin(2 * math.pi * freq * ratio * t)
                for ratio, level, k in TIMBRE)
        # raised-cosine fades, so the note starts and ends without a click
        if i < fade_in:
            v *= 0.5 - 0.5 * math.cos(math.pi * i / fade_in)
        if i > n - fade_out:
            v *= 0.5 - 0.5 * math.cos(math.pi * (n - i) / fade_out)
        out.append(v)
    return out


def render(name, volume=100):
    """The cue as 16-bit mono PCM."""
    peak_db, notes = CUES[name]
    parts = [(int(start * RATE), _note(freq, decay)) for freq, start, decay in notes]
    length = max(at + len(part) for at, part in parts) + int(ECHOES[-1][0] * RATE)
    mix = [0.0] * length
    for at, part in parts:
        for delay, level in [(0, 1.0)] + ECHOES:
            offset = at + int(delay * RATE)
            for i, v in enumerate(part):
                mix[offset + i] += level * v
    gain = 10 ** (peak_db / 20) * max(volume, 0) / 100 / max(abs(v) for v in mix)
    return b"".join(struct.pack("<h", int(round(v * gain * 32767))) for v in mix)


def ensure():
    """Build the WAVs if they are missing or were made by another VERSION or volume."""
    SOUND_DIR.mkdir(parents=True, exist_ok=True)
    volume = 100 if _volume is None else _volume
    stamp, want = SOUND_DIR / "version.txt", f"{VERSION}:{volume}"
    fresh = stamp.exists() and stamp.read_text(encoding="utf-8").strip() == want
    for name in CUES:
        path = SOUND_DIR / f"{name}.wav"
        if fresh and path.exists():
            continue
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(render(name, volume))
    stamp.write_text(want, encoding="utf-8")


def configure(volume=100, files=None):
    """Set the volume in % for the built-in cues, and files = {cue: path to your own .wav}."""
    global _volume, _files, _worker
    _files = {k: v for k, v in (files or {}).items() if v and Path(v).is_file()}
    if int(volume) == _volume:
        return
    _volume = int(volume)
    # Rebuilding takes about a second, so it runs on one background worker. A slider sends many values;
    # the worker keeps going until it has built the latest one.
    if not (_worker and _worker.is_alive()):
        _worker = threading.Thread(target=_rebuild, daemon=True)
        _worker.start()


def _rebuild():
    built = None
    while built != _volume:
        built = _volume
        try:
            ensure()
        except OSError as e:            # e.g. disk full, or a WAV locked while playing
            print("sounds: could not build the WAVs:", e, file=sys.stderr)
            return


def play(name, force=False):
    now = time.monotonic()
    if not force and now - _last.get(name, -1e9) < MIN_GAP.get(name, 1.0):
        return
    _last[name] = now
    path = _files.get(name) or SOUND_DIR / f"{name}.wav"
    try:
        if not Path(path).exists():
            ensure()
        get_platform().sound.play_file(path)
    except (OSError, RuntimeError):
        pass


def play_most_important(names):
    for name in PRIORITY:
        if name in names:
            play(name)
            return


if __name__ == "__main__":
    ensure()
    for cue in CUES:
        print("playing", cue)
        play(cue)
        time.sleep(1.4)
