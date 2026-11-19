# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Sound on Linux: paplay (PulseAudio, PipeWire), else aplay (ALSA)."""
from platforms.posix import first_that_runs


def play_file(path):
    first_that_runs([["paplay", str(path)], ["aplay", "-q", str(path)]])
