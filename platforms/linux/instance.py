# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Single instance: an flock on config/island.lock."""
from platforms.posix import acquire

__all__ = ["acquire"]
