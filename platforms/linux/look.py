# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Fonts and window quirks on Linux."""
from platforms.posix import float_over_menu_bar, force_focus, force_show, notch_rect, system_fonts

__all__ = ["fix_tool_window", "force_show", "force_focus", "notch_rect", "float_over_menu_bar"]


def __getattr__(name):
    # UI_FONTS asks Qt for the desktop font, which only works once the app is running.
    if name == "UI_FONTS":
        return system_fonts()
    raise AttributeError(name)


def fix_tool_window(widget):
    pass
