# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Single instance on Windows: a named mutex, held until the process ends."""
import ctypes

ERROR_ALREADY_EXISTS = 183
_mutex = None


def acquire():
    """True if no other copy of the widget runs."""
    global _mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = kernel32.CreateMutexW(None, False, "Local\\ClaudeIslandWidget")   # kept: closing it frees the name
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
