# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Fonts and window quirks on Windows."""
import ctypes

UI_FONTS = ["Segoe UI Variable Text", "Segoe UI"]
SW_SHOW = 5


def fix_tool_window(widget):
    pass


def force_focus(widget):
    """Give the widget the keyboard."""
    # Windows refuses activateWindow() to a background app, so reuse the tricks that bring a chat to the front.
    from platforms.windows.winctl import _bring_front
    widget.activateWindow()
    _bring_front(int(widget.winId()))
    widget.setFocus()


def notch_rect(screen):
    return None


def float_over_menu_bar(widget, on):
    pass


def force_show(widget):
    """Show the window again if Windows swallowed the first show."""
    # A program started with a "hidden" window style gets that style applied to its first shown window.
    hwnd = int(widget.winId())
    if not ctypes.windll.user32.IsWindowVisible(hwnd):
        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
