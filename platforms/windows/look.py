# Claude Island - a desktop widget for watching your Claude Code sessions
# Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
"""Fonts and window quirks on Windows."""
import ctypes

UI_FONTS = ["Segoe UI Variable Text", "Segoe UI"]
SW_SHOW = 5
HWND_TOPMOST = ctypes.c_void_p(-1)
KEEP_FLAGS = 0x0002 | 0x0001 | 0x0010 | 0x0200    # SWP_NOMOVE | NOSIZE | NOACTIVATE | NOOWNERZORDER


def fix_tool_window(widget):
    pass


def app_identity(app):
    """Group our windows and notifications as "Claude Island", not as python.exe."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MedRu.ClaudeIsland")
    except (AttributeError, OSError):
        pass


def force_focus(widget):
    """Give the widget the keyboard."""
    # Windows refuses activateWindow() to a background app, so reuse the tricks that bring a chat to the front.
    from platforms.windows.winctl import _bring_front
    widget.activateWindow()
    _bring_front(int(widget.winId()))
    widget.setFocus()


HAS_GLASS = False


def glass(widget, rect, radius, dark=True):
    return False


def notch_rect(screen):
    return None


def keep_on_top(widget, over_menu_bar=False, bump=0, raise_front=True):
    """Put the island back in the topmost band.

    Windows drops a topmost window behind others now and then (after the taskbar or a full-screen app took
    the top, or another topmost window was shown), so this runs every second. It never takes the focus.
    bump and raise_front are no-ops here: Windows has no camera notch to share with other apps, so the
    island keeps re-asserting topmost as before.
    """
    if widget.isVisible():
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(int(widget.winId())), HWND_TOPMOST, 0, 0, 0, 0, KEEP_FLAGS)


def force_show(widget):
    """Show the window again if Windows swallowed the first show."""
    # A program started with a "hidden" window style gets that style applied to its first shown window.
    hwnd = int(widget.winId())
    if not ctypes.windll.user32.IsWindowVisible(hwnd):
        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
