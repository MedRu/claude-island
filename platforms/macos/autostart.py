# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Autostart on macOS: the Claude Code hook command only, with no menu shortcut."""
from platforms.posix import hook_command, is_ours

__all__ = ["hook_command", "is_ours", "set_shortcut", "shortcut_exists", "shortcut_label", "shortcut_supported"]
shortcut_supported = False
shortcut_label = ""


def shortcut_exists():
    return False


def set_shortcut(on):
    pass
