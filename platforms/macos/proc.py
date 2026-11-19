# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Process checks: signal 0, so a reused pid is not detected."""
from platforms.posix import pid_alive

__all__ = ["pid_alive"]
